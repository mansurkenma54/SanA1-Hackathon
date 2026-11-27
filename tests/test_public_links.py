from io import BytesIO
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from docx import Document
from hackathon_cli import audit_document
from public_links import github_repository, web_urls
from word_output import build_word


PUBLIC_CASE = "https://github.com/BCC-HUB/ai-requirements-validator-task"


class PublicLinkTests(unittest.TestCase):
    def test_demo_audit_extracts_links_and_reports_a_dangling_reference(self):
        path = Path(__file__).resolve().parents[1] / "public" / "qr-refund-demo.docx"
        audit = audit_document(path, path.read_bytes(), rules_only=True)
        self.assertEqual([(link["target"], link["status"]) for link in audit["references"]],
                         [("QR-06", "resolved"), ("QR-09", "missing")])
        self.assertEqual(len(audit["external_references"]), 2)
        link = audit["external_references"][0]
        self.assertEqual(link["url"], PUBLIC_CASE)
        self.assertEqual(link["check"], "github")
        self.assertTrue(link["origins"])

    def test_url_inventory_strips_prose_punctuation(self):
        text = f"См. [кейс]({PUBLIC_CASE}). Связанные сведения https://example.org/wiki/Example_(topic)."
        self.assertEqual(list(web_urls(text)), [PUBLIC_CASE, "https://example.org/wiki/Example_(topic)"])

    def test_word_export_keeps_a_clickable_link_and_text(self):
        original = f"См. {PUBLIC_CASE}."
        document = Document(BytesIO(build_word({"text": original, "locale": "ru"})))
        self.assertEqual(document.paragraphs[0].text, original)
        self.assertEqual(document.paragraphs[0].hyperlinks[0].url, PUBLIC_CASE)

    def test_public_check_calls_only_the_github_repository_adapter(self):
        with patch("app.check_public_repository", return_value="public") as check, app.test_client() as client:
            response = client.get("/api/public-link", query_string={"url": PUBLIC_CASE})
            self.assertEqual(response.json, {"status": "public"})
            check.assert_called_once_with("BCC-HUB", "ai-requirements-validator-task")
            for url in ("https://example.org/project", PUBLIC_CASE + "/blob/main/README.md", PUBLIC_CASE + "?x=1"):
                self.assertIsNone(github_repository(url))
                self.assertEqual(client.get("/api/public-link", query_string={"url": url}).json, {"status": "manual"})
            self.assertEqual(check.call_count, 1)

    def test_main_audit_stream_includes_link_results_and_markdown(self):
        with patch("public_links.check_public_repository", return_value="public") as check, app.test_client() as client:
            response = client.post("/api/analyze?operation=report",
                                   json={"text": f"Ф-1. Использовать методику {PUBLIC_CASE}."},
                                   headers={"Accept": "application/x-ndjson"})
            events = [json.loads(line) for line in response.data.splitlines()]
            self.assertEqual([event["stage"] for event in events[:-1]], ["read", "rules", "references", "report"])
            report = events[-1]["report"]
            self.assertEqual(report["review"]["external_link_checks"][0]["status"], "public")
            self.assertIn("Доступ подтверждён", report["markdown"])
            check.assert_called_once_with("BCC-HUB", "ai-requirements-validator-task")
