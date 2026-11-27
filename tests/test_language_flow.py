import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import app
from hackathon_cli import audit_document, render_review, review_file
from report_terms import report_terms
from source_language import detect_source_language


class LanguageFlowTests(unittest.TestCase):
    def test_glossary_preserves_numbers_and_respects_script_requests(self):
        for language in ("kk", "en", "kk-Cyrl-KZ", "en-GB"):
            terms = report_terms(language)
            self.assertIn("⟦0⟧ из ⟦1⟧", terms)
            for source, target in terms.items():
                self.assertEqual(re.findall(r"⟦\d+⟧", source), re.findall(r"⟦\d+⟧", target))
        self.assertFalse(report_terms("kk-Latn"))
        self.assertFalse(report_terms("ja"))

    def test_uploaded_language_is_independent_of_interface_and_code_examples(self):
        texts = {
            "kk": "Клиент төлемді растаған кезде жүйе түбіртекті жіберуі керек.",
            "ru": "После подтверждения платежа система должна отправить клиенту квитанцию.",
            "en": "The service must issue a receipt when the customer confirms the payment.",
        }
        client = app.test_client()
        for language, text in texts.items():
            with self.subTest(language=language):
                source = text + "\n\n```json\n" + ('{"message":"payment accepted"}\n' * 12) + "```"
                response = client.post("/api/analyze?operation=report", data=source.encode(),
                                       content_type="application/octet-stream",
                                       headers={"X-File-Name": "spec.md", "Accept": "application/json",
                                                "Accept-Language": "ru"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["review"]["source_language"], language)
        self.assertEqual(detect_source_language("123 `GET`"), "und")

    def test_auto_export_localizes_report_and_worksheet_together(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, output = base / "receipt.md", base / "report.md"
            source.write_text("The system must provide the receipt quickly.", encoding="utf-8")
            audit = audit_document(source, source.read_bytes(), rules_only=True)
            raw = render_review(audit)
            translated = raw.replace("Вопросы автору ТЗ", "Questions for the author")
            targets = [output, output.with_suffix(".answers.md"), output.with_suffix(".json")]
            def steps(*args, **kwargs):
                yield "report"
                return audit
            with patch("hackathon_cli.audit_document_steps", steps), patch("report_language.localize_report") as localize:
                localize.return_value = {"language": "en", "markdown": translated}
                review_file(source, output, language="auto", answers_path=targets[1], json_path=targets[2])
                localize.assert_called_once_with(audit, "en", model=None)
                self.assertEqual(output.read_text(encoding="utf-8"), translated)
                self.assertTrue(targets[1].read_text(encoding="utf-8").startswith("# Questions for the author"))
                self.assertEqual(json.loads(targets[2].read_text(encoding="utf-8"))["source_language"], "en")
                saved = [p.read_bytes() for p in targets]
                localize.side_effect = ValueError("gemini_quota")
                with self.assertRaisesRegex(ValueError, "gemini_quota"):
                    review_file(source, output, language="auto", answers_path=targets[1], json_path=targets[2])
                self.assertEqual([p.read_bytes() for p in targets], saved)
