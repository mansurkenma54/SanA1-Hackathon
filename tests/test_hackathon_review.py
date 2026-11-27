import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docx import Document
from docx.oxml import OxmlElement
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app import app, main
from document_input import extract_document
from gemini import compatible_request
from hackathon_cli import audit_document, missing_production_address_keys, overlaps_rule, render_review, review_file, scope_production_address
from hackathon_review import IndividualReview, SetIssue, SetReview, individual_results, needs_assessment, review_requirements, set_results, source_blocks
from review_rules import answered_by_document, rule_findings
from tools.check_qr_case import DIAGRAM, assess


SPEC = """# Уведомления

## Основное правило
* **Ф-1.** Уведомление отправляется не позже 10 секунд.

## Критерий приёмки

| Условие | Результат |
| --- | --- |
| Превышение порога | Уведомление отправляется не позже 30 секунд. |
"""
RULES_SPEC = """# Расходы

## Правило
Ф-1. Месяц определяется по дате покупки.

## Критерии приёмки
| Состояние | Действие | Итог |
| --- | --- | --- |
| Покупка 30 апреля | Провести 1 мая | Майский счётчик растёт |
"""
REFUND_CLAUSES = (
    "**Ф-1.** Сервис зачисляет подтверждённый возврат карточной покупки на исходный счёт до 18:00 следующего рабочего дня "
    "по календарю Алматы (UTC+5) после получения события подтверждения возврата от процессинга. "
    "Это правило применяется и к замороженному счёту.",
    "**Ф-2.** Возврат идентифицируется идентификатором операции процессинга. "
    "Повторная доставка того же идентификатора не меняет баланс.",
    '**Ф-3.** При заморозке счёта сервис отклоняет исходящие переводы, возвращая HTTP 403 и JSON {"code":"ACCOUNT_FROZEN"}. '
    "Входящий возврат покупки не зачисляется до снятия заморозки.",
)
REFUND_ACCEPTANCE = (
    "**П-1.** При подтверждении возврата на замороженный счёт баланс не меняется до снятия заморозки.",
    "**П-2.** При повторной доставке того же события баланс остаётся прежним.",
    '**П-3.** При исходящем переводе с замороженного счёта сервис отвечает HTTP 403 с JSON {"code":"ACCOUNT_FROZEN"} '
    "и сохраняет баланс.",
)
REFUND_CREDIT_RESULT = (
    "баланс увеличивается на сумму возврата до 18:00 следующего рабочего дня по календарю Алматы (UTC+5) "
    "после получения события подтверждения возврата от процессинга."
)
ISSUE = {
    "criterion": "consistency",
    "severity": "blocker",
    "explanation": "В документе указано два различных срока.",
    "question": "Какой срок действует при превышении порога?",
    "next_step": "Согласовать единый срок со владельцем требований.",
}
MODEL = "gemini-3.8-flash"
CONFIG = {"GEMINI_API_KEY": "test-only", "GEMINI_MODEL": MODEL,
          "GEMINI_FALLBACK_MODEL": ""}
SET_CHECK = {"outcome": "ok", "comment": "В указанных пунктах описан сценарий.", "refs": ["L4"]}


def model_answer(data, model=MODEL):
    return {"modelVersion": model, "candidates": [
        {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(data)}]}}
    ]}


def individual(quote="Уведомление отправляется не позже 10 секунд."):
    return {"requirements": [
        {"ref": "L4", "quote": quote, "summary": "Срок уведомления",
         "assessment": "Момент начала отсчёта требует согласования.", "issues": []},
        {"ref": "L10", "quote": "Уведомление отправляется не позже 30 секунд.",
         "summary": "Критерий для превышения порога",
         "assessment": "В критерии есть измеримое ограничение.", "issues": []},
    ]}


def whole_set(refs=("L4", "L10")):
    return dict.fromkeys(("consistency", "completeness", "traceability", "feasibility"), SET_CHECK) | {
        "issues": [{**ISSUE, "refs": refs}]
    }


def create_pdf(*, leading_number_only=False):
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_ref = writer._add_object(font)
    text_layers = [b"1"] if leading_number_only else []
    text_layers.append(b"The service delivers an alert within 10 seconds.")
    for text in text_layers:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})})
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 12 Tf 48 700 Td (" + text + b") Tj ET")
        page[NameObject("/Contents")] = writer._add_object(content)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


class EvidenceTests(unittest.TestCase):
    def test_impossible_range_requires_comparable_bounds_in_one_clause(self):
        for text, expected in (
            ("Ф-1. Строка содержит не менее 10 символов и не более 5 символов.", True),
            ("Ф-1. The response must take at least 2.5 and at most 1 second.", True),
            ("Ф-1. Лимит не менее 10 000 тенге и не более 5 000 ₸.", True),
            ("Ф-1. Строка содержит не менее 5 и не более 10 символов.", False),
            ("Ф-1. Действие занимает не менее 10 мс и не более 5 секунд.", False),
            ("Ф-1. Пауза не менее 10 секунд. Таймаут не более 5 секунд.", False),
        ):
            with self.subTest(text=text):
                _, blocks = source_blocks(text, structured=True)
                matches = [issue for issue in rule_findings(blocks) if "Нижняя граница" in issue["explanation"]]
                self.assertEqual(bool(matches), expected)
                if matches:
                    self.assertEqual(matches[0]["refs"], ["L1"])

    def test_notification_counter_reset_is_the_same_question_as_a_second_push(self):
        rule = SetIssue(criterion="consistency", severity="blocker", refs=["L39", "L40"],
                        explanation="Пересекаются правила отправки.",
                        question="Будет ли уведомление отправлено второй раз после изменения порога?",
                        next_step="Согласовать правила.")
        model = rule.model_copy(update={
            "question": "Должен ли сброситься счётчик отправленных push-уведомлений при изменении порога?",
        })
        self.assertTrue(overlaps_rule(model, rule))
        self.assertFalse(overlaps_rule(model.model_copy(update={
            "question": "Какой код получает клиент, если отправка push после изменения порога не удалась?",
        }), rule))

    def test_same_missing_reference_is_reported_once_and_other_links_are_kept(self):
        rule = SetIssue(criterion="traceability", severity="major", refs=["L90"],
                        explanation="В документе нет пункта QR-09.",
                        question="На какие существующие пункты должна вести ссылка «QR-09»?",
                        next_step="Указать нужный пункт.")
        model = rule.model_copy(update={
            "question": "Что указать вместо несуществующего QR-09?",
        })
        self.assertTrue(overlaps_rule(model, rule))
        self.assertFalse(overlaps_rule(model.model_copy(update={
            "question": "Какие права требуются для открытия внешней ссылки?",
            "explanation": "Для внешней ссылки не описаны права доступа.",
        }), rule))

    def setUp(self):
        title, blocks = source_blocks(SPEC, structured=True)
        self.title = title
        self.blocks = {block.ref: block for block in blocks}

    def test_preserves_cyrillic_identifier_and_acceptance_table(self):
        self.assertEqual(self.title, "Уведомления")
        self.assertEqual(self.blocks["L4"].source_id, "Ф-1")
        self.assertEqual(self.blocks["L8"].kind, "table_header")
        self.assertEqual(self.blocks["L10"].kind, "table_row")
        self.assertNotIn("L9", self.blocks)

    def test_adjacent_requirement_ids_preserve_line_spans_and_continuations(self):
        text = (
            "# Возврат\n\n## Функциональные требования\n"
            "Правила расчёта применяются к карточным операциям.\n"
            "**Ф-1.** Сервис зачисляет возврат за один рабочий день.\n"
            "Это правило применяется и к замороженному счёту.\n"
            "_REF-2:_ Повторное событие не меняет баланс.\n"
            "Ф-3. Возврат не зачисляется до снятия заморозки.\n\n"
            "```text\nФ-4. Пример строки с ID.\nФ-5. Ещё один пример.\n```"
        )
        _, blocks = source_blocks(text, structured=True)
        paragraphs = [block for block in blocks if block.kind == "paragraph"]
        self.assertEqual(
            [(block.source_id, block.line, block.end) for block in paragraphs],
            [(None, 4, 4), ("Ф-1", 5, 6), ("REF-2", 7, 7), ("Ф-3", 8, 8)],
        )
        lines = text.splitlines()
        for block in paragraphs:
            self.assertEqual(block.text, "\n".join(lines[block.line - 1:block.end]))
            self.assertEqual(block.section, "Возврат / Функциональные требования")
        self.assertEqual([(b.line, b.end) for b in blocks if b.kind == "example"], [(10, 13)])

    def test_refund_hold_does_not_conflict_with_a_deadline_excluding_frozen_accounts(self):
        source = "\n".join(REFUND_CLAUSES).replace("применяется и к замороженному", "не применяется к замороженному")
        _, blocks = source_blocks(source, structured=True)
        self.assertEqual(rule_findings(blocks), [])

    def test_prompt_reuses_document_title_without_altering_citation_sections(self):
        block = self.blocks["L10"]
        self.assertEqual(block.as_prompt_data(self.title)["section"], "Критерий приёмки")
        self.assertEqual(block.section, "Уведомления / Критерий приёмки")
        self.assertEqual(block.as_prompt_data("Другой документ")["section"], block.section)

    def test_missing_acceptance_result_cites_header_and_row(self):
        source = (
            "# Проверка\n\n## Критерии приёмки\n"
            "| Исходные условия | Действие | Ожидаемый результат |\n"
            "| --- | --- | --- |\n"
            "| Текущий лимит 100 ₸ | Сохранить лимит 200 ₸ | {} |"
        )
        _, blocks = source_blocks(source.format(""), structured=True)
        issues = rule_findings(blocks)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["criterion"], "verifiability")
        self.assertEqual(issues[0]["refs"], ["L4", "L6"])
        self.assertIn("ожидаемый результат", issues[0]["question"])
        _, complete = source_blocks(source.format(r"Ответ OK \| лимит 200 ₸"), structured=True)
        self.assertEqual(rule_findings(complete), [])

    def test_acceptance_check_does_not_cross_tables(self):
        _, blocks = source_blocks(
            "## Acceptance scenarios\n"
            "| Given | When | Then |\n| --- | --- | --- |\n| Configured | Request | Accepted |\n\n"
            "| ID | Note | Example |\n| --- | --- | --- |\n| 1 | Optional note | |",
            structured=True,
        )
        self.assertEqual(rule_findings(blocks), [])

    def test_vague_timing_cites_obligation_and_asks_only_for_missing_bound(self):
        _, blocks = source_blocks(
            "# Уведомления\n\nФ-1. Сервис должен быстро отправить push после подтверждения операции.",
            structured=True,
        )
        issues = rule_findings(blocks)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["criterion"], "verifiability")
        self.assertEqual(issues[0]["refs"], ["L3"])
        self.assertIn("после указанного события", issues[0]["question"])
        rule = SetIssue.model_validate(issues[0])
        model_issue = rule.model_copy(update={"criterion": "completeness",
                                              "question": "Какое максимальное время отправки push?"})
        self.assertTrue(overlaps_rule(model_issue, rule))
        self.assertTrue(overlaps_rule(model_issue.model_copy(update={
            "question": "Каковы точные количественные требования к скорости отображения статуса?",
        }), rule))
        self.assertFalse(overlaps_rule(model_issue, rule, ["L7"]))
        self.assertFalse(overlaps_rule(model_issue.model_copy(update={
            "question": "Какой формат данных должен содержать push?",
        }), rule))

    def test_explicit_bound_or_unique_timing_reference_resolves_vagueness(self):
        requirement = "Ф-1. Сервис должен быстро отправить push."
        limit = "PERF-2. Push должен быть отправлен в течение 2 секунд после подтверждения."
        for text in (
            "The app must promptly show the receipt within a minute.",
            requirement + " Время ответа см. PERF-2.\n\n" + limit,
            "Система должна показывать текст «как можно скорее» в подсказке.",
        ):
            with self.subTest(text=text):
                _, blocks = source_blocks(text, structured=True)
                self.assertEqual(rule_findings(blocks), [])
        for body in (
            requirement + "\n\n" + limit,
            requirement + " Время ответа см. PERF-2.\n\n" + limit + "\n\n" + limit,
            requirement + " Квитанцию следует хранить в течение 3 минут.",
        ):
            with self.subTest(body=body):
                _, blocks = source_blocks(body, structured=True)
                self.assertEqual(len([item for item in rule_findings(blocks)
                                      if item["criterion"] == "verifiability"]), 1)

    def test_reference_check_distinguishes_unknown_ambiguous_and_external_targets(self):
        source = (
            "# Уведомления\n\n"
            "## Ф-1 Условия\n"
            "Ф-1. Система сохраняет состояние карты.\n\n"
            "## Основной поток\n"
            "Ф-2. Система передаёт push.\n\n"
            "## Альтернативный поток\n"
            "Ф-2. Система запрещает push.\n\n"
            "Ф-3. См. пункт **Ф–1**, Ф-2 и Ф-9. Для внешнего интерфейса см. Ф-5 дочерней спецификации."
        )
        _, blocks = source_blocks(source, structured=True)
        issues = rule_findings(blocks)
        self.assertEqual(len(issues), 2)
        self.assertTrue(all(item["criterion"] == "traceability" for item in issues))
        self.assertIn("Ф-9", issues[0]["explanation"])
        self.assertNotIn("Ф-5", issues[0]["explanation"])
        self.assertEqual(issues[0]["refs"], ["L12"])
        self.assertEqual(issues[1]["refs"], ["L7", "L10", "L12"])

    def test_reference_check_resolves_ids_in_requirement_table(self):
        _, blocks = source_blocks(
            "# Example\n\n| ID | Requirement |\n| --- | --- |\n"
            "| REQ-2.1 | Retain a copy of the original receipt. |\n\n"
            "See requirement REQ-2.1 for receipt retention.",
            structured=True,
        )
        self.assertEqual(rule_findings(blocks), [])

    def test_only_redundant_timing_wording_is_resolved_by_explicit_reference(self):
        source = (
            "Ф-1. Экран должен оперативно показывать квитанцию. Время ответа см. PERF-2.\n\n"
            "PERF-2. Экран должен показывать квитанцию в течение 2 секунд после подтверждения перевода."
        )
        _, blocks = source_blocks(source, structured=True)
        question = "Следует ли удалить слово 'оперативно', учитывая наличие ссылки на точный норматив в PERF-2?"
        self.assertEqual(answered_by_document(question, blocks, sources=blocks[:1]).ref, "L3")
        self.assertIsNone(answered_by_document(question, blocks, sources=blocks[1:]))
        self.assertIsNone(answered_by_document(
            "В какой момент начинается отсчёт?", blocks, sources=blocks[:1]))

    def test_unnumbered_ui_data_integration_and_api_requirements_are_required(self):
        _, blocks = source_blocks(
            "# Спецификация\n\n"
            "## Дизайн процесса UI\nПри ошибке сообщение появляется под полем.\n\n"
            "## Нефункциональные требования\nУведомление отправляется в течение минуты.\n\n"
            "## Требования к данным\nХранить идентификатор операции.\n\n"
            "## Требования к интеграции\nПовторная доставка сохраняет исходный итог.\n\n"
            "## Общие параметры\n| Поле | Значение |\n| --- | --- |\n"
            "| **REST type** | GET |\n| **Authorization** | Bearer |\n| **Author** | Аналитик |\n",
            structured=True,
        )
        required = [block.text for block in blocks if needs_assessment(block)]
        self.assertEqual(required, [
            "При ошибке сообщение появляется под полем.",
            "Уведомление отправляется в течение минуты.",
            "Хранить идентификатор операции.",
            "Повторная доставка сохраняет исходный итог.",
            "| **REST type** | GET |",
            "| **Authorization** | Bearer |",
        ])

    def test_paraphrase_is_replaced_with_original_source(self):
        rows, excluded, replaced = individual_results(
            IndividualReview.model_validate(individual("цитаты нет в тексте")), self.blocks)
        self.assertEqual(rows[0][1].quote, self.blocks["L4"].text)
        self.assertEqual((excluded, replaced), (0, 1))

    def test_missing_numbered_requirement_rejects_incomplete_report(self):
        with self.assertRaisesRegex(ValueError, "gemini_incomplete_inventory"):
            individual_results(IndividualReview(requirements=[]), self.blocks)

    def test_unverifiable_conflict_is_excluded(self):
        no_evidence = SetReview.model_validate(whole_set(("L4", "L999")))
        result, excluded = set_results(no_evidence, self.blocks)
        self.assertEqual(result.issues, [])
        self.assertEqual(excluded, 1)

    def test_conflict_needs_two_distinct_source_blocks(self):
        with_evidence = SetReview.model_validate(whole_set())
        result, excluded = set_results(with_evidence, self.blocks)
        self.assertEqual(excluded, 0)
        self.assertEqual(result.issues[0].refs, ["L4", "L10"])

    def test_distinct_findings_can_share_the_same_two_citations(self):
        payload = whole_set()
        second = {**ISSUE, "refs": ["L10", "L4"],
                  "explanation": "В пунктах указаны разные события запуска отсчёта.",
                  "question": "Какое событие запускает отсчёт?"}
        payload["issues"].extend([second, dict(second)])
        result, excluded = set_results(SetReview.model_validate(payload), self.blocks)
        self.assertEqual(excluded, 0)
        self.assertEqual(len(result.issues), 2)

    def test_same_calendar_rule_on_a_different_spec_and_clean_counterexample(self):
        template = (
            "## Правило\nМесяц определяется по дате покупки.\n\n"
            "## Приёмка\n| Состояние | Действие | Итог |\n| --- | --- | --- |\n"
            "| Покупка 30 апреля | Провести 1 мая | {} счётчик растёт |"
        )
        _, incorrect = source_blocks(template.format("Майский"), structured=True)
        _, correct = source_blocks(template.format("Апрельский"), structured=True)
        findings = rule_findings(incorrect)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["refs"], ["L2", "L7"])
        self.assertEqual(rule_findings(correct), [])

    def test_http_200_error_example_does_not_invent_a_contradiction_in_correct_doc(self):
        template = (
            "200 — успешный ответ.\n\n400 — параметры запроса заполнены неверно.\n\n"
            "### {}\n\n```json\n{{\"result\":\"ERROR\", \"message\":\"Проверьте сумму\"}}\n```\n"
        )
        _, incorrect = source_blocks(template.format("200"), structured=True)
        _, correct = source_blocks(template.format("400"), structured=True)
        self.assertTrue(rule_findings(incorrect))
        self.assertEqual(rule_findings(correct), [])

    def test_http_evidence_is_never_borrowed_from_a_sibling_endpoint(self):
        template = (
            "# Контракты API\n## Чтение\n### Статусы\n"
            "200 — успешный ответ.\n\n{}\n\n"
            "## Сохранение\n### Статусы\n200 — успешный ответ.\n\n{}\n\n"
            "#### 200\n```json\n{{\"result\":\"ERROR\"}}\n```"
        )
        rejection = "400 — параметры запроса заполнены неверно."
        _, different = source_blocks(template.format(rejection, ""), structured=True)
        _, conflicting = source_blocks(template.format(rejection, rejection), structured=True)
        self.assertEqual(rule_findings(different), [])
        self.assertEqual(len(rule_findings(conflicting)), 1)
        lookup = {block.ref: block for block in conflicting}
        for ref in rule_findings(conflicting)[0]["refs"]:
            self.assertIn("Сохранение", lookup[ref].section)

    def test_access_codes_in_separate_contracts_do_not_conflict(self):
        template = (
            "# Контракты API\n## История\n### Статусы\n403 — доступ запрещён.\n"
            "\n## Настройки\n### Статусы\n{}\n\n#### 403\nДля чужой карты возвращается 404."
        )
        _, different = source_blocks(template.format(""), structured=True)
        _, same = source_blocks(template.format("403 — доступ запрещён."), structured=True)
        self.assertEqual(rule_findings(different), [])
        self.assertEqual(len(rule_findings(same)), 1)

    def test_second_get_is_checked_when_the_first_is_read_only(self):
        document = (
            "# Контракты API\n## Чтение\n### Метод\nHTTP method: GET\n"
            "### Выполнение\nПрочитать настройки карты.\n"
            "## Изменение\n### Метод\nHTTP method: GET\n"
            "### Выполнение\nЗаменить настройки карты."
        )
        _, blocks = source_blocks(document, structured=True)
        issues = rule_findings(blocks)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["refs"], ["L9", "L11"])

    def test_answer_from_another_endpoint_does_not_hide_a_miss(self):
        document = (
            "# Контракты API\n## Чтение\n### Ответ\n| Параметр | Тип |\n"
            "| --- | --- |\n| amount | string |\n"
            "## Изменение\n### Ответ\n| Параметр | Тип |\n| --- | --- |\n| amount | — |"
        )
        _, blocks = source_blocks(document, structured=True)
        lookup = {block.ref: block for block in blocks}
        payload = whole_set()
        payload["issues"] = [{**ISSUE, "criterion": "clarity", "refs": ["L11"],
                              "question": "Должно ли поле amount в ответе возвращаться в виде строки или числового типа?"}]
        result, excluded = set_results(SetReview.model_validate(payload), lookup)
        self.assertEqual(excluded, 0)
        self.assertEqual(result.issues[0].refs, ["L11"])

    def test_same_read_contract_question_is_not_counted_twice(self):
        rule = SetIssue(**{**ISSUE, "criterion": "completeness", "refs": ["L3", "L4", "L7"],
                           "question": "Каким методом клиент читает настройки?"})
        duplicate = SetIssue(**{**ISSUE, "refs": ["L3", "L4"],
                                "question": "Какие параметры нужны для чтения настроек?"})
        other = SetIssue(**{**ISSUE, "refs": ["L3", "L4"],
                            "question": "Сколько запросов на сохранение допустимо?"})
        self.assertTrue(overlaps_rule(duplicate, rule))
        self.assertFalse(overlaps_rule(other, rule))

    def test_shared_access_status_evidence_deduplicates_the_model(self):
        rule = SetIssue(**{**ISSUE, "criterion": "clarity", "refs": ["L3", "L4"],
                           "explanation": "В одном разделе указаны 403 и 404."})
        duplicate = SetIssue(**{**ISSUE, "refs": ["L3", "L4"],
                                "explanation": "Для одного отказа встречаются 404 и 403."})
        self.assertTrue(overlaps_rule(duplicate, rule))

    def test_cited_card_exception_resolves_status_choice_without_hiding_an_explicit_conflict(self):
        template = "# Контракт\n## Статусы\n403 — доступ запрещён{}.\n\n### 403\n" \
                   "Для чужой карты возвращается 404, как и для отсутствующей карты."
        for condition, redundant in (("", True), (" для чужой карты", False)):
            _, sequence = source_blocks(template.format(condition), structured=True)
            blocks = {block.ref: block for block in sequence}
            rule = SetIssue.model_validate(rule_findings(sequence)[0])
            issue = rule.model_copy(update={
                "criterion": "consistency",
                "question": "Какой именно статус (403 или 404) должен возвращаться клиенту при запросе чужой или несуществующей карты?",
                "explanation": "Конфликт между общим списком статус-кодов и специальным правилом для чужой карты.",
            })
            self.assertEqual(overlaps_rule(issue, rule, blocks=blocks), redundant)
            self.assertFalse(overlaps_rule(issue.model_copy(update={
                "question": "Какой статус (403 или 404) возвращается, если срок действия карты истёк?"
            }), rule, blocks=blocks))

    def test_notification_flag_question_matches_its_repeat_rule(self):
        rule = SetIssue(**{**ISSUE, "refs": ["L39", "L40"],
                           "question": "Если уведомление уже отправлено, будет ли оно отправлено второй раз после изменения порога?"})
        issue = rule.model_copy(update={
            "question": "Сбрасывается ли флаг отправленного пуша при изменении порога, если текущие расходы уже превышают новое значение?"
        })
        self.assertTrue(overlaps_rule(issue, rule))
        self.assertFalse(overlaps_rule(issue.model_copy(update={
            "question": "Будет ли пуш отправлен сразу после снижения порога, если его никогда не достигали?"
        }), rule))

    def test_individual_http_error_citation_merges_with_conflict_in_same_contract(self):
        document = (
            "# Контракт\n## Логика\nПри отклонении суммы вернуть результат ERROR.\n"
            "## Статусы\n200 — успешный ответ.\n\n400 — параметры запроса заполнены неверно.\n"
            "### 200\n```json\n{\"result\":\"ERROR\"}\n```"
        )
        _, blocks = source_blocks(document, structured=True)
        rule = SetIssue.model_validate(rule_findings(blocks)[0])
        individual_issue = SetIssue(**{**ISSUE, "criterion": "design", "refs": ["L3"],
                                       "explanation": "Ответ с HTTP 200 и результатом ERROR."})
        self.assertIn("L3", rule.refs)
        self.assertTrue(overlaps_rule(individual_issue, rule))
        self.assertFalse(overlaps_rule(individual_issue, rule, ["L60"]))

    def test_documented_api_types_and_bounds_answer_matching_questions(self):
        template = (
            "## Запрос\n| Параметр | Тип | Логика |\n| --- | --- | --- |\n"
            "| amount | integer | 10–100 |\n| enabled | integer | {} |\n"
            "\n## Ответ\n| Параметр | Тип |\n| --- | --- |\n| amount | string |\n"
        )
        _, sufficient = source_blocks(template.format("0 или 1"), structured=True)
        _, underspecified = source_blocks(template.format("—"), structured=True)
        rules_question = "Какие конкретно ограничения проверяются для суммы и переключателя?"
        self.assertIsNotNone(answered_by_document(rules_question, sufficient))
        self.assertIsNone(answered_by_document(rules_question, underspecified))
        validation = "Каким конкретным правилам валидации должны соответствовать сумма и переключатель?"
        self.assertIsNotNone(answered_by_document(validation, sufficient))
        self.assertIsNone(answered_by_document(validation, underspecified))
        self.assertIsNotNone(answered_by_document(
            "Должно ли поле amount в ответе возвращаться в виде строки или числового типа?", sufficient))
        self.assertIsNotNone(answered_by_document(
            "Какой тип данных должен возвращаться в поле amount в ответе: string или integer?", sufficient))

    def test_explicit_foreign_card_status_does_not_resolve_other_denials(self):
        _, blocks = source_blocks(
            "# Контракт\n## Статусы\n403 — доступ запрещён.\n\nДля чужой карты возвращается 404.",
            structured=True,
        )
        direct = "Какой HTTP-статус должен возвращаться для чужой карты: 403 или 404?"
        self.assertEqual(answered_by_document(direct, blocks).ref, "L5")
        self.assertIsNone(answered_by_document(
            "Для каких отказов API возвращает 403, если для чужой карты есть 404?", blocks))

    def test_status_for_missing_authorization_stays_within_one_contract(self):
        scenario = (
            "# API\n\n## Сохранение\n### Логика\nПроверить пользовательскую сессию.\n\n"
            "### Статусы\n401 — запрос без необходимой авторизации.\n\n"
            "403 — карта недоступна владельцу.\n\n"
            "## Чтение\n### Логика\nПроверить пользовательскую сессию.\n"
        )
        question = "Какой HTTP-статус возвращается при отсутствии сессии?"
        conflicting = scenario.replace("403 — карта недоступна владельцу.", "403 — запрос без авторизации.")
        for source_text, expected in ((scenario, True), (scenario.replace("401", "403"), False), (conflicting, False)):
            _, blocks = source_blocks(source_text, structured=True)
            save, read = [block for block in blocks if block.text.startswith("Проверить")]
            self.assertEqual(bool(answered_by_document(question, blocks, [save.section], sources=[save])), expected)
            self.assertIsNone(answered_by_document(question, blocks, [read.section], sources=[read]))
            for open_question in (
                "Какой HTTP-статус возвращается при отсутствии сессии или при её истечении?",
                "Какой HTTP-статус и сообщение возвращаются при отсутствии сессии?",
                "Какой HTTP-статус возвращается при отсутствии сессии — 401 или 403?",
            ):
                self.assertIsNone(answered_by_document(open_question, blocks, [save.section], sources=[save]))

    def test_bearer_example_does_not_imply_an_extra_session_channel(self):
        overview = "### Общие параметры\n| Поле | Значение |\n| --- | --- |\n"
        declaration = "| **Authorization** | Bearer, сессия владельца карты |\n"
        command = '| **CURL** | curl -H "Authorization: Bearer $TOKEN" /settings |\n'
        same_operation = overview + declaration + command
        question = "Каким способом передается сессия владельца карты помимо заголовка Authorization с Bearer токеном?"
        for details, expected in (
            (same_operation, True),
            (overview + declaration + "\n## Другая операция\n" + overview + command, False),
            (same_operation + "\n### Логика\nДополнительно проверить cookie сессии.\n", False),
        ):
            _, blocks = source_blocks("# API\n\n## Сохранение\n" + details, structured=True)
            cited = next(block for block in blocks if "**Authorization**" in block.text)
            self.assertEqual(bool(answered_by_document(question, blocks, [cited.section], sources=[cited])), expected)
            self.assertIsNone(answered_by_document(
                "Как проверяется связь сессии с владельцем карты?", blocks, [cited.section], sources=[cited]))

    def test_individual_review_preserves_open_issue_beside_documented_answer(self):
        _, sequence = source_blocks(
            "# Сохранение\n\n## Логика\nПроверить пользовательскую сессию.\n\n"
            "## Статусы\n401 — запрос без необходимой авторизации.",
            structured=True,
        )
        source = sequence[2]
        available = {block.ref: block for block in sequence}
        base = {**ISSUE, "criterion": "completeness"}
        question = "Какой HTTP-статус возвращается при отсутствии сессии?"
        unresolved = "Сколько времени действует пользовательская сессия?"
        request = IndividualReview.model_validate({"requirements": [{
            "ref": source.ref, "quote": source.text, "summary": "Проверка сессии",
            "assessment": "Срок действия сессии требует уточнения.",
            "issues": [{**base, "question": question}, {**base, "question": unresolved}],
        }]})
        [(item, _)], omitted, replaced = individual_results(request, available)
        self.assertEqual([issue.question for issue in item.issues], [unresolved])
        self.assertIn("Срок действия сессии требует уточнения.", item.assessment)
        self.assertIn(sequence[-1].ref, item.assessment)
        self.assertEqual((omitted, replaced), (0, 0))

    def test_documented_status_does_not_hide_a_contradicting_source(self):
        _, sequence = source_blocks(
            "# Сохранение\n\n## Статусы\n403 — отклонить запрос для чужой карты.\n\n"
            "Для чужой карты возвращается 404.",
            structured=True,
        )
        blocks = {block.ref: block for block in sequence}
        payload = whole_set((sequence[-2].ref, sequence[-1].ref))
        payload["issues"][0].update(
            explanation="Для чужой карты указаны два разных кода.",
            question="Какой HTTP-статус должен возвращаться для чужой карты: 403 или 404?",
        )
        result, omitted = set_results(SetReview.model_validate(payload), blocks)
        self.assertEqual(len(result.issues), 1)
        self.assertEqual(omitted, 0)

    def test_explicit_per_card_cap_filters_a_redundant_question_in_both_passes(self):
        text = ("# Уведомления\n\n## Частота\n"
                "**Ф-3.** Когда расходы достигают порога, клиент получает push. "
                "На карту приходится максимум один такой push за календарный месяц.")
        question = ("Распространяется ли ограничение «максимум один такой push за календарный месяц» "
                    "на каждую карту отдельно или на весь договор клиента?")
        answered = {**ISSUE, "criterion": "clarity", "question": question}
        open_question = {**answered, "question": "По какому часовому поясу начинается новый календарный месяц?"}
        for suffix, stays_open in (
            ("", False),
            ("\n**Ф-4.** На весь договор клиента допускается максимум один push за календарный месяц.", True),
        ):
            _, sequence = source_blocks(text + suffix, structured=True)
            source = next(block for block in sequence if block.source_id == "Ф-3")
            blocks = {block.ref: block for block in sequence}
            individual = IndividualReview.model_validate({"requirements": [{
                "ref": source.ref, "quote": source.text, "summary": "Частота уведомлений",
                "assessment": "Указан предел отправки push.",
                "issues": [answered, open_question],
            }]})
            [(item, _)], _, _ = individual_results(individual, blocks, enforce_numbered=False)
            expected = [question, open_question["question"]] if stays_open else [open_question["question"]]
            self.assertEqual([issue.question for issue in item.issues], expected)
            payload = whole_set((source.ref,))
            payload["issues"] = [{**issue, "refs": [source.ref]} for issue in (answered, open_question)]
            result, excluded = set_results(SetReview.model_validate(payload), blocks)
            self.assertEqual([issue.question for issue in result.issues], expected)
            self.assertEqual(excluded, 0)

        _, sequence = source_blocks(text.replace("На карту приходится", "Допускается"), structured=True)
        source = sequence[-1]
        self.assertIsNone(answered_by_document(question, sequence, sources=[source]))
        _, sequence = source_blocks(text[:-1] + ", если у клиента только одна карта.", structured=True)
        self.assertIsNone(answered_by_document(question, sequence, sources=[sequence[-1]]))
        _, sequence = source_blocks(text, structured=True)
        compound = question[:-1] + " и как учитывать перевыпуск карты?"
        self.assertIsNone(answered_by_document(compound, sequence, sources=[sequence[-1]]))

    def test_documented_amount_range_only_resolves_its_own_validation_question(self):
        question = "Какие именно значения суммы вызывают возврат состояния ERROR на данном шаге?"
        logic = "### Логика\nПри отклонении суммы вернуть прежнее состояние и результат ERROR.\n\n"
        params = "### Параметры запроса\n| Поле | Тип | Ограничения |\n| --- | --- | --- |\n"
        row = "| amount | integer | 1 000–1 000 000 |"
        for table, expected in ((params + row, True), (params + row.replace("1 000–1 000 000", "—"), False),
                                ("## Другая операция\n" + params + row, False)):
            with self.subTest(answered=expected, table=table):
                _, blocks = source_blocks("# API\n\n## Сохранение\n" + logic + table, structured=True)
                source = next(block for block in blocks if block.text.startswith("При отклонении"))
                sections = [source.section]
                self.assertEqual(bool(answered_by_document(question, blocks, sections, sources=[source])), expected)
                self.assertIsNone(answered_by_document(
                    question + " Какой HTTP-статус использовать?", blocks, sections, sources=[source]))

    def test_response_format_uses_field_and_scope_from_the_cited_row(self):
        _, blocks = source_blocks(
            "# Сохранение\n\n## Ответ\n| Поле | Формат | Описание |\n| --- | --- | --- |\n"
            "| amount | string | Порог в тенге |\n\n```json\n{\"amount\":50000}\n```\n",
            structured=True,
        )
        row, example = blocks[-2:]
        question = "Должно ли числовое значение порога в ответе сериализоваться как строка или как число?"
        self.assertEqual(answered_by_document(question, blocks, [row.section], sources=[row]), row)
        self.assertIsNone(answered_by_document(question, blocks, [row.section], sources=[]))
        direct = "Должен ли параметр amount возвращаться в формате строки или числа?"
        self.assertEqual(answered_by_document(direct, blocks, [row.section], sources=[row]), row)
        self.assertIsNone(answered_by_document(direct, blocks, [row.section], sources=[]))
        self.assertIsNone(answered_by_document(question, blocks, [row.section], sources=[row, example]))

    def test_get_is_flagged_only_when_the_same_contract_writes(self):
        template = (
            "# Операции\n## Контракт уведомлений\n### Метод\n"
            "HTTP method: GET\n\n### Выполнение\n{} настройки карты.\n"
        )
        _, writes = source_blocks(template.format("Заменить"), structured=True)
        _, reads = source_blocks(template.format("Прочитать"), structured=True)
        finding = rule_findings(writes)[0]
        self.assertIn("RFC 9110", finding["explanation"])
        self.assertEqual(finding["refs"], ["L4", "L7"])
        self.assertEqual(rule_findings(reads), [])

    def test_get_duplicate_merges_only_within_its_own_contract(self):
        source = (
            "# API\n## Изменение лимита\n### Метод\nHTTP method: GET\n"
            "### Выполнение\nЗаменить настройки карты.\n"
            "### Параметры запроса\nТело не используется.\n"
            "## Замена контакта\n### Параметры запроса\nТело не используется.\n"
        )
        _, blocks = source_blocks(source, structured=True)
        lookup = {block.ref: block for block in blocks}
        canonical = SetIssue.model_validate(rule_findings(blocks)[0])
        duplicate = SetIssue(**{**ISSUE, "criterion": "design", "refs": ["L8"],
                               "explanation": "GET используется для сохранения настроек."})
        self.assertTrue(overlaps_rule(duplicate, canonical, blocks=lookup))
        self.assertFalse(overlaps_rule(duplicate, canonical, ["L11"], blocks=lookup))
        inconsistent_method = duplicate.model_copy(update={
            "criterion": "consistency",
            "question": "Почему для изменения состояния используется метод GET?",
        })
        self.assertTrue(overlaps_rule(inconsistent_method, canonical, blocks=lookup))
        self.assertFalse(overlaps_rule(inconsistent_method, canonical, ["L11"], blocks=lookup))


class ReviewEntryPointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch.dict(os.environ, {"LLM_PROVIDER": "openai-compatible", "LLM_BASE_URL": "https://provider.example/v1",
                            "LLM_API_KEY": "test-token", "LLM_MODEL": "org/model:free", "LLM_FALLBACK_MODEL": ""})
    def test_full_audit_can_use_a_compatible_chat_api(self):
        answers = iter((individual(), whole_set()))
        expected_model = "org/model:2026-11"

        def provider(request, timeout):
            self.assertEqual(request.full_url, "https://provider.example/v1/chat/completions")
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
            body = json.loads(request.data)
            self.assertEqual(body["model"], "org/model:free")
            self.assertEqual(body["response_format"], {"type": "json_object"})
            self.assertIn("schema", body["messages"][0]["content"])
            self.assertEqual(body["messages"][1]["role"], "user")
            return io.BytesIO(json.dumps({"model": expected_model, "choices": [{
                "finish_reason": "stop", "message": {"content": json.dumps(next(answers))}
            }]}).encode())

        self.assertTrue(self.client.get("/api/config").json["gemini"])
        with patch("gemini.urlopen", side_effect=provider) as transport:
            response = self.client.post("/api/analyze/gemini?operation=report",
                                        json={"text": SPEC, "filename": "requirements.md"})
        self.assertEqual(response.status_code, 200)
        audit = response.json["review"]
        self.assertEqual(audit["provider"], "openai-compatible")
        self.assertEqual(transport.call_count, 2)
        self.assertEqual([stage["model"] for stage in audit["passes"]], [expected_model, expected_model])
        self.assertEqual([item["line"] for item in audit["findings"][0]["evidence"]], [4, 10])
        self.assertIn("Модель и правила SanA1", response.json["markdown"])

    @patch.dict(os.environ, CONFIG)
    def test_refund_case_preserves_requirement_ids_across_markdown_formats(self):
        expected_ids = ("Ф-1", "Ф-2", "Ф-3", "П-1", "П-2", "П-3")
        for marker, separator in (("", "\n"), ("", "\n\n"), ("* ", "\n")):
            text = (
                "# Возврат на замороженный счёт\n\n## Функциональные требования\n"
                + separator.join(marker + clause for clause in REFUND_CLAUSES)
                + "\n\n## Критерии приёмки\n"
                + separator.join(marker + clause for clause in REFUND_ACCEPTANCE)
            )
            corrected = text.replace("Входящий возврат покупки не зачисляется до снятия заморозки.",
                                     "Входящий возврат покупки доступен.").replace(
                "баланс не меняется до снятия заморозки.",
                REFUND_CREDIT_RESULT,
            )
            for document, conflict in ((text, True), (corrected, False)):
                with self.subTest(marker=marker, separator=separator, conflict=conflict):
                    lines = document.splitlines()
                    expected_lines = {
                        label: next(i for i, line in enumerate(lines, 1) if f"**{label}.**" in line)
                        for label in expected_ids
                    }

                    def provider(model, payload, timeout):
                        data = json.loads(payload["contents"][0]["parts"][0]["text"])
                        rows = {row["source_id"]: row for row in data["blocks"] if row["source_id"]}
                        self.assertEqual(tuple(rows), expected_ids)
                        if "required_refs" in data:
                            return model_answer({"requirements": [
                                {"ref": row["ref"], "quote": row["text"], "summary": row["text"],
                                 "assessment": "Описано поведение системы.",
                                 "issues": [{**ISSUE, "criterion": "clarity",
                                             "question": "Зачислять ли возврат на замороженный счёт или ждать до снятия заморозки?"}]
                                 if conflict and label == "Ф-1" else []}
                                for label, row in rows.items()
                            ]})
                        refs = [rows[label]["ref"] for label in ("Ф-1", "Ф-3", "П-1")]
                        evaluation = whole_set(refs)
                        for key in ("consistency", "completeness", "traceability", "feasibility"):
                            evaluation[key] = {**SET_CHECK, "refs": refs[:1]}
                        evaluation["issues"] = [{
                            **ISSUE, "refs": refs,
                            "explanation": "Для возврата на замороженный счёт указаны несовместимые сроки зачисления.",
                            "question": "Зачислять входящий возврат на замороженный счёт в срок или удержать до снятия заморозки?",
                        }] if conflict else []
                        return model_answer(evaluation)

                    with patch("hackathon_review.generate", side_effect=provider):
                        response = self.client.post("/api/analyze/gemini?operation=report",
                                                    json={"text": document, "filename": "refund.md"})
                    self.assertEqual(response.status_code, 200)
                    audit = response.get_json()["review"]
                    self.assertEqual({item["source_id"]: item["source"]["line"]
                                      for item in audit["requirements"]}, expected_lines)
                    self.assertEqual(len(audit["findings"]), int(conflict))
                    if conflict:
                        self.assertEqual(audit["findings"][0]["severity"], "blocker")
                        self.assertEqual(audit["findings"][0]["engine"], "Правило SanA1")
                        self.assertEqual(
                            {item["source_id"]: item["line"] for item in audit["findings"][0]["evidence"]},
                            {label: expected_lines[label] for label in ("Ф-1", "Ф-3")},
                        )

    @patch.dict(os.environ, CONFIG)
    def test_missing_production_url_is_reported_once_across_review_stages(self):
        individual_issue = {
            **ISSUE, "criterion": "completeness",
            "explanation": "Не указан адрес production.",
            "question": "Какой Request URL должен использоваться в промышленной среде?",
        }
        separate_issue = {
            **individual_issue,
            "question": "У кого согласовать включение уведомлений?",
        }
        draft = individual()
        draft["requirements"][0]["issues"] = [individual_issue]
        evaluation = whole_set()
        evaluation["issues"] = [
            {**individual_issue, "refs": ["L4"], "question": "Какой URL нужно использовать в продуктовой среде?"},
            {**separate_issue, "refs": ["L4"]},
        ]
        with patch("hackathon_review.generate", side_effect=[model_answer(draft), model_answer(evaluation)]):
            response = self.client.post(
                "/api/analyze/gemini?operation=report", data=SPEC.encode(),
                content_type="application/octet-stream",
                headers={"X-File-Name": "requirements.md", "Accept": "application/json"},
            )
        self.assertEqual(response.status_code, 200)
        findings = response.get_json()["review"]["findings"]
        self.assertEqual([item["question"] for item in findings], [individual_issue["question"], separate_issue["question"]])

    def test_production_address_identity_uses_each_empty_endpoint_field(self):
        _, blocks = source_blocks(
            "# API\n\nПриложение использует операции чтения и записи.\n\n"
            "## Чтение\nПуть чтения. Dev: /read. Prod: —.\n\n"
            "## Запись\nПуть записи. Dev: /write. Prod: —.",
            structured=True,
        )
        shared, read, write = blocks[1], blocks[3], blocks[5]
        issue = SetIssue(**{**ISSUE, "criterion": "completeness", "refs": [read.ref],
                            "explanation": "Отсутствует Prod URL.", "question": "Какой URL нужен в продуктивном контуре?"})
        self.assertEqual(missing_production_address_keys(issue, [read]), {read.ref})
        self.assertEqual(missing_production_address_keys(issue, [shared, read]), {read.ref})
        self.assertEqual(missing_production_address_keys(issue, [shared, write]), {write.ref})
        for criterion, severity, explanation in (
            ("feasibility", "blocker", "В строке Prod URL указан прочерк, поэтому адрес развёртывания неизвестен."),
            ("completeness", "minor", "Отсутствует Prod URL."),
        ):
            variant = issue.model_copy(update={"criterion": criterion, "severity": severity, "explanation": explanation})
            normalized = scope_production_address(variant, [read])
            self.assertEqual(normalized.severity, "major")
            self.assertIn("Dev-маршрут указан", normalized.explanation)
            self.assertEqual(missing_production_address_keys(normalized, [read]), {read.ref})
        self.assertEqual(scope_production_address(issue, [shared]), issue)
        compound = issue.model_copy(update={"question": "Какой Prod URL нужно указать и как передавать токен?"})
        self.assertEqual(missing_production_address_keys(compound, [read]), set())

    def test_complex_docx_pair_exposes_text_controls_and_requires_visual_review(self):
        fixture_dir = Path(__file__).parent / "fixtures"
        for filename, defective in (("qr-refund-audit.docx", True), ("qr-refund-corrected.docx", False)):
            with self.subTest(filename=filename):
                fixture = fixture_dir / filename
                source = fixture.read_bytes()
                audit = audit_document(fixture, source, rules_only=True)
                self.assertTrue(audit["unreviewed_figures"])
                self.assertIn("Сверьте схемы и изображения", render_review(audit))
                self.assertEqual(len(audit["findings"]), 5 if defective else 0)
                if defective:
                    self.assertEqual({frozenset(ref["line"] for ref in item["evidence"]) for item in audit["findings"]},
                                     {frozenset(pair) for pair in ((11, 21), (9, 74), (39, 46), (72, 75), (58, 60))})
                    self.assertEqual([ref["source_id"] for ref in audit["findings"][0]["evidence"]], ["QR-03", "QR-07"])
                    self.assertIn("Idempotency-Key", "\n".join(item["source"]["quote"] for item in audit["requirements"]))
                    self.assertTrue(any("создавать заявку" in item["question"] for item in audit["findings"]))
                    self.assertTrue(any("ожидаемый результат" in item["question"] for item in audit["findings"]))
                    webhook = next(item for item in audit["findings"] if "вебхука" in item["question"])
                    self.assertEqual([ref["source_id"] for ref in webhook["evidence"]], ["EVT-01", "EVT-02"])
                    self.assertIn("204", webhook["explanation"])
                    self.assertIn("200", webhook["explanation"])
                extracted = self.client.post("/api/extract", data=source,
                                             content_type="application/octet-stream", headers={"X-File-Type": "docx"}).get_json()
                self.assertEqual(len(extracted["media"]), 2)
                self.assertIn("unreviewed_figures", extracted["warnings"])
                repeated = self.client.post("/api/analyze?operation=report",
                                            json={"text": extracted["text"], "filename": "revised.md"}).get_json()["review"]
                self.assertTrue(repeated["unreviewed_figures"])

    def test_visual_audit_checks_actual_embedded_figures_and_fails_open_to_text(self):
        folder = Path(__file__).parent / "fixtures"

        def text_stage(text, extension, model, *, table_rows, rules_only):
            return review_requirements(text, extension, table_rows=table_rows, rules_only=True)

        for filename, status, expected_count in (
            ("qr-refund-audit.docx", "PENDING", 1),
            ("qr-refund-corrected.docx", "SETTLED", 0),
        ):
            file = folder / filename
            response = model_answer({"images": [
                {"number": 1, "transitions": [{"event": "Подтверждение\nСобытие провайдера", "status": status}]},
                {"number": 2, "transitions": []},
            ]})
            with patch("hackathon_cli.review_requirements", side_effect=text_stage), \
                    patch("visual_review.generate", return_value=response) as provider:
                audit = audit_document(file, file.read_bytes())
            parts = provider.call_args.args[1]["contents"][0]["parts"]
            images = [part["inline_data"] for part in parts if "inline_data" in part]
            self.assertEqual(len(images), 2)
            self.assertTrue(all(image["mime_type"] == "image/jpeg" and image["data"].startswith("/9j/") for image in images))
            with patch.dict(os.environ, {"LLM_BASE_URL": "https://example.org/v1", "LLM_API_KEY": "test-only"}):
                payload = json.loads(compatible_request("vision-example", provider.call_args.args[1]).data)
            request_images = [part for part in payload["messages"][1]["content"] if part["type"] == "image_url"]
            self.assertEqual(len(request_images), 2)
            self.assertTrue(request_images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,/9j/"))
            self.assertEqual(audit["visual_review"], {"sent": 2, "compared": 1, "status": "completed"})
            visual = [item for item in audit["findings"] if "visual_evidence" in item]
            self.assertEqual(len(visual), expected_count)
            source = extract_document("docx", file.read_bytes(), include_previews=False)["text"]
            result = assess(audit, source, corrected=not expected_count)
            if visual:
                self.assertEqual([item["line"] for item in visual[0]["evidence"]], [55, 68])
                self.assertEqual(visual[0]["visual_evidence"]["table_status"], "SETTLED")
                self.assertIn("на схеме PENDING, в таблице SETTLED", render_review(audit))
                self.assertEqual(result["matched"], 6)
                duplicate = {**visual[0], "id": "duplicate"}
                repeated = assess({**audit, "findings": [*audit["findings"], duplicate]}, source, corrected=False)
                self.assertEqual(repeated["duplicate"], {DIAGRAM: [visual[0]["id"], "duplicate"]})
                self.assertEqual(repeated["matched"], 5)
                self.assertEqual(repeated["additional"], [])
                visual[0]["visual_evidence"]["figure_status"] = "SETTLED"
                incorrect = assess(audit, source, corrected=False)
                self.assertEqual(incorrect["missing"], [DIAGRAM])
            else:
                self.assertEqual(result, {"citations": result["citations"], "compared": 1, "visual": 0, "total": 0})

        file = folder / "qr-refund-audit.docx"
        with patch("hackathon_cli.review_requirements", side_effect=text_stage), \
                patch("visual_review.generate", side_effect=ValueError("gemini_timeout")):
            missed = audit_document(file, file.read_bytes())
        self.assertEqual(missed["visual_review"], {"sent": 2, "compared": 0, "status": "unavailable"})
        self.assertEqual(len(missed["findings"]), 5)

    def test_empty_acceptance_cell_does_not_duplicate_a_model_question_about_that_cell(self):
        fixture = Path(__file__).parent / "fixtures" / "qr-refund-audit.docx"
        extracted = extract_document("docx", fixture.read_bytes(), preserve_boundary_lines=True, include_previews=False)
        _, blocks = source_blocks(extracted["text"], structured=True, table_rows=extracted["table_rows"])
        accepted = next(SetIssue.model_validate(rule) for rule in rule_findings(blocks)
                        if "ожидаемый результат" in rule["question"])
        row = accepted.refs[-1]
        model = SetIssue(**{**ISSUE, "criterion": "completeness", "refs": [row],
                            "question": "Какой ожидаемый результат следует указать в таблице приёмки?"})
        self.assertTrue(overlaps_rule(model, accepted))
        self.assertFalse(overlaps_rule(model.model_copy(update={"refs": [accepted.refs[0]]}), accepted))
        independent = model.model_copy(update={"question": "Как долго хранить ключ для повторной доставки?"})
        self.assertFalse(overlaps_rule(independent, accepted))
        live = model.model_copy(update={
            "refs": accepted.refs,
            "question": "Какой результат должен возвращаться при отправке повторного запроса с тем же ключом и суммой?",
            "explanation": "В строке L75 таблицы не заполнен столбец ожидаемого результата.",
        })
        self.assertTrue(overlaps_rule(live, accepted))
        by_reference = live.model_copy(update={
            "question": "Какой именно ожидаемый результат должен быть зафиксирован для повторного запроса с тем же ключом и суммой?"
        })
        self.assertTrue(overlaps_rule(by_reference, accepted))
        self.assertFalse(overlaps_rule(live.model_copy(update={"question": "Какой HTTP-статус и тело возвращает повтор?"}), accepted))
        same_retry = live.model_copy(update={
            "criterion": "verifiability",
            "question": "Какой статус и тело ответа должен возвращать API при повторной отправке запроса с тем же ключом и суммой?",
            "explanation": "В таблице переходов состояний для повторного запроса с тем же ключом не указан ожидаемый результат.",
        })
        self.assertTrue(overlaps_rule(same_retry, accepted))
        self.assertTrue(overlaps_rule(same_retry.model_copy(update={
            "question": "Какой статус и код ответа должен возвращать API при повторной отправке запроса с тем же ключом и неизменным телом?",
            "explanation": "В таблице переходов для запроса с тем же ключом и суммой не заполнен ожидаемый результат.",
        }), accepted))
        self.assertFalse(overlaps_rule(same_retry.model_copy(update={
            "question": "Какой результат API должен возвращать при повторной отправке запроса с тем же ключом, но другой суммой?"
        }), accepted, blocks={block.ref: block for block in blocks}))
        other_refs = [*accepted.refs, next(block.ref for block in blocks if block.ref not in accepted.refs)]
        self.assertFalse(overlaps_rule(same_retry.model_copy(update={"refs": other_refs}), accepted))
        self.assertFalse(overlaps_rule(same_retry.model_copy(update={
            "explanation": "У контрактов операций разные структуры ответа для повторной отправки."
        }), accepted))

    def test_refund_example_answers_the_rejection_grounds_without_hiding_a_conflict(self):
        question = ("Какое именно ограничение (суточный лимит, лимит одного возврата или остаток покупки) "
                    "должно приводить к отклонению запроса на 75 000 ₸ в таблице приёмки?")
        paraphrase = "Какая максимальная сумма одного возврата должна применяться для проверки в тестовом примере?"
        priority = ("Какое правило лимита является приоритетным для отклонения возврата на 75 000 ₸ при покупке на "
                    "80 000 ₸ — ограничение максимальной суммы одного возврата в 50 000 ₸ или проверка остатка покупки?")
        order_question = priority.replace("является приоритетным", "применяется первым")
        for name, variants in (
            ("qr-refund-corrected.docx", (
                (question, True),
                (paraphrase, True),
                (priority, True),
                (question.replace("75 000", "45 000"), False),
                (question.replace("75 000", "50 000"), False),
                (order_question, False),
                ("Какой HTTP-статус должен возвращаться при превышении лимита одного возврата?", False),
                ("Какой лимит должен проверяться первым, если одновременно превышены два ограничения?", False),
            )),
            ("qr-refund-audit.docx", ((question, False), (paraphrase, False), (priority, False))),
        ):
            fixture = Path(__file__).parent / "fixtures" / name
            parsed = extract_document("docx", fixture.read_bytes(), preserve_boundary_lines=True, include_previews=False)
            _, sequence = source_blocks(parsed["text"], structured=True, table_rows=parsed["table_rows"])
            blocks = {block.ref: block for block in sequence}
            cap = next(block for block in sequence if block.source_id == "QR-02")
            row = next(block for block in sequence if block.kind == "table_row" and "75 000 ₸" in block.text)
            refs = [cap.ref, row.ref]
            for wording, documented in variants:
                with self.subTest(fixture=name, wording=wording):
                    payload = whole_set(refs)
                    payload["consistency"] = {**SET_CHECK, "outcome": "issue", "refs": refs}
                    payload["issues"] = [{**ISSUE, "refs": refs, "question": wording}]
                    result, excluded = set_results(SetReview.model_validate(payload), blocks)
                    self.assertEqual(excluded, 0)
                    self.assertEqual(len(result.issues), 0 if documented else 1)
                    order = wording == order_question
                    self.assertEqual(result.consistency.outcome, "unknown" if documented or order else "issue")
                    if order:
                        self.assertEqual(result.issues[0].criterion, "clarity")
                        self.assertEqual(result.issues[0].severity, "minor")
            payload = whole_set(refs)
            payload["issues"] = [{
                **ISSUE, "refs": refs,
                "question": "Какое именно правило лимита должно применяться: максимальная сумма одного возврата 50 000 ₸ "
                            "или остаток покупки после подтверждённых возвратов?",
                "explanation": "Предел 50 000 ₸, в таблице приёмки проверяется запрос на 75 000 ₸ для покупки в 80 000 ₸, "
                               "и в качестве причины отклонения указан лимит одного возврата.",
            }]
            result, _ = set_results(SetReview.model_validate(payload), blocks)
            self.assertEqual(len(result.issues), int(name == "qr-refund-audit.docx"))
            payload["issues"][0]["question"] = (
                "Какая именно проверка должна срабатывать первой для запроса на 75 000 ₸ при покупке на 80 000 ₸: "
                "ограничение максимальной суммы одного возврата в 50 000 ₸ или проверка остатка покупки?"
            )
            result, _ = set_results(SetReview.model_validate(payload), blocks)
            self.assertEqual(len(result.issues), 1)
            corrected = name == "qr-refund-corrected.docx"
            self.assertEqual(result.issues[0].criterion, "clarity" if corrected else "consistency")
            self.assertEqual(result.issues[0].severity, "minor" if corrected else ISSUE["severity"])
            payload["issues"][0].update(
                question="Каково корректное максимальное ограничение суммы одного возврата — 50 000 ₸ "
                         "или иное значение, позволяющее проверить сценарий из таблицы?",
                explanation="Лимит одного возврата в 50 000 ₸ противоречит сценарию в таблице, где проверяется возврат на 75 000 ₸.",
            )
            result, _ = set_results(SetReview.model_validate(payload), blocks)
            self.assertEqual(len(result.issues), int(not corrected))

    def test_qr_refund_duplicate_findings_use_the_same_decision(self):
        fixture = Path(__file__).parent / "fixtures" / "qr-refund-audit.docx"
        data = extract_document("docx", fixture.read_bytes(), preserve_boundary_lines=True, include_previews=False)
        _, blocks = source_blocks(data["text"], structured=True, table_rows=data["table_rows"])
        for prompt, duplicate, separate in (
            ("замороженный счёт",
             "Должен ли сервис проводить зачисление возврата на замороженный счёт в срок до 18:00 следующего рабочего дня "
             "или ожидать снятия заморозки перед зачислением?",
             "Какое событие сообщает сервису о снятии заморозки счёта?"),
            ("вебхука",
             "Какой HTTP-статус должен возвращать сервис при успешной обработке события — 204 или 200?",
             "Какой HTTP-статус выбрасывается при недействительной подписи события?"),
            ("лимит на один возврат",
             "Какое максимальное ограничение по сумме на один возврат является верным: 50 000 ₸ или 100 000 ₸?",
             "Какой HTTP-статус нужно вернуть приложению при превышении лимита?"),
            ("ожидаемый результат",
             "Какой ожидаемый результат должен быть зафиксирован для строки повторного запроса с тем же ключом и суммой?",
             "Как долго хранить ключ операции?"),
        ):
            rule = next(SetIssue.model_validate(item) for item in rule_findings(blocks) if prompt in item["question"])
            model = SetIssue(**{**ISSUE, "refs": rule.refs, "question": duplicate})
            self.assertTrue(overlaps_rule(model, rule))
            self.assertFalse(overlaps_rule(model.model_copy(update={"question": separate}), rule))
            if prompt == "замороженный счёт":
                lived = ("Требуется ли зачислять входящий возврат на замороженный счёт в срок до 18:00 следующего рабочего дня "
                         "или зачисление должно быть полностью заблокировано до момента снятия заморозки?")
                self.assertTrue(overlaps_rule(model.model_copy(update={"question": lived}), rule))
                api_status = "Какой HTTP-статус возвращается при отказе в зачислении возврата на замороженный счёт?"
                self.assertFalse(overlaps_rule(model.model_copy(update={"question": api_status}), rule))
            if prompt == "вебхука":
                incoming = "Какой именно HTTP-статус должен возвращать сервис при успешной обработке входящего события: 200 или 204?"
                self.assertTrue(overlaps_rule(model.model_copy(update={"question": incoming}), rule))
                receiving = "Какой код состояния должен возвращать обработчик при успешном получении события: HTTP 204 или HTTP 200?"
                self.assertTrue(overlaps_rule(model.model_copy(update={"question": receiving}), rule))
            if prompt == "лимит на один возврат":
                same_amounts = "Какое именно значение является корректным суточным или разовым лимитом: 50 000 ₸ или 100 000 ₸?"
                self.assertTrue(overlaps_rule(model.model_copy(update={"question": same_amounts}), rule))
                self.assertFalse(overlaps_rule(model.model_copy(update={"question": same_amounts.replace("100 000", "150 000")}), rule))
            if prompt == "ожидаемый результат":
                scenario_result = "Какой ожидаемый результат должен быть зафиксирован в приёмке для повторного запроса с тем же Idempotency-Key?"
                self.assertTrue(overlaps_rule(model.model_copy(update={"question": scenario_result}), rule))

    def test_validation_duplicate_can_put_both_statuses_in_its_question_only(self):
        refs = ["L151", "L162", "L170", "L121"]
        rule = SetIssue(**{**ISSUE, "refs": refs, "explanation": "HTTP 200 содержит ERROR, но статус 400 задан для ошибки."})
        model = SetIssue(**{**ISSUE, "refs": list(reversed(refs)),
                            "question": "Какой HTTP-статус (200 или 400) должен возвращать метод при ошибке валидации суммы?",
                            "explanation": "Рассинхронизация описания статусов и примеров блокирует обработку ответов."})
        self.assertTrue(overlaps_rule(model, rule))
        self.assertFalse(overlaps_rule(model.model_copy(update={"refs": ["L121", "L162"]}), rule))
        self.assertFalse(overlaps_rule(model.model_copy(update={"question": "Какие поля должны быть в теле ошибки?"}), rule))

    def test_demo_correcting_the_calendar_keeps_the_independent_api_issue(self):
        response = self.client.get("/api/example?case=audit")
        self.assertEqual(response.status_code, 200)
        demo = response.get_json()
        text, filename = demo["text"], demo["filename"]
        headers = {"X-File-Name": filename, "Accept": "application/json"}
        baseline, revised = [
            self.client.post("/api/analyze?operation=report", data=value.encode(),
                             content_type="application/octet-stream", headers=headers).get_json()["review"]
            for value in (text, text.replace("Апрельский", "Мартовский"))
        ]
        self.assertEqual(baseline["file"], "virtual-card-demo.md")
        self.assertEqual(baseline["mode"], "rules")
        self.assertEqual(len(baseline["findings"]), 2)
        self.assertEqual(baseline["findings"][0]["evidence"][1]["location"], "L11")
        self.assertEqual(len(revised["findings"]), 1)
        self.assertEqual(revised["findings"][0]["evidence"], baseline["findings"][1]["evidence"])
        self.assertIn("GET", revised["findings"][0]["explanation"])

    @patch.dict(os.environ, {"GEMINI_API_KEY": ""})
    def test_local_route_preserves_citations_and_never_calls_gemini(self):
        headers = {"X-File-Name": "requirements.md", "Accept": "application/json"}
        with patch("hackathon_review.generate") as provider:
            response = self.client.post("/api/analyze?operation=report", data=RULES_SPEC.encode(),
                                        content_type="application/octet-stream", headers=headers)
            full = self.client.post("/api/analyze/gemini?operation=report", data=RULES_SPEC.encode(),
                                    content_type="application/octet-stream", headers=headers)
        provider.assert_not_called()
        self.assertEqual((response.status_code, full.status_code), (200, 503))
        self.assertEqual(full.get_json()["error"], "gemini_unconfigured")
        payload = response.get_json()
        audit = payload["review"]
        self.assertEqual((audit["mode"], audit["readiness"], audit["passes"]), ("rules", "blocked", []))
        self.assertEqual(audit["requirements"][0]["source_id"], "Ф-1")
        self.assertEqual([source["line"] for source in audit["findings"][0]["evidence"]], [4, 9])
        self.assertIn("Локальные правила SanA1", payload["markdown"])
        self.assertEqual([check["outcome"] for check in audit["checks"]],
                         ["issue", "unknown", "unknown", "unknown"])

    def test_audit_contract_example_runs_and_matches_the_local_route(self):
        response = self.client.get("/api/audit-contract")
        self.assertEqual(response.status_code, 200)
        contract = response.get_json()
        self.assertEqual(contract["contract_version"], 1)
        self.assertEqual(contract["method"], "POST")
        self.assertTrue(contract["endpoints"]["gemini"]["requires_server_key"])
        self.assertFalse(contract["endpoints"]["rules"]["requires_server_key"])
        sample = contract["inputs"]["application/json"]["example"]
        with patch("hackathon_review.generate") as provider:
            response = self.client.post(contract["endpoints"]["rules"]["path"], json=sample)
        provider.assert_not_called()
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(sorted(result), sorted(contract["outputs"]["application/json"]["fields"]))
        self.assertEqual(result["review"]["mode"], "rules")
        self.assertEqual(result["review"]["file"], sample["filename"])
        self.assertEqual(result["review"]["requirements"][0]["source_id"], "Ф-1")

    def test_published_example_is_discoverable_and_readable_with_get(self):
        contract = self.client.get("/api/audit-contract").get_json()
        example = contract["example_report"]
        self.assertEqual(example["method"], "GET")
        self.assertIn(f'href="{example["path"]}"', self.client.get("/", buffered=True).get_data(as_text=True))
        with patch("hackathon_review.generate") as provider:
            response = self.client.get(example["path"], buffered=True)
        provider.assert_not_called()
        self.assertEqual((response.status_code, response.mimetype), (200, "text/plain"))
        report = response.get_data(as_text=True)
        for section in ("Паспорт прогона", "Выделенные требования", "Проверка каждого требования",
                        "Проверка набора требований", "Вопросы автору ТЗ", "Сводка и готовность к разработке"):
            self.assertIn(f"## {section}", report)
        self.assertRegex(report, r"(?m)^- Версия SanA1 \(Git\) — [0-9a-f]{40}$")
        self.assertIn("- Режим — Модель и правила SanA1", report)

    def test_json_input_matches_identical_file_bytes_and_can_return_markdown(self):
        text = RULES_SPEC.replace("\n", "\r\n")
        url = "/api/analyze?operation=report"
        payload = {"text": text}
        structured = self.client.post(url, json=payload)
        raw = self.client.post(url, data=text.encode("utf-8"), content_type="application/octet-stream",
                               headers={"Accept": "application/json", "X-File-Name": "requirements.md"})
        markdown = self.client.post(url, json=payload, headers={"Accept": "text/markdown"})
        self.assertEqual((structured.status_code, raw.status_code, markdown.status_code), (200, 200, 200))
        self.assertEqual(structured.mimetype, "application/json")
        self.assertEqual(markdown.mimetype, "text/markdown")
        self.assertIn("Accept", structured.vary)
        self.assertIn("Отчёт о проверке требований", markdown.get_data(as_text=True))
        structured_review = structured.get_json()["review"]
        raw_review = raw.get_json()["review"]
        self.assertEqual(structured_review["sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())
        for key in ("file", "sha256", "requirements", "findings", "readiness"):
            self.assertEqual(structured_review[key], raw_review[key])

    @patch.dict(os.environ, CONFIG)
    def test_text_json_reaches_both_model_stages_on_the_provider_route(self):
        url = "/api/analyze/gemini?operation=report"
        with patch("hackathon_review.generate", side_effect=[model_answer(individual()), model_answer(whole_set())]):
            response = self.client.post(url, json={"filename": "требования.markdown", "text": SPEC, "mode": "rules"})
        self.assertEqual(response.status_code, 200)
        review = response.get_json()["review"]
        self.assertEqual((review["file"], review["mode"]), ("требования.markdown", "gemini"))
        self.assertEqual(len(review["passes"]), 2)

    @patch.dict(os.environ, {"GEMINI_API_KEY": ""})
    def test_json_invalid_input_does_not_contact_provider(self):
        url = "/api/analyze/gemini?operation=report"
        with patch("hackathon_review.generate") as provider:
            for name, data, status, error in (
                ("missing text", '{"filename":"a.md"}', 400, "invalid_request"),
                ("non-string filename", '{"text":"text","filename":null}', 400, "invalid_request"),
                ("malformed body", '{"text":', 400, "invalid_request"),
                ("unpaired surrogate", r'{"text":"\ud800"}', 400, "invalid_request"),
                ("binary format", '{"text":"text","filename":"a.pdf"}', 422, "unsupported_file"),
                ("unconfigured", '{"text":"Some requirement.","mode":"rules"}', 503, "gemini_unconfigured"),
            ):
                with self.subTest(name=name):
                    response = self.client.post(url, data=data, content_type="application/json")
                    self.assertEqual((response.status_code, response.get_json()["error"]), (status, error))
        provider.assert_not_called()

    @patch.dict(os.environ, CONFIG)
    def test_local_cli_stays_limited_when_no_supported_issue_remains(self):
        with tempfile.TemporaryDirectory() as work:
            input_path = Path(work, "test.md")
            output_path = Path(work, "review.json")
            input_path.write_text(RULES_SPEC.replace("Майский", "Апрельский"), encoding="utf-8")
            argv = ["app.py", "--input", str(input_path), "--output", str(output_path), "--rules-only"]
            with patch("hackathon_review.generate") as provider, patch("sys.argv", argv):
                self.assertEqual(main(), 0)
            provider.assert_not_called()
            audit = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual((audit["mode"], audit["readiness"], audit["findings"]), ("rules", "limited", []))
        self.assertTrue(all(check["outcome"] == "unknown" for check in audit["checks"]))

    @patch.dict(os.environ, CONFIG)
    def test_docx_keeps_heading_depth_and_typed_acceptance_rows(self):
        document = Document()
        document.add_heading("Уведомления", level=0)
        document.add_heading("Бизнес-правила", level=1)
        document.add_paragraph("Ф-1. Месяц определяется по дате покупки.")
        document.add_paragraph("Ф-2. Сервис отправляет уведомления.")
        document.add_heading("Приёмка", level=2)
        table = document.add_table(rows=2, cols=3)
        table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        for row, values in zip(table.rows, [
            ("Состояние", "Действие", "Итог"),
            ("Покупка 30 апреля", "Провести 1 мая", "Майский счётчик растёт"),
        ]):
            for cell, value in zip(row.cells, values):
                cell.text = value
        source = io.BytesIO()
        document.save(source)
        captured = {}

        def provider(model, payload, timeout):
            content = json.loads(payload["contents"][0]["parts"][0]["text"])
            captured.update({item["ref"]: item for item in content["blocks"]})
            rows = [item for item in content["blocks"] if item["source_id"] or item["kind"] == "table_row"]
            self.assertEqual(len(rows), 3)
            if "required_refs" in content:
                return model_answer({"requirements": [
                    {"ref": item["ref"], "quote": item["text"], "summary": item["text"],
                     "assessment": "Требование относится к учёту расходов.", "issues": []}
                    for item in rows
                ]})
            evaluation = whole_set()
            for key in ("consistency", "completeness", "traceability", "feasibility"):
                evaluation[key] = {**SET_CHECK, "refs": [rows[0]["ref"]]}
            return model_answer({**evaluation, "issues": []})

        with patch("hackathon_review.generate", side_effect=provider):
            response = self.client.post("/api/analyze/gemini?operation=report", data=source.getvalue(),
                                        content_type="application/octet-stream",
                                        headers={"X-File-Name": "requirements.docx", "Accept": "application/json"})
        self.assertEqual(response.status_code, 200)
        audit = response.get_json()["review"]
        self.assertEqual(audit["document"], "Уведомления")
        self.assertEqual([row["source_id"] for row in audit["requirements"]], ["Ф-1", "Ф-2", None])
        self.assertTrue(any(item["kind"] == "table_header" for item in captured.values()))
        self.assertEqual([issue["engine"] for issue in audit["findings"]], ["Правило SanA1"])
        self.assertIn("Уведомления / Бизнес-правила / Приёмка",
                      audit["findings"][0]["evidence"][1]["section"])

    @patch.dict(os.environ, CONFIG)
    def test_cli_writes_russian_report_from_both_model_passes(self):
        with tempfile.TemporaryDirectory() as work:
            input_path = Path(work, "test.md")
            output_path = Path(work, "review.md")
            input_path.write_text(SPEC, encoding="utf-8")
            with patch("hackathon_review.generate", side_effect=[
                model_answer(individual()), model_answer(whole_set())
            ]) as generate, patch("sys.argv", ["app.py", "--input", str(input_path), "--output", str(output_path)]):
                self.assertEqual(main(), 0)
            self.assertEqual(generate.call_count, 2)
            report = output_path.read_text(encoding="utf-8")
            for section in ("Паспорт прогона", "Ф-1", "Проверка каждого требования",
                            "Проверка набора требований", "Вопрос автору", "Сводка",
                            "Блокирующих — 1", "L10", MODEL):
                self.assertIn(section, report)

    @patch.dict(os.environ, CONFIG)
    def test_provider_failure_keeps_previous_report_intact(self):
        with tempfile.TemporaryDirectory() as work:
            input_path = Path(work, "test.md")
            output_path = Path(work, "review.md")
            input_path.write_text(SPEC, encoding="utf-8")
            output_path.write_text("earlier review", encoding="utf-8")
            with (patch("hackathon_review.generate", side_effect=ValueError("gemini_busy")),
                  patch("hackathon_review.sleep")):
                with self.assertRaisesRegex(ValueError, "gemini_busy"):
                    review_file(input_path, output_path)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "earlier review")

    @patch.dict(os.environ, CONFIG | {"GEMINI_FALLBACK_MODEL": "gemini-fallback"})
    def test_fallback_is_reused_when_recovering_missing_requirements(self):
        fallback = "gemini-fallback"
        calls = []

        def provider(model, payload, timeout):
            data = json.loads(payload["contents"][0]["parts"][0]["text"])
            calls.append((model, data.get("required_refs")))
            if model == MODEL:
                raise ValueError("gemini_busy")
            if data.get("required_refs") == ["L4", "L10"]:
                return model_answer({"requirements": individual()["requirements"][:1]}, "gemini-fallback-001")
            if data.get("required_refs") == ["L10"]:
                return model_answer({"requirements": individual()["requirements"][1:]}, "gemini-fallback-001")
            return model_answer(whole_set(), "gemini-fallback-001")

        with patch("hackathon_review.generate", side_effect=provider), patch("hackathon_review.sleep"):
            response = self.client.post("/api/analyze/gemini?operation=report", data=SPEC.encode(),
                                        content_type="application/octet-stream",
                                        headers={"X-File-Name": "requirements.md", "Accept": "application/json"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [(MODEL, ["L4", "L10"]), (fallback, ["L4", "L10"]),
                                 (fallback, ["L10"]), (fallback, None)])
        audit = response.get_json()["review"]
        self.assertEqual(len(audit["requirements"]), 2)
        self.assertEqual([stage["model"] for stage in audit["passes"]], ["gemini-fallback-001"] * 3)

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-only", "GEMINI_MODEL": "gemini-primary",
                            "GEMINI_FALLBACK_MODEL": "gemini-secondary"})
    def test_temporary_provider_failure_retries_with_a_backoff(self):
        responses = [ValueError("gemini_busy"), ValueError("gemini_busy"),
                     model_answer(individual(), "gemini-primary"), model_answer(whole_set(), "gemini-primary")]
        with patch("hackathon_review.generate", side_effect=responses) as generate, patch("hackathon_review.sleep") as sleep:
            response = self.client.post("/api/analyze/gemini?operation=report", data=SPEC.encode(),
                                        content_type="application/octet-stream", headers={"X-File-Name": "test.md"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([values.args[0] for values in generate.call_args_list],
                         ["gemini-primary", "gemini-secondary", "gemini-primary", "gemini-primary"])
        self.assertEqual([values.args[0] for values in sleep.call_args_list], [1, 8])

    @patch.dict(os.environ, CONFIG)
    def test_later_batch_is_included_in_the_document_wide_check(self):
        document = "## Правило\nФ-1. Сервис проверяет настройки до сохранения.\n\n***\n\n"
        document += ("Служебный контекст. " * 700) + "\n\nФ-2. Сервис сохраняет только проверенные настройки."
        observed = {}

        def provider(model, payload, timeout):
            data = json.loads(payload["contents"][0]["parts"][0]["text"])
            if "required_refs" in data:
                rows = [item for item in data["blocks"] if item["source_id"]]
                return model_answer({"requirements": [
                    {"ref": item["ref"], "quote": item["text"], "summary": item["text"],
                     "assessment": "Проверка учитывает порядок обработки.", "issues": []} for item in rows
                ]})
            observed.update(data)
            evaluation = whole_set()
            for key in ("consistency", "completeness", "traceability", "feasibility"):
                evaluation[key] = {**SET_CHECK, "refs": ["L2"]}
            return model_answer({**evaluation, "issues": []})

        with patch("hackathon_review.generate", side_effect=provider):
            response = self.client.post("/api/analyze/gemini?operation=report", data=document.encode(),
                                        content_type="application/octet-stream",
                                        headers={"X-File-Name": "requirements.md", "Accept": "application/json"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["ref"] for item in observed["requirements"]], ["L2", "L8"])
        self.assertGreater(len(response.get_json()["review"]["passes"]), 2)

    @patch.dict(os.environ, CONFIG)
    def test_file_download_returns_same_russian_report_format(self):
        with patch("hackathon_review.generate", side_effect=[
            model_answer(individual()), model_answer(whole_set())
        ]):
            response = self.client.post("/api/analyze/gemini?operation=report", data=SPEC.encode(),
                                        content_type="application/octet-stream",
                                        headers={"X-File-Name": "requirements.md"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/markdown")
        self.assertIn("Вопрос автору", response.get_data(as_text=True))

    @patch.dict(os.environ, CONFIG)
    def test_web_preview_and_both_exports_have_the_same_evidence(self):
        with patch("hackathon_review.generate", side_effect=[
            model_answer(individual()), model_answer(whole_set())
        ]) as generate:
            response = self.client.post("/api/analyze/gemini?operation=report", data=SPEC.encode(),
                                        content_type="application/octet-stream",
                                        headers={"X-File-Name": "requirements.md", "Accept": "application/json"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(generate.call_count, 2)
        result = response.get_json()
        audit = result["review"]
        self.assertEqual(audit["schema_version"], 1)
        self.assertEqual(audit["mode"], "gemini")
        self.assertEqual(audit["readiness"], "blocked")
        self.assertEqual(audit["counts"]["blocker"], 1)
        issue = audit["findings"][0]
        self.assertEqual([source["line"] for source in issue["evidence"]], [4, 10])
        self.assertEqual(audit["requirements"][0]["findings"], [issue["id"]])
        self.assertEqual(issue["requirements"], ["REQ-001", "REQ-002"])
        self.assertEqual(render_review(audit), result["markdown"])

    @patch.dict(os.environ, CONFIG)
    def test_cli_can_write_structured_report(self):
        with tempfile.TemporaryDirectory() as work:
            input_path = Path(work, "test.md")
            output_path = Path(work, "review.json")
            input_path.write_text(SPEC, encoding="utf-8")
            with patch("hackathon_review.generate", side_effect=[
                model_answer(individual()), model_answer(whole_set())
            ]):
                review_file(input_path, output_path)
            review = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(review["requirements"][0]["source_id"], "Ф-1")
            self.assertEqual(review["passes"][0]["model"], MODEL)

    def test_report_exports_internal_reference_states_and_repeat_headings(self):
        source = (
            "# Payments\n\n"
            "## REQ-1 Notifications\nREQ-1. Send an alert after the transaction.\n\n"
            "## REQ-2 Limit\n\n"
            "## REQ-2 Limit\nREQ-2. Apply the limit once per transaction.\n\n"
            "## Flow\nREQ-3. See REQ-1, REQ-2 and REQ-9."
        )
        result = self.client.post("/api/analyze?operation=report", data=source.encode(),
                                  content_type="application/octet-stream", headers={
                                      "X-File-Name": "payments.md", "Accept": "application/json"}).get_json()
        links = {link["target"]: link for link in result["review"]["references"]}
        self.assertEqual({id: link["status"] for id, link in links.items()},
                         {"REQ-1": "resolved", "REQ-2": "ambiguous", "REQ-9": "missing"})
        self.assertEqual([target["line"] for target in links["REQ-1"]["declarations"]], [4])
        self.assertEqual([target["line"] for target in links["REQ-2"]["declarations"]], [6, 9])
        self.assertEqual([source["line"] for source in links["REQ-9"]["origins"]], [12])
        self.assertEqual(links["REQ-9"]["declarations"], [])
        self.assertIn("| REQ-9 | Пункт отсутствует | L12 | — |", result["markdown"])

    @patch.dict(os.environ, CONFIG)
    def test_pdf_review_ignores_page_number_and_marks_unread_pages(self):
        draft = individual("The service delivers an alert within 10 seconds.")
        draft["requirements"][0]["ref"] = "L1"
        draft["requirements"].pop()
        evaluation = {k: {**SET_CHECK, "refs": ["L1"]} for k in
                      ("consistency", "completeness", "traceability", "feasibility")}
        evaluation["issues"] = []
        with patch("hackathon_review.generate", side_effect=[
            model_answer(draft), model_answer(evaluation)
        ]):
            response = self.client.post("/api/analyze/gemini?operation=report", data=create_pdf(leading_number_only=True),
                                        content_type="application/octet-stream",
                                        headers={"X-File-Name": "requirements.pdf", "Accept": "application/json"})
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["review"]["pdf_coverage"], {"total": 2, "unread": [1]})
        self.assertEqual(result["review"]["readiness"], "clarify")
        self.assertIn("стр. 2 · L1 (извлечённый текст)", result["markdown"])
        self.assertIn("Страницы PDF без читаемого текста — 1.", result["markdown"])

    @patch.dict(os.environ, CONFIG)
    def test_invalid_pdf_never_calls_a_model(self):
        with patch("hackathon_review.generate") as generate:
            response = self.client.post("/api/analyze/gemini?operation=report", data=b"bad PDF",
                                        content_type="application/octet-stream",
                                        headers={"X-File-Name": "requirements.pdf"})
        generate.assert_not_called()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"], "invalid_document")


if __name__ == "__main__":
    unittest.main()
