import io
import json
import os
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import app
from hackathon_cli import render_review, review_file, write_review_files
from organizer_input import SOURCE_URL, official_input_bytes


class JuryRunTests(unittest.TestCase):
    def test_review_and_sidecars_share_one_audit(self):
        source = Path(__file__).parent / "fixtures" / "quality-broken.md"
        with TemporaryDirectory() as tmp:
            report = Path(tmp) / "review.md"
            audit = review_file(source, report, rules_only=True, json_path=report.with_suffix(".json"),
                                answers_path=report.with_suffix(".answers.md"))
            saved = json.loads(report.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(saved, audit)
            self.assertEqual(report.read_text(encoding="utf-8"), render_review(saved))
            self.assertIn("пропущена в режиме локальных правил", render_review(saved))
            mixed = [{**item, "assessment_status": "reviewed" if idx else "unchecked"}
                     for idx, item in enumerate(saved["requirements"])]
            mixed_report = render_review({**saved, "mode": "gemini", "requirements": mixed})
            self.assertIn(f"оценкой ИИ — {len(mixed) - 1} из {len(mixed)}", mixed_report)
            self.assertIn("Требуют индивидуальной сверки — " + mixed[0]["id"], mixed_report)
            questions = report.with_suffix(".answers.md").read_text(encoding="utf-8")
            self.assertTrue(saved["findings"])
            for item in saved["findings"]:
                self.assertIn(item["id"], questions)

    def test_sidecar_cannot_overwrite_source_even_via_a_hard_link(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "file.md"
            source.write_text("Original")
            target = Path(tmp) / "review.md"
            target.with_suffix(".json").hardlink_to(source)
            with self.assertRaisesRegex(ValueError, "same_json_file"):
                review_file(source, target, rules_only=True, json_path=target.with_suffix(".json"))
            self.assertFalse(target.exists())
            self.assertEqual(source.read_text(), "Original")

    def test_failed_publication_restores_previous_results(self):
        with TemporaryDirectory() as tmp:
            files = [Path(tmp) / name for name in ("file.json", "file.answers.md", "file.md")]
            files[0].write_bytes(b"previous report")
            replace = os.replace

            def replace_except_last(staged, target):
                if target == files[-1]:
                    raise PermissionError("report is locked")
                replace(staged, target)

            with patch("hackathon_cli.os.replace", side_effect=replace_except_last), self.assertRaises(PermissionError):
                write_review_files(dict.fromkeys(files, "next run"))
            self.assertEqual(files[0].read_bytes(), b"previous report")
            self.assertFalse(files[1].exists())
            self.assertFalse(files[2].exists())

    def test_official_route_discards_unexpected_bytes_then_serves_verified_file(self):
        official_input_bytes.cache_clear()
        self.addCleanup(official_input_bytes.cache_clear)
        content = b"# Test requirements\n"
        with patch("organizer_input.OFFICIAL_SHA256", sha256(content).hexdigest()), \
                patch("organizer_input.urlopen", side_effect=[io.BytesIO(b"wrong"), io.BytesIO(content)]) as get:
            client = app.test_client()
            self.assertEqual(client.get("/api/official-input").status_code, 503)
            for _ in range(2):
                response = client.get("/api/official-input")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, content)
                self.assertEqual(response.mimetype, "text/markdown")
            self.assertEqual(get.call_count, 2)
            get.assert_called_with(SOURCE_URL, timeout=6)
