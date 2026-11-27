import json
from pathlib import Path
from time import monotonic
import unittest
from unittest.mock import patch

from app import app
from hackathon_cli import audit_document, overlaps_rule
from hackathon_review import IndividualReview, SetIssue, completed_steps, review_requirements_steps, source_blocks
from public_links import check_public_url, public_address
from review_snapshot import read_snapshot, sign_snapshot
from review_rules import rule_findings


FIXTURES = Path(__file__).parent / "fixtures"


class UnifiedAuditTests(unittest.TestCase):
    def test_unavailable_provider_runs_rules_and_labels_the_result(self):
        with patch("hackathon_review.is_configured", return_value=False), app.test_client() as client:
            source = (FIXTURES / "quality-broken.md").read_text(encoding="utf-8")
            response = client.post("/api/analyze/gemini?operation=report&fallback=rules",
                                   json={"text": source}, headers={"Accept": "application/x-ndjson"})
            self.assertEqual(response.status_code, 200)
            events = [json.loads(line) for line in response.data.splitlines()]
            self.assertEqual([event["stage"] for event in events[:-1]],
                             ["read", "segment", "rules", "references", "verified", "report"])
            report = events[-1]["report"]
            audit = report["review"]
            self.assertTrue(audit["findings"])
            self.assertEqual(audit["mode"], "rules")
            self.assertEqual(audit["ai_unavailable"], "gemini_unconfigured")
            self.assertTrue(all(item["assessment_status"] == "unchecked" for item in audit["requirements"]))
            self.assertIn("ИИ-проверка недоступна, выполнены только правила", report["markdown"])
            legacy = client.post("/api/analyze/gemini?operation=report", json={"text": source})
            self.assertEqual(legacy.status_code, 503)

    def test_arithmetic_wording_and_attachment_checks_have_source_lines(self):
        file = FIXTURES / "quality-broken.md"
        lines = file.read_text(encoding="utf-8").splitlines()
        result = audit_document(file, file.read_bytes(), rules_only=True)
        explanations = [item["explanation"] for item in result["findings"]]
        for phrase in ("сумма строк равна 50", "сумма её компонентов равна 35",
                       "интуитивно", "policies/refund.pdf", "ожидаемый результат"):
            self.assertTrue(any(phrase in explanation for explanation in explanations), phrase)
        for issue in result["findings"]:
            self.assertTrue(issue["evidence"])
            for ref in issue["evidence"]:
                self.assertIn(ref["quote"], "\n".join(lines[ref["line"] - 1:ref["end"]]))

    def test_consistent_tables_and_requirements_remain_clean(self):
        file = FIXTURES / "quality-clear.md"
        result = audit_document(file, file.read_bytes(), rules_only=True)
        self.assertFalse(result["findings"])

    def test_duplicate_calculation_and_empty_cell_questions_preserve_separate_decisions(self):
        text = (FIXTURES / "quality-broken.md").read_text(encoding="utf-8")
        _, blocks = source_blocks(text, structured=True)
        rules = [SetIssue.model_validate(item) for item in rule_findings(blocks)]
        cases = [
            ("В строке указан итог", "consistency", "Сумма значений в строке не равна итогу.",
             "Какое значение должно быть в колонке итога?", "В какой валюте округлять итог?"),
            ("Нижняя граница", "feasibility", "Задан некорректный диапазон хранения.",
             "Какой точный срок хранения отчёта следует установить?", "С какого события считается срок хранения?"),
            ("В строке приёмки", "completeness", "В таблице полностью отсутствует ожидаемый результат.",
             "Какой именно результат должен отображаться в отчёте?", "Какой HTTP-статус возвращает архив?"),
            ("Выражение «интуитивно»", "verifiability", "Требование об интуитивном отображении субъективно.",
             "Каковы конкретные правила отображения комиссии при приёмке?", "Каковы конкретные правила отображения комиссии при приёмке?"),
        ]
        for prefix, criterion, explanation, duplicate, independent in cases:
            rule = next(item for item in rules if item.explanation.startswith(prefix))
            model = rule.model_copy(update={"criterion": criterion, "explanation": explanation, "question": duplicate})
            self.assertTrue(overlaps_rule(model, rule), duplicate)
            separate = {"question": independent}
            if duplicate == independent:
                separate["explanation"] = "Нужно уточнить другой аспект."
            self.assertFalse(overlaps_rule(model.model_copy(update=separate), rule), independent)

    def test_public_probe_never_connects_if_resolution_includes_nonpublic_address(self):
        records = [(2, 1, 6, "", ("93.184.215.14", 443)), (2, 1, 6, "", ("10.0.0.17", 443))]
        with patch("public_links.socket.getaddrinfo", return_value=records), \
                patch("public_links.socket.create_connection") as connect:
            self.assertEqual(check_public_url("https://public.example.org/ref", monotonic() + 5), "blocked")
            self.assertEqual(check_public_url("https://localhost/ref", monotonic() + 5), "blocked")
            self.assertEqual(check_public_url("https://public.example.org/ref?token=x", monotonic() + 5), "manual")
            connect.assert_not_called()
        for address in ("100.64.0.1", "169.254.9.1", "127.0.0.1", "::ffff:10.0.0.17", "::1", "fe80::7"):
            self.assertFalse(public_address(address), address)

    def test_recheck_reuses_only_authenticated_unchanged_clauses_and_still_checks_the_set(self):
        text = "\n\n".join(f"Ф-{number}. Сервис хранит документ {number} 30 дней." for number in range(1, 7))
        delta = text.replace("документ 4 30", "документ 4 40")
        seen = []

        def provider(output_type, instruction, data, tokens, validate, models):
            ids = [part["ref"] for part in data["blocks"] if part["source_id"]]
            seen.append((output_type, ids))
            if output_type is IndividualReview:
                answer = {"requirements": [{"ref": part["ref"], "quote": part["text"], "summary": part["text"],
                                             "assessment": "Указан измеримый срок.", "issues": []}
                                            for part in data["blocks"] if part["source_id"]]}
            else:
                check = {"outcome": "ok", "comment": "Сроки определены.", "refs": ids[:1]}
                answer = {name: check for name in ("consistency", "completeness", "traceability", "feasibility")}
                answer["issues"] = []
            return validate(output_type.model_validate(answer)), "test-model", models[0]

        snapshot = {}
        with patch.dict("os.environ", {"SANA1_RECHECK_SECRET": "test-secret"}), \
                patch("hackathon_review.is_configured", return_value=True), \
                patch("hackathon_review.run_stage", side_effect=provider):
            completed_steps(review_requirements_steps(text, "md", snapshot=snapshot))
            token = sign_snapshot(snapshot, "abc")
            self.assertTrue(token)
            self.assertEqual(read_snapshot(token, "other"), {})
            changed_signature = token[:-8] + "badtoken"
            self.assertEqual(read_snapshot(changed_signature, "abc"), {})
            previous = read_snapshot(token, "abc")
            seen.clear()
            result = completed_steps(review_requirements_steps(delta, "md", previous=previous))
            self.assertEqual(len(result[2]), 6)
            self.assertEqual(seen[0][1], ["L5", "L7", "L9"])
            self.assertEqual(seen[1][1], ["L1", "L3", "L5", "L7", "L9", "L11"])
