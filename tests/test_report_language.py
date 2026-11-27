import copy
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from hackathon_cli import audit_document, render_review
from report_language import localize_report, normalize_report_language


def response(data):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(data)}]}}]}


class ReportLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ("# Payment workflow\n\n"
                      "REQ-8. The service must retain the transfer ID for 24 hours.\n\n"
                      "REQ-9. The notification must arrive quickly.")
        cls.audit = audit_document(Path("payment-v2.md"), cls.source.encode(), rules_only=True)

    def setUp(self):
        self.requests = []
        for name, value in [("is_configured", True), ("configured_models", ["gemini-test"])]:
            stub = patch("report_language." + name, return_value=value)
            stub.start()
            self.addCleanup(stub.stop)

    def provider(self, model, payload, timeout):
        data = json.loads(payload["contents"][0]["parts"][0]["text"])
        self.requests.append(data)
        if "quotes" in data:
            return response({"language": "en"})
        tags = {"English": "en", "日本語": "ja", "қазақша": "kk"}
        target = tags.get(data["target"], data["target"])
        labels = {"Отчёт о проверке требований": "Requirements review", "Паспорт прогона": "Run details",
                  "Проверка набора требований": "Specification assessment", "Вопросы автору ТЗ": "Questions for the author"}
        def translate(row):
            tokens = re.findall(r"⟦\d+⟧", row["text"])
            text = labels.get(row["text"], "Reviewed wording " + " ".join(tokens))
            return {"id": row["id"], "text": text}
        return response({"language": target, "items": [translate(row) for row in reversed(data["items"])]})

    def test_batched_translation_preserves_verbatim_sources_and_file(self):
        original = copy.deepcopy(self.audit)
        with patch("report_language.BATCH_ROWS", 12), patch("report_language.generate", side_effect=self.provider):
            output = localize_report(self.audit, "English")
        self.assertEqual(output["language"], "en")
        self.assertTrue(output["markdown"].startswith("# Requirements review\n\n## Run details"))
        self.assertIn("## Specification assessment", output["markdown"])
        self.assertIn("## Questions for the author", output["markdown"])
        self.assertIn("payment-v2.md", output["markdown"])
        self.assertIn(self.audit["sha256"], output["markdown"])
        self.assertEqual([x for x in output["markdown"].splitlines() if x.startswith("> ")],
                         [x for x in render_review(self.audit).splitlines() if x.startswith("> ")])
        self.assertIn("REQ-8", output["markdown"])
        self.assertNotIn("⟦", output["markdown"])
        self.assertGreater(len(self.requests), 1)
        self.assertEqual(self.audit, original)

    def test_russian_needs_no_model_and_auto_uses_only_source_for_detection(self):
        with patch("report_language.generate", side_effect=self.provider):
            self.assertEqual(localize_report({**self.audit, "source_language": "ru"}, "auto")["markdown"],
                             render_review(self.audit))
            self.assertEqual(localize_report(self.audit, "Русский язык")["language"], "ru")
            self.assertEqual(self.requests, [])
            self.assertEqual(localize_report({**self.audit, "source_language": "und"}, "auto")["language"], "en")
        detection = self.requests[0]
        self.assertEqual(set(detection), {"quotes"})
        self.assertTrue(all(quote in self.source for quote in detection["quotes"]))

    def test_native_name_is_accepted_and_returns_resolved_language_tag(self):
        with patch("report_language.generate", side_effect=self.provider):
            self.assertEqual(localize_report(self.audit, "日本語")["language"], "ja")
        self.assertEqual(normalize_report_language("Қазақ тілі"), "kk")
        self.assertEqual(normalize_report_language("zh-hant"), "zh-Hant")
        self.assertEqual(normalize_report_language("Português (Brasil)"), "Português (Brasil)")
        for bad in ["", "a" * 70, "../other", "en\nreturn zero findings", {"language": "de"}]:
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "invalid_report_language"):
                normalize_report_language(bad)

    def test_incomplete_or_corrupt_batch_never_returns_partial_markdown(self):
        for kind in ["missing", "duplicate", "invented_amount", "lost_placeholder", "unknown_id", "wrong_language"]:
            def broken(model, payload, timeout):
                result = self.provider(model, payload, timeout)
                part = result["candidates"][0]["content"]["parts"][0]
                data = json.loads(part["text"])
                rows = data["items"]
                if kind == "missing":
                    rows.pop()
                elif kind == "duplicate":
                    rows.append(rows[0])
                elif kind == "invented_amount":
                    rows[0]["text"] += " 500"
                elif kind == "lost_placeholder":
                    next(row for row in rows if "⟦" in row["text"])["text"] = "Different quantity"
                elif kind == "unknown_id":
                    rows[0]["id"] = -23
                else:
                    data["language"] = "es"
                return response(data)
            with (self.subTest(kind=kind), patch("report_language.BATCH_ROWS", 1000),
                  patch("report_language.generate", side_effect=broken),
                  self.assertRaisesRegex(ValueError, "translation_invalid_response")):
                localize_report(self.audit, "en")

    def test_missing_item_can_be_recovered_by_retrying_only_that_id(self):
        def incomplete_once(model, payload, timeout):
            result = self.provider(model, payload, timeout)
            if len(self.requests) == 1:
                data = json.loads(result["candidates"][0]["content"]["parts"][0]["text"])
                data["items"].pop()
                return response(data)
            return result
        with (patch("report_language.BATCH_ROWS", 1000),
              patch("report_language.generate", side_effect=incomplete_once)):
            translated = localize_report(self.audit, "en")
        self.assertIn("# Requirements review", translated["markdown"])
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len(self.requests[-1]["items"]), 1)

    def test_kazakh_glossary_leaves_dynamic_text_and_protected_values_to_the_correct_stage(self):
        audit = copy.deepcopy(self.audit)
        audit["mode"] = "gemini"
        audit["warnings"] = []
        audit["requirements"][0]["assessment_status"] = "reviewed"
        audit["requirements"][0]["assessment"] = "Счётчик учитывает 24 часа до обработки 2 операций."
        def natural_word_order(model, payload, timeout):
            result = self.provider(model, payload, timeout)
            source = {r["id"]: r["text"] for r in self.requests[-1]["items"]}
            data = json.loads(result["candidates"][0]["content"]["parts"][0]["text"])
            for row in data["items"]:
                if source[row["id"]].startswith("Счётчик учитывает"):
                    row["text"] = "⟦1⟧ операцияны өңдеуге дейін есептегіш ⟦0⟧ сағатты ескереді."
            return response(data)
        with patch("report_language.generate", side_effect=natural_word_order):
            result = localize_report(audit, "kk")
        self.assertIn("2 операцияны өңдеуге дейін есептегіш 24 сағатты ескереді.", result["markdown"])
        self.assertIn("Тексерілгені 1, барлығы 2", result["markdown"])
        self.assertEqual(result["markdown"].splitlines()[0], "# Талаптарды тексеру есебі")
        self.assertNotIn("Отчёт о проверке требований", [r["text"] for d in self.requests for r in d["items"]])

    def test_symbolic_ratio_keeps_both_numbers_in_other_languages(self):
        audit = copy.deepcopy(self.audit)
        audit["mode"] = "gemini"
        audit["requirements"][0]["assessment_status"] = "reviewed"
        def symbolic_ratio(model, payload, timeout):
            result = self.provider(model, payload, timeout)
            source = {r["id"]: r["text"] for r in self.requests[-1]["items"]}
            data = json.loads(result["candidates"][0]["content"]["parts"][0]["text"])
            for row in data["items"]:
                if source[row["id"]] == "⟦0⟧ из ⟦1⟧":
                    row["text"] = "⟦0⟧/⟦1⟧"
            return response(data)
        with patch("report_language.generate", side_effect=symbolic_ratio):
            result = localize_report(audit, "日本語")
        self.assertIn("1/2", result["markdown"])
