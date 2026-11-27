import unittest

from app import app
from examples import AUDIT_DEMO


class PartialPdfProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_edited_pdf_review_keeps_origin_without_reusing_page_anchors(self):
        origin = {"total": 3, "unread": [3, 2]}
        response = self.client.post("/api/analyze?operation=report", json={
            "text": AUDIT_DEMO, "filename": "revised.md", "pdf_origin": origin,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        review = payload["review"]
        self.assertEqual(review["pdf_origin"], {"total": 3, "unread": [2, 3]})
        self.assertNotIn("pdf_coverage", review)
        self.assertIn("не прочитаны страницы 2, 3", payload["markdown"])
        self.assertIn("Ссылки относятся к текущему тексту.", payload["markdown"])
        for finding in review["findings"]:
            for citation in finding["evidence"]:
                self.assertEqual(citation["pages"], [])
                self.assertIn(citation["quote"], AUDIT_DEMO)

    def test_invalid_pdf_origin_is_rejected(self):
        for origin in ({"total": 1000, "unread": [1]}, {"total": 2, "unread": [True]},
                       {"total": 2, "unread": [3]}, {"total": 3, "unread": [2, 2]},
                       {"total": 3, "unread": [1, 2, 3]}, "pages"):
            with self.subTest(origin=origin):
                response = self.client.post("/api/analyze?operation=report", json={
                    "text": AUDIT_DEMO, "filename": "revised.md", "pdf_origin": origin,
                })
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {"error": "invalid_request"})
