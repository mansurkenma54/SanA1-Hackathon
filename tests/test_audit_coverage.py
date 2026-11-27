import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from hackathon_cli import audit_document
from hackathon_review import SetReview, needs_assessment, set_results, source_blocks


CONFIG = {"GEMINI_API_KEY": "test-only", "GEMINI_MODEL": "gemini-test", "GEMINI_FALLBACK_MODEL": ""}
SOURCE = (
    "# Card service\n\n"
    "REQ-1. The ledger must retain processed transfers.\n\n"
    "## Operational constraints\n"
    "A client is required to send a unique reference for each transfer.\n\n"
    "### Examples\n"
    "The mock client must send DEMO as the reference.\n"
)


def model_answer(data):
    return {"modelVersion": "gemini-test", "candidates": [
        {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(data)}]}}
    ]}


def assessment(block):
    return {"ref": block["ref"], "quote": block["text"], "summary": "Условие обработки перевода",
            "assessment": "В тексте задано проверяемое условие.", "issues": []}


class MandatoryCoverageTests(unittest.TestCase):
    def test_adjacent_unnumbered_obligations_require_separate_source_lines(self):
        source = ("# Processing\n"
                  "The service must store each accepted transfer\n"
                  "before acknowledging receipt.\n"
                  "The client shall preserve its confirmation.\n"
                  "Оператор должен получить номер операции.\n\n"
                  "Example: The simulator must log TEST.\n"
                  "Test clients must read this value.\n\n"
                  "REQ-2. The processor must log the outcome.\n"
                  "This entry must include the identifier.")
        _, blocks = source_blocks(source, structured=True)
        required = [block for block in blocks if needs_assessment(block)]
        self.assertEqual([(block.line, block.end) for block in required], [(2, 3), (4, 4), (5, 5), (10, 11)])
        self.assertEqual(required[-1].source_id, "REQ-2")
        for block in required:
            self.assertEqual(block.text, "\n".join(source.splitlines()[block.line - 1:block.end]))

    def test_set_assessment_cannot_keep_conclusion_with_invented_source(self):
        _, blocks = source_blocks("The bank must retain the transfer ID.", structured=True)
        good = {"outcome": "ok", "comment": "Пункт содержит проверяемое обязательство.", "refs": ["L1"]}
        payload = dict.fromkeys(("consistency", "completeness", "traceability", "feasibility"), good)
        payload["consistency"] = {**good, "refs": ["L1", "L94"]}
        reviewed, _ = set_results(SetReview.model_validate({**payload, "issues": []}), {"L1": blocks[0]})
        self.assertEqual((reviewed.consistency.outcome, reviewed.consistency.refs), ("unknown", []))
        self.assertEqual(reviewed.completeness.outcome, "ok")

    def test_explicit_unnumbered_obligations_across_languages(self):
        obligations = [
            "A client is required to send a reference.",
            "Duplicate references are prohibited.",
            "Повторное зачисление не допускается.",
            "Запрещается выводить полный номер карты в журнал.",
        ]
        context = [
            "Example: A client is required to send the value DEMO.",
            "**Пример:** Клиент должен отправить тестовое значение.",
            "A PIN is not required to open the help page.",
        ]
        for structured in (True, False):
            with self.subTest(structured=structured):
                _, blocks = source_blocks("\n\n".join(obligations + context), structured)
                self.assertEqual([block.text for block in blocks if needs_assessment(block)], obligations)

    @patch.dict(os.environ, CONFIG)
    def test_missing_obligation_is_retried_and_examples_remain_available(self):
        selected = []

        def provider(_model, payload, _timeout):
            data = json.loads(payload["contents"][0]["parts"][0]["text"])
            required = data.get("required_refs")
            selected.append(required)
            blocks = {block["ref"]: block for block in data["blocks"]}
            if required == ["L3", "L6"]:
                self.assertIn("L9", blocks)
                return model_answer({"requirements": [assessment(blocks["L3"])]})
            if required == ["L6"]:
                self.assertEqual(list(blocks), ["L6"])
                return model_answer({"requirements": [assessment(blocks["L6"])]})
            self.assertIn("L9", blocks)
            self.assertEqual([entry["ref"] for entry in data["requirements"]], ["L3", "L6"])
            grounded = {"outcome": "ok", "comment": "Рассмотрены указанные ограничения.", "refs": ["L3", "L6"]}
            return model_answer(dict.fromkeys(("consistency", "completeness", "traceability", "feasibility"), grounded)
                                | {"issues": []})

        with patch("hackathon_review.generate", side_effect=provider):
            result = audit_document(Path("card.md"), SOURCE.encode())

        self.assertEqual(selected, [["L3", "L6"], ["L6"], None])
        quotes = [item["source"]["quote"] for item in result["requirements"]]
        self.assertEqual(quotes, [SOURCE.splitlines()[2], SOURCE.splitlines()[5]])

    @patch.dict(os.environ, CONFIG)
    def test_persistent_omission_cannot_produce_a_ready_report(self):
        data = {"ref": "L3", "text": SOURCE.splitlines()[2]}
        with patch("hackathon_review.generate", side_effect=[
            model_answer({"requirements": [assessment(data)]}), model_answer({"requirements": []}),
        ]) as generate:
            with self.assertRaisesRegex(ValueError, "gemini_incomplete_inventory"):
                audit_document(Path("card.md"), SOURCE.encode())
            self.assertEqual(generate.call_count, 2)

    @patch.dict(os.environ, CONFIG)
    def test_invalid_table_quote_is_rechecked_without_erasing_the_source(self):
        source = ("# API\n\n## Общие параметры\n"
                  "| Поле | Значение |\n| --- | --- |\n"
                  "| **Request URL** | Dev: `/alerts/saveLimit` . Prod: — |\n")
        row = source.splitlines()[-1]
        invalid = assessment({"ref": "L6", "text": "/invented/path"})
        good = assessment({"ref": "L6", "text": "`/alerts/saveLimit`"})
        check = {"outcome": "ok", "comment": "Адрес операции приведён.", "refs": ["L6"]}
        whole = dict.fromkeys(("consistency", "completeness", "traceability", "feasibility"), check) | {"issues": []}
        for retry, expected in ((good, "reviewed"), (invalid, "unchecked")):
            with self.subTest(expected=expected), patch("hackathon_review.generate", side_effect=[
                model_answer({"requirements": [invalid]}), model_answer({"requirements": [retry]}), model_answer(whole)
            ]) as request:
                audit = audit_document(Path("settings.md"), source.encode())
                payload = json.loads(request.call_args_list[1].args[1]["contents"][0]["parts"][0]["text"])
                self.assertEqual([(b["ref"], b["text"]) for b in payload["blocks"]], [("L6", row)])
                self.assertEqual(len(audit["requirements"]), 1)
                requirement = audit["requirements"][0]
                self.assertEqual(requirement["assessment_status"], expected)
                self.assertEqual(requirement["source"]["quote"], good["quote"] if expected == "reviewed" else row)
                self.assertEqual(any("неточных цитат" in warning for warning in audit["warnings"]), expected == "unchecked")
