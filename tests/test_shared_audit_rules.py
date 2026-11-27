from io import BytesIO
from pathlib import Path
import unittest

from docx import Document

from document_input import extract_document
from hackathon_cli import audit_document, build_audit, overlaps_rule
from hackathon_review import SetIssue, SetReview, source_blocks


class SharedAuditRulesTests(unittest.TestCase):
    def audit(self, text):
        return audit_document(Path("transfers.md"), text.encode(), rules_only=True)

    def test_transfer_defects_appear_in_full_audit_with_source_citations(self):
        lines = [
            "# Transfers", "",
            "REQ-1. Maximum amount per transfer is 100 000 KZT.", "",
            "REQ-2. The limit per transfer is 50 000 KZT.", "",
            "REQ-3. If there is no response, the app must retry the transfer request.", "",
            "REQ-4. The receipt retention period is TBD.",
        ]
        report = self.audit("\n".join(lines))
        self.assertEqual(report["readiness"], "blocked")
        self.assertEqual([item["criterion"] for item in report["findings"]],
                         ["Непротиворечивость", "Полнота", "Полнота"])
        for issue, expected in zip(report["findings"], ([3, 5], [7], [9])):
            self.assertEqual(issue["engine"], "Правило SanA1")
            self.assertEqual([source["line"] for source in issue["evidence"]], expected)
            self.assertEqual([source["quote"] for source in issue["evidence"]],
                             [lines[number - 1] for number in expected])
            self.assertTrue(issue["requirements"])

    def test_explicit_scopes_resolved_retry_and_fenced_example_are_clean(self):
        report = self.audit(
            "# Transfers\n\n"
            "REQ-1. The limit per transfer is 50 000 KZT.\n\n"
            "REQ-2. The daily transfer limit is 100 000 KZT.\n\n"
            "REQ-3. If there is no response, the app must retry the transfer request "
            "with the same idempotency key and must not debit twice.\n\n"
            "REQ-4. The receipt retention period is 30 days.\n\n"
            "```text\nThe limit per transfer is 120 000 KZT.\nReceipt retention: TBD\n```"
        )
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["readiness"], "limited")

    def test_conflicting_lines_can_share_one_markdown_paragraph(self):
        text = "The limit per transfer is 50 000 KZT.\nThe limit per transfer is 100 000 KZT."
        [issue] = self.audit(text)["findings"]
        [source] = issue["evidence"]
        self.assertEqual((source["line"], source["end"], source["quote"]), (1, 2, text))

    def test_docx_edit_preserves_unrelated_findings_and_citation_identity(self):
        document = Document()
        document.add_heading("Transfer ledger", level=0)
        document.add_heading("Limits", level=1)
        table = document.add_table(rows=2, cols=3)
        for row, values in zip(table.rows, [("Clause", "Requirement", "Amount"),
                                           ("REQ-1", "Maximum amount per transfer", "100 000 KZT")]):
            for cell, value in zip(row.cells, values):
                cell.text = value
        document.add_paragraph("REQ-2. The limit per transfer is 50 000 KZT.")
        document.add_heading("Retention", level=1)
        document.add_paragraph("REQ-3. The receipt retention period is TBD.")
        stream = BytesIO()
        document.save(stream)
        data = stream.getvalue()
        before = audit_document(Path("ledger.docx"), data, rules_only=True)
        editor = extract_document("docx", data)["text"]
        after = self.audit(editor.replace("50 000", "100 000"))

        self.assertEqual(len(before["findings"]), 2)
        self.assertEqual(len(after["findings"]), 1)
        self.assertEqual([r["source_id"] for r in before["requirements"]],
                         [r["source_id"] for r in after["requirements"]])
        previous, current = before["findings"][1]["evidence"][0], after["findings"][0]["evidence"][0]
        self.assertEqual([(previous[k], current[k]) for k in ("section", "quote", "source_id")],
                         [("Transfer ledger / Retention",) * 2,
                          ("REQ-3. The receipt retention period is TBD.",) * 2, ("REQ-3",) * 2])

    def test_set_check_cannot_be_ok_when_linked_finding_says_otherwise(self):
        title, blocks = source_blocks("# Ledger\n\nСервис отправляет отчёт.", True)
        source = blocks[-1]
        check = {"outcome": "ok", "comment": "Проверен раздел отправки.", "refs": [source.ref]}
        issue = SetIssue(criterion="completeness", severity="major", refs=[source.ref],
                         explanation="Нет срока отправки.", question="Когда отправлять отчёт?",
                         next_step="Указать срок отправки.")
        review = SetReview(consistency=check, completeness=check, traceability=check, feasibility=check, issues=[issue])
        result = (title, {block.ref: block for block in blocks}, [], review, [], [], 0, 0)
        audit = build_audit(result, Path("ledger.md"), "md", "hash", [], [])
        self.assertEqual(audit["checks"][1]["outcome"], "issue")
        self.assertEqual(audit["checks"][1]["evidence"][0]["quote"], source.text)

    def test_repeated_get_write_finding_is_merged_across_criteria(self):
        rule = SetIssue(criterion="design", severity="major", refs=["L104", "L120"],
                        explanation="Контракт назначает GET операции, которая изменяет настройки.",
                        question="Какой метод изменяет настройки?", next_step="Разделить чтение и запись.")
        duplicate = rule.model_copy(update={"criterion": "feasibility", "refs": ["L120", "L104"],
                                            "question": "Какой HTTP-метод используется для изменения настроек?"})
        different = duplicate.model_copy(update={"explanation": "Не указан результат записи при сбое."})
        self.assertTrue(overlaps_rule(duplicate, rule))
        self.assertFalse(overlaps_rule(different, rule))

    def test_shared_citations_keep_independent_business_decisions(self):
        cases = (
            ("Общее правило относит расход к дате покупки, а пример — к дате проведения.",
             "В какой месяц входит покупка, совершённая в одном месяце и проведённая в следующем?",
             "Какая именно дата (совершения или проведения) должна использоваться для отнесения "
             "транзакции к месяцу расходов при их пересечении на стыке месяцев?",
             "Какой часовой пояс используется для даты проведения транзакции на границе месяцев?"),
            ("Для перевода указаны два разных лимита.", "Какой лимит действует при этих условиях?",
             "Какое значение лимита действует для перевода?", "Как округлять сумму лимита?"),
            ("После изменения порога возможна повторная отправка push.",
             "Допустимо ли второе уведомление после изменения порога?",
             "Будет ли повторный push после изменения лимита?", "Как распознать повтор события процессинга?"),
            ("HTTP 200 с ERROR противоречит ошибке 400 для неверного ввода.",
             "Какой HTTP-статус получает клиент при неверном вводе?",
             "Какой код ответа использовать при ошибке валидации?", "Какой локализованный message возвращает HTTP 200 с ERROR?"),
        )
        for explanation, canonical, paraphrase, other in cases:
            with self.subTest(question=canonical):
                rule = SetIssue(criterion="consistency", severity="major", refs=["L4", "L7"],
                                explanation=explanation, question=canonical, next_step="Согласовать поведение.")
                duplicate = rule.model_copy(update={"explanation": "Повторная формулировка. " + explanation,
                                                    "question": paraphrase})
                distinct = duplicate.model_copy(update={"question": other})
                self.assertTrue(overlaps_rule(duplicate, rule))
                self.assertFalse(overlaps_rule(distinct, rule))

    def test_provider_paraphrases_merge_with_local_controls(self):
        recorded_paraphrases = (
            ("Общее правило относит расход к дате покупки, а пример — к дате проведения.",
             "В какой месяц входит покупка, совершённая в одном месяце и проведённая в следующем?",
             "Неопределён результат агрегации расходов по дате покупки и проведения.",
             "Какая именно дата — совершения покупки или её проведения — определяет месячный счётчик?"),
            ("Месячный лимит противоречит повторной отправке после изменения порога.",
             "Будет ли уведомление отправлено второй раз после изменения порога?",
             "Повторный push при смене порога противоречит ограничению количества за месяц.",
             "Сбрасывается ли лимит отправки одного push-уведомления за календарный месяц при изменении порога?"),
            ("Во время ошибки 400 документ показывает ERROR в примере HTTP 200.",
             "Какой HTTP-статус получает клиент при недопустимом значении?",
             "Таблица требует HTTP 400 при неверных параметрах, а примеры возвращают тело ошибки внутри HTTP 200.",
             "Какой именно HTTP-статус (200 или 400) должен возвращать сервис при некорректной сумме?"),
        )
        for explanation, question, generated_explanation, generated_question in recorded_paraphrases:
            with self.subTest(question=question):
                rule = SetIssue(criterion="consistency", severity="blocker", refs=["L4", "L7"],
                                explanation=explanation, question=question, next_step="Согласовать поведение.")
                model = rule.model_copy(update={"explanation": generated_explanation, "question": generated_question})
                self.assertTrue(overlaps_rule(model, rule))

    def test_period_and_validation_decisions_use_the_question_and_its_grounds(self):
        cases = (
            ("Общее правило относит расход к дате покупки, а пример — к дате проведения.",
             "В какой месяц входит покупка, совершённая в одном месяце и проведённая в следующем?",
             "По какой дате (совершения или проведения) должен определяться месяц учёта расходов?",
             ["В каком часовом поясе определяется дата проведения на границе месяца?",
              "Какой формат даты нужно отображать клиенту для месяца покупки?"]),
            ("Отклонённый ввод описан как ошибка 400, но в примерах под HTTP 200 указан ERROR.",
             "Какой HTTP-статус и какое тело получает клиент при недопустимом значении суммы?",
             "Какой статус HTTP и формат ответа должен возвращаться при неверном значении суммы?",
             ["Какой статус HTTP возвращается при отсутствии авторизации?",
              "Какой статус HTTP получает клиент при обрыве связи?",
              "Какой формат тела предусмотрен для HTTP 200 и 400?",
              "Какая максимальная сумма допустима для запроса?", "Как округляется сумма?"]),
        )
        for explanation, canonical, paraphrase, separate in cases:
            rule = SetIssue(criterion="consistency", severity="blocker", refs=["L8", "L16"],
                            explanation=explanation, question=canonical, next_step="Согласовать поведение.")
            issue = rule.model_copy(update={"question": paraphrase})
            self.assertTrue(overlaps_rule(issue, rule))
            self.assertFalse(overlaps_rule(issue.model_copy(update={"refs": ["L75"]}), rule))
            for question in separate:
                with self.subTest(question=question):
                    self.assertFalse(overlaps_rule(issue.model_copy(update={"question": question}), rule))
