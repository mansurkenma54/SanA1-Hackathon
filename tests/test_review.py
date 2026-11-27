import io
import json
import os
import unittest
from unittest.mock import patch

from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from analyzer import sections_from, verify_findings
from app import app
from examples import EXAMPLES, evaluate
from gemini import accept_findings, enhance


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_public_views_open_by_address(self):
        for path in ("/", "/workspace"):
            with self.subTest(path=path), self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'data-route id="nav-review"', response.data)
                self.assertNotIn(b'id="nav-evaluation"', response.data)
        self.assertEqual(self.client.get("/evaluation").location, "/workspace")

    def test_document_workspace_loads_its_editor_assets(self):
        for route, mimetype in (("/workspace.css", "text/css"), ("/audit-repair.js", "text/javascript"),
                                ("/hero-field.js", "text/javascript")):
            with self.subTest(route=route), self.client.get(route) as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, mimetype)

    def test_stream_yields_real_review_phases_and_the_same_report(self):
        body = {"text": EXAMPLES["en"], "mode": "local"}
        normal = self.client.post("/api/analyze", json=body).get_json()
        streamed = self.client.post("/api/analyze", json=body, headers={"Accept": "application/x-ndjson"})
        self.assertEqual(streamed.mimetype, "application/x-ndjson")
        events = [json.loads(line) for line in streamed.get_data(as_text=True).splitlines()]
        self.assertEqual([event["step"] for event in events[:-1]],
                         ["segment", "references", "wording", "compare", "scenarios", "report", "verify"])
        compared = next(e for e in events[:-1] if e["step"] == "compare")
        self.assertEqual(compared["count"], normal["statistics"]["sections"])
        excerpts = next(e for e in events[:-1] if e["step"] == "report")["evidence"]
        self.assertEqual(len(excerpts), 4)
        self.assertEqual(len({ref["line"] for ref in excerpts}), len(excerpts))
        for ref in excerpts:
            self.assertIn(ref["quote"], body["text"].splitlines()[ref["line"] - 1])
        self.assertEqual(events[-1], {"type": "result", "report": normal})

    def test_stream_reports_validation_failures_without_a_result(self):
        response = self.client.post("/api/analyze", json={"text": "short"},
                                    headers={"Accept": "application/x-ndjson"})
        events = [json.loads(line) for line in response.get_data(as_text=True).splitlines()]
        self.assertEqual(events[-1], {"type": "error", "error": "text_too_short"})
        self.assertNotIn("result", [event["type"] for event in events])

    def test_limit_edits_cover_all_clauses_and_exact_amount_offsets(self):
        text = ("§1 💳 The maximum amount per transfer is 100 000 KZT.\n"
                "§2 The maximum amount per transfer is 100,000.00 KZT.\n"
                "§3 The limit per transfer is 50 000 KZT.\n"
                "§4 The daily transfer limit is 250 000 KZT.")
        finding = self.analyze(text).json["findings"][0]
        edits = finding["values"]["limit_edits"]
        self.assertEqual([(edit["line"], edit["amount"]) for edit in edits],
                         [(1, "100000"), (2, "100000"), (3, "50000")])
        for edit in edits:
            self.assertEqual(edit["quote"][edit["start"]:edit["end"]], edit["text"])

    def analyze(self, content, mode="local"):
        return self.client.post("/api/analyze", json={"text": content, "mode": mode})

    def upload(self, content, kind):
        return self.client.post("/api/extract", data=content, content_type="application/octet-stream",
                                headers={"X-File-Type": kind})

    def test_labeled_evaluation(self):
        result = evaluate()
        failures = [case for case in result["cases"] if not case["passed"]]
        self.assertEqual(failures, [])

    def test_custom_case_grades_rule_and_lines_independently_of_count(self):
        text = "A customer can open the receipt.\n\nThe app must display the status quickly."
        correct = {"code": "vague_requirement", "lines": [3]}
        wrong = {"code": "vague_requirement", "lines": [1]}
        for expected, passed in (([correct], True), ([wrong], False), ([], False)):
            row = self.client.post("/api/evaluate/case", json={"text": text, "expected_findings": expected}).json
            self.assertEqual(row["passed"], passed)
            self.assertEqual(row["detected_findings"], [correct])
            self.assertEqual(row["unexpected_findings"], [] if passed else [correct])
            self.assertEqual(row["missed_findings"], [wrong] if expected == [wrong] else [])
        for invalid in ([{"code": "fake", "lines": [1]}], [correct, correct],
                        [{"code": "retry_behavior", "lines": [True]}], [{"code": "limit_conflict", "lines": [4]}]):
            response = self.client.post("/api/evaluate/case", json={"text": text, "expected_findings": invalid})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json["error"], "invalid_expectation")

    def test_evaluation_catalog_and_local_author_guidance(self):
        guidance = self.client.get("/api/guidance")
        self.assertEqual(guidance.mimetype, "application/json")
        self.assertEqual(set(guidance.json), {"ru", "en"})
        catalog = self.client.get("/api/evaluate/fixtures").json["cases"]
        self.assertEqual(len(catalog), len(evaluate()["cases"]))
        for fixture in catalog:
            result = self.client.post("/api/evaluate/case", json=fixture).json
            self.assertTrue(result["passed"], fixture["id"])
        report = self.client.post("/api/analyze", json={"text": EXAMPLES["ru"], "locale": "ru"}).json
        self.assertEqual(report["locale"], "ru")
        for item in report["findings"]:
            self.assertTrue(item["guidance"]["question"].endswith("?"))
            self.assertTrue(item["guidance"]["recommendation"])
            self.assertTrue(item["guidance"]["acceptance_test"])

    def test_evaluation_stream_matches_the_json_report(self):
        response = self.client.get("/api/evaluate", headers={"Accept": "application/x-ndjson"})
        self.assertEqual(response.mimetype, "application/x-ndjson")
        events = [json.loads(line) for line in response.get_data(as_text=True).splitlines()]
        self.assertEqual(events[-1]["report"], self.client.get("/api/evaluate").json)
        self.assertEqual([event for event in events if event["type"] == "stage"], [
            {"type": "stage", "step": "eval_cases", "count": len(events[-1]["report"]["cases"])},
            {"type": "stage", "step": "eval_metrics"},
        ])
        self.assertEqual([event["completed"] for event in events if event["type"] == "progress"],
                         list(range(1, len(events[-1]["report"]["cases"]) + 1)))

    def test_review_evidence_offsets_and_blank_input(self):
        content = "💳 Requirements\n" + EXAMPLES["en"]
        response = self.analyze(content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["engine"], "local")
        self.assertEqual(len(response.json["findings"]), 3)
        for item in response.json["findings"]:
            for ref in item["evidence"]:
                self.assertEqual(content[ref["start"]:ref["end"]], ref["quote"])
        self.assertEqual(self.analyze("").json["error"], "text_too_short")
        self.assertEqual(self.analyze("a" * 50_001).status_code, 413)

    def test_uploaded_docx_preserves_paragraphs_and_table_rows(self):
        document = Document()
        document.add_paragraph(EXAMPLES["ru"].splitlines()[0])
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Лимит"
        table.cell(0, 1).text = "50 000 ₸"
        stream = io.BytesIO()
        document.save(stream)
        result = self.upload(stream.getvalue(), "docx")
        self.assertEqual(result.status_code, 200)
        self.assertIn("Лимит | 50 000 ₸", result.json["text"])

    def test_file_errors_are_explicit(self):
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        stream = io.BytesIO()
        writer.write(stream)
        self.assertEqual(self.upload(stream.getvalue(), "pdf").json["error"], "scanned_document")
        self.assertEqual(self.upload(b"not a pdf", "pdf").json["error"], "invalid_document")
        self.assertEqual(self.upload(b"\xff\x00", "txt").json["error"], "invalid_text_encoding")
        self.assertEqual(self.upload(b"a", "exe").json["error"], "unsupported_file")

    def test_docx_inline_picture_keeps_its_position_in_table(self):
        from PIL import Image
        image = io.BytesIO()
        Image.new("RGB", (4, 4), "white").save(image, format="PNG")
        image.seek(0)
        document = Document()
        cell = document.add_table(rows=1, cols=2).cell(0, 1)
        row = cell.paragraphs[0]
        row.add_run("Before picture")
        row.add_run().add_picture(image)
        row.add_run("After picture")
        stream = io.BytesIO()
        document.save(stream)
        parsed = self.upload(stream.getvalue(), "docx").get_json()
        self.assertIn("|  | Before picture ![](attachment:fig-1) After picture |", parsed["text"])
        self.assertEqual(len(parsed["media"]), 1)

    def test_word_export_preserves_editable_table_picture_and_author_answer(self):
        with self.client.get("/transfer-case-en.docx") as source:
            parsed = self.upload(source.data, "docx").get_json()
        text = parsed["text"].replace("100 000", "48 000") + "\n## Approval owner\nЛидия approves after integration testing."
        response = self.client.post("/api/export/docx", json={"text": text, "locale": "en", "media": parsed["media"]})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.mimetype.endswith("wordprocessingml.document"))
        exported = Document(io.BytesIO(response.data))
        self.assertTrue(any("48 000" in cell.text for table in exported.tables for row in table.rows for cell in row.cells))
        self.assertEqual(exported.paragraphs[-2].style.name, "Heading 2")
        self.assertEqual(exported.paragraphs[-1].text, "Лидия approves after integration testing.")
        self.assertEqual(len(exported.inline_shapes), 1)
        self.assertEqual(self.upload(response.data, "docx").status_code, 200)

    def test_word_export_rejects_unrecognized_media_and_empty_text(self):
        for value in ({"text": "   "}, {"text": "hello", "media": [{"id":"fig-1", "src":"https://example.org/image.jpg"}]},
                      {"text": "bad\x00xml"}, {"text": "a" * 50001}):
            with self.subTest(payload=str(value)[:80]):
                self.assertIn(self.client.post("/api/export/docx", json=value).status_code, (413, 422))

    def test_downloadable_cases_keep_their_table_and_diagram_on_upload(self):
        for locale in ("en", "ru"):
            with self.subTest(locale=locale):
                name = "transfer-case-" + locale + ".docx"
                with self.client.get("/" + name) as download:
                    self.assertEqual(download.status_code, 200)
                    parsed = self.upload(download.data, "docx").get_json()
                self.assertEqual(parsed["warnings"], ["unreviewed_figures"])
                self.assertIn("| §2.1 |", parsed["text"])
                self.assertIn("](attachment:fig-1)", parsed["text"])
                self.assertEqual(len(parsed["media"]), 1)
                self.assertTrue(parsed["media"][0]["src"].startswith("data:image/jpeg;base64,"))
                result = self.analyze(parsed["text"]).get_json()
                self.assertEqual(len(result["findings"]), 6)
                self.assertEqual(result["verification"], {"verified_quotes": 8, "excluded_findings": 0})

    def test_pdf_extracts_a_text_page_and_reports_skipped_page(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=200)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        layer = DecodedStreamObject()
        layer.set_data(b"BT /F1 12 Tf 20 80 Td (The transfer limit is 500 KZT.) Tj ET")
        page[NameObject("/Contents")] = layer
        writer.add_blank_page(width=300, height=200)
        stream = io.BytesIO()
        writer.write(stream)
        result = self.upload(stream.getvalue(), "pdf")
        self.assertEqual(result.status_code, 200)
        self.assertIn("The transfer limit is 500 KZT.", result.json["text"])
        self.assertEqual(result.json["warnings"], ["partial_pdf"])
        self.assertEqual([preview["page"] for preview in result.json["media"]], [1, 2])
        self.assertTrue(result.json["media"][0]["src"].startswith("data:image/jpeg;base64,"))

    def test_pdf_reader_views_scans_and_requests_later_pages(self):
        writer = PdfWriter()
        for _ in range(5):
            writer.add_blank_page(width=300, height=200)
        stream = io.BytesIO()
        writer.write(stream)
        data = stream.getvalue()
        headers = {"X-File-Type": "pdf"}
        reader = self.client.post("/api/extract?view=pdf", data=data, headers=headers,
                                  content_type="application/octet-stream")
        self.assertEqual(reader.status_code, 200)
        self.assertEqual(reader.json["text"], "")
        self.assertEqual(reader.json["warnings"], ["scanned_document"])
        self.assertEqual([image["page"] for image in reader.json["media"]], [1, 2, 3, 4])
        page = self.client.post("/api/extract?page=5", data=data, headers=headers,
                                content_type="application/octet-stream")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json["page"], 5)
        self.assertTrue(page.json["src"].startswith("data:image/jpeg;base64,"))
        invalid = self.client.post("/api/extract?page=6", data=data, headers=headers,
                                   content_type="application/octet-stream")
        self.assertEqual((invalid.status_code, invalid.json["error"]), (422, "invalid_page"))
        audit = self.client.post("/api/analyze?operation=report", data=data, headers={"X-File-Name": "scan.pdf"},
                                 content_type="application/octet-stream")
        self.assertEqual((audit.status_code, audit.json["error"]), (422, "scanned_document"))

    def test_gemini_unavailable_preserves_local_results(self):
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=False):
            response = self.analyze(EXAMPLES["en"], "gemini")
        self.assertEqual(response.json["engine"], "local")
        self.assertEqual(response.json["warnings"], ["gemini_unconfigured"])
        self.assertEqual(len(response.json["findings"]), 3)

    def test_hosted_gemini_uses_only_the_rate_limited_route(self):
        with patch.dict(os.environ, {"VERCEL": "1", "GEMINI_API_KEY": "test-key"}):
            with patch("app.enhance", return_value=([], False, "gemini-3.5-flash")) as provider:
                self.assertTrue(self.client.get("/api/config").json["gemini"])
                self.assertEqual(self.analyze(EXAMPLES["en"], "gemini").json["engine"], "local")
                provider.assert_not_called()
                remote = self.client.post("/api/analyze/gemini", json={"text": EXAMPLES["en"]})
                self.assertEqual(remote.json["engine"], "gemini")
                provider.assert_called_once()

    def test_model_stage_reports_completed_rule_counts(self):
        original = self.analyze(EXAMPLES["en"]).json
        with patch("app.gemini_available", return_value=True), patch("app.enhance", return_value=([], False, "gemini-3.5-flash")):
            response = self.client.post("/api/analyze/gemini", json={"text": EXAMPLES["en"]},
                                        headers={"Accept": "application/x-ndjson"})
            events = [json.loads(line) for line in response.get_data(as_text=True).splitlines()]
        self.assertEqual(events[-3], {"type": "stage", "step": "model", "sections": original["statistics"]["sections"],
                                      "findings": len(original["findings"])})
        self.assertEqual(events[-2], {"type": "stage", "step": "verify"})
        self.assertEqual(events[-1]["report"]["engine"], "gemini")

    def test_final_audit_discards_bad_quotes_and_duplicates(self):
        text = "💳\n" + EXAMPLES["en"]
        valid = self.analyze(text).json["findings"][0]
        ref = valid["evidence"][0]
        bad = {**valid, "id": "invalid", "evidence": [{**ref, "quote": "unrelated"}]}
        self.assertEqual(verify_findings(text, [bad, valid, valid]), [valid])

    def test_semantic_review_retries_busy_service_once_and_respects_quota(self):
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"findings":[]}'}]}}]}
        with patch("gemini.is_configured", return_value=True), patch("gemini.MODEL", "gemini-3.5-flash"):
            with patch("gemini.generate", side_effect=[ValueError("gemini_busy"), response]) as provider:
                self.assertEqual(enhance(EXAMPLES["en"], "en", []), ([], False, "gemini-3.5-flash-lite"))
                self.assertEqual(provider.call_count, 2)
            with patch("gemini.generate", side_effect=ValueError("gemini_quota")) as provider:
                with self.assertRaisesRegex(ValueError, "gemini_quota"):
                    enhance(EXAMPLES["en"], "en", [])
                provider.assert_called_once()

    def test_gemini_evidence_rejects_invented_quote(self):
        sections = sections_from(EXAMPLES["en"])
        payload = {"findings": [
            {"code": "missing_scenario", "explanation": "Missing status for a duplicate request.",
             "evidence": [{"id": "L5", "quote": "An invented source paragraph."}]},
            {"code": "missing_scenario", "explanation": "Missing status for a duplicate request.",
             "evidence": [{"id": "L5", "quote": "the app must retry the transfer request"}]},
        ]}
        accepted, discarded = accept_findings(payload, sections, [])
        self.assertTrue(discarded)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["origin"], "gemini")

    def test_cross_origin_and_secret_file_route(self):
        response = self.client.post("/api/analyze", json={"text": EXAMPLES["en"]},
                                    headers={"Origin": "https://another.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/.env").status_code, 404)

    def test_context_clarification_requires_more_than_a_heading(self):
        sections = sections_from("# Payment reversal\n§1.1 The operator retries a pending reversal.")
        heading = {"id": "L1", "quote": "Payment reversal"}
        requirement = {"id": "L2", "quote": "retries a pending reversal"}
        issue = {"code": "missing_scenario", "explanation": "The result after a retry is unclear."}
        accepted, discarded = accept_findings({"findings": [
            {**issue, "evidence": [heading]}, {**issue, "evidence": [heading, requirement]}
        ]}, sections, [])
        self.assertTrue(discarded)
        self.assertEqual([item["id"] for item in accepted], ["missing_scenario:L1-L2"])


if __name__ == "__main__":
    unittest.main()
