import json
import os
import unittest
from unittest.mock import patch

from app import app


def provider_result(wording, **fields):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": json.dumps({"wording": wording, **fields})}
    ]}}]}


class CorrectionProposalTests(unittest.TestCase):
    path = "/api/correction/propose"

    def setUp(self):
        self.client = app.test_client()
        self.body = {
            "text": "# Internal audit\n§2.4 The transfer limit is TBD.\nUnrelated customer note.",
            "locale": "en", "code": "open_decision", "line": 2,
            "quote": "The transfer limit is TBD.",
            "question": "Which limit applies to one transfer?", "answer": "50 000 KZT per transfer",
        }

    @patch("gemini.is_configured", return_value=True)
    @patch("gemini.generate")
    def test_confirmed_numbers_and_minimal_provider_context(self, generate, _configured):
        wording = "The limit per transfer is 50 000 KZT."
        generate.return_value = provider_result(wording)
        response = self.client.post(self.path, json=self.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"wording": wording})
        inputs = json.loads(generate.call_args.args[1]["contents"][0]["parts"][0]["text"])
        self.assertEqual(inputs, {key: self.body[key] for key in ("quote", "code", "question", "answer")})

    @patch.dict(os.environ, {"GEMINI_MODEL": "", "GEMINI_FALLBACK_MODEL": "gemini-3.6-flash"})
    @patch("gemini.is_configured", return_value=True)
    @patch("gemini.generate")
    def test_drafts_on_flash_lite_and_retries_temporary_failure(self, generate, _configured):
        wording = "The transfer limit is 50 000 KZT."
        generate.side_effect = [ValueError("gemini_timeout"), provider_result(wording)]
        response = self.client.post(self.path, json=self.body)
        self.assertEqual(response.json, {"wording": wording})
        self.assertEqual([call.args[0] for call in generate.call_args_list],
                         ["gemini-3.5-flash-lite", "gemini-3.6-flash"])

    @patch("gemini.generate")
    def test_bad_evidence_and_invalid_inputs_do_not_call_provider(self, generate):
        for update in [{"line": 3}, {"quote": "Unrelated quote."}, {"code": []}, {"line": True}, {"answer": ""}, {"locale": "other"}, {"target": "different cell"}]:
            with self.subTest(update=update):
                self.assertEqual(self.client.post(self.path, json={**self.body, **update}).status_code, 400)
        self.assertEqual(self.client.post(self.path, json={**self.body, "answer": "x" * 2001}).status_code, 413)
        generate.assert_not_called()

    @patch("gemini.is_configured", return_value=True)
    @patch("gemini.generate")
    def test_unconfirmed_quantities_rejected_and_missing_detail_signaled(self, generate, _configured):
        for wording in ["The transfer limit is 70 000 KZT.", "The transfer limit is 50 KZT."]:
            generate.return_value = provider_result(wording)
            response = self.client.post(self.path, json=self.body)
            self.assertEqual(response.json["error"], "gemini_invalid_response")
        generate.return_value = provider_result("")
        self.assertEqual(self.client.post(self.path, json=self.body).json["error"], "clarification_needed")
        generate.side_effect = ValueError("gemini_quota")
        self.assertEqual(self.client.post(self.path, json=self.body).status_code, 429)

    @patch("gemini.is_configured", return_value=False)
    def test_unconfigured_is_reported(self, _configured):
        response = self.client.post(self.path, json=self.body)
        self.assertEqual((response.status_code, response.json["error"]), (503, "gemini_unconfigured"))

    @patch("gemini.is_configured", return_value=True)
    @patch("gemini.generate")
    def test_incomplete_answer_returns_only_a_supported_compact_follow_up(self, generate, _configured):
        question = "Какая сумма разрешена для одного перевода?"
        for candidate in (question, question + "\n", question * 7, 123, "Разрешена сумма 600 000 KZT?", "Кто? Когда?"):
            with self.subTest(candidate=candidate):
                generate.return_value = provider_result("", question=candidate)
                response = self.client.post(self.path, json={**self.body, "locale": "ru", "answer": "Да"})
                self.assertEqual(response.status_code, 422)
                expected = {"error": "clarification_needed"}
                if candidate == question:
                    expected["question"] = question
                self.assertEqual(response.json, expected)

    @patch.dict(os.environ, {"VERCEL": "1"})
    @patch("gemini.is_configured", return_value=True)
    @patch("gemini.generate")
    def test_vercel_reuses_existing_provider_route_and_preserves_payload(self, generate, _configured):
        wording = "The limit is 50 000 KZT."
        generate.return_value = provider_result(wording)
        response = self.client.post(self.path, json={**self.body, "target": "The transfer limit is TBD."}, follow_redirects=True)
        self.assertEqual(response.history[0].status_code, 307)
        self.assertEqual(response.request.path, "/api/analyze/gemini")
        self.assertEqual(response.json, {"wording": wording})
