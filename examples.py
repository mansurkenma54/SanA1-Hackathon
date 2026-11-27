"""Examples and an intentionally small, labeled local evaluation."""

from analyzer import analyze


EXAMPLES = {
    "en": """§1.1 The app supports transfers between domestic accounts.
§2.1 The maximum amount per transfer is 100 000 KZT.
§3.1 The app must display the transfer status quickly.
§4.3 The limit per transfer is 50 000 KZT.
§5.2 If there is no response, the app must retry the transfer request.
§6.1 The daily transfer limit is 200 000 KZT.""",
    "ru": """§1.1 Приложение поддерживает переводы между счетами внутри страны.
§2.1 Максимальная сумма на один перевод составляет 100 000 ₸.
§3.1 Приложение должно быстро показывать статус перевода.
§4.3 Лимит на один перевод составляет 50 000 ₸.
§5.2 Если ответ не поступил, приложение должно повторить запрос на перевод.
§6.1 Суточный лимит переводов составляет 200 000 ₸.""",
}

WORKSPACE_EXAMPLES = {
    "en": """# Domestic transfers
## Scope
§1.1 A customer can transfer money between two domestic accounts in KZT.
## Published limits
Clause | Requirement | Amount
§2.1 | Maximum amount per transfer | 100 000 KZT
§2.2 | Daily transfer limit | 250 000 KZT
## Processing sequence
Draft → Confirmed → Submitted → Settled
§3.1 The app must display the transfer status quickly.
§3.2 For a declined transfer, see §8.4.
## Operations handbook
§4.3 The limit per transfer is 50 000 KZT.
§4.4 The receipt retention period is TBD.
§5.2 If there is no response, the app must retry the transfer request.
§6.1 The customer may download a receipt after settlement.
§6.1 The operator may export a daily settlement register.""",
    "ru": """# Внутренние переводы
## Назначение
§1.1 Клиент может переводить деньги между двумя счетами внутри страны в тенге.
## Лимиты продукта
Пункт | Требование | Сумма
§2.1 | Максимальная сумма на один перевод | 100 000 ₸
§2.2 | Суточный лимит переводов | 250 000 ₸
## Обработка перевода
Черновик → Подтверждён → Отправлен → Исполнен
§3.1 Приложение должно быстро показывать статус перевода.
§3.2 При отклонении перевода см. §8.4.
## Операционный регламент
§4.3 Лимит на один перевод составляет 50 000 ₸.
§4.4 Срок хранения квитанции — [согласовать].
§5.2 Если ответ не поступил, приложение должно повторить запрос на перевод.
§6.1 Клиент может скачать квитанцию после исполнения перевода.
§6.1 Оператор может выгрузить реестр проведённых переводов за день.""",
}

AUDIT_DEMO = """# Отчёт по виртуальной карте

## Правила учёта покупок

Ф-1. Месяц определяется по дате покупки по времени Астаны. В отчёт входят завершённые покупки.

## Критерии приёмки

| Состояние | Действие | Результат |
| --- | --- | --- |
| Покупка 31 марта в 23:59 на 7 500 ₸ | Провести покупку 1 апреля в 00:05 | Апрельский счётчик расходов увеличивается на 7 500 ₸ |

## API изменения лимита виртуальной карты

### Метод

HTTP method: GET

### Выполнение

Ф-2. Обновить настройки виртуальной карты на основании параметров запроса.
"""

ADVANCED_LABELS = [("limit_conflict", (6, 13)), ("vague_requirement", (10,)), ("broken_reference", (11,)),
                   ("open_decision", (14,)), ("retry_behavior", (15,)), ("duplicate_clause", (16, 17))]

CASES = [
    ("advanced_en", WORKSPACE_EXAMPLES["en"], ADVANCED_LABELS),
    ("advanced_ru", WORKSPACE_EXAMPLES["ru"], ADVANCED_LABELS),
    ("forward_reference", "§1.1 For a refund see §4.2.\n§4.2 Return funds to the original account.", []),
    ("missing_ref", "§1.1 При отмене операции см. §7.3.", [("broken_reference", (1,))]),
    ("duplicate_number", "§2.1 Issue a paper receipt.\n§2.1 Store the receipt electronically.", [("duplicate_clause", (1, 2))]),
    ("open_value", "§1.1 Receipt retention period is TBD.", [("open_decision", (1,))]),
    ("sample_en", EXAMPLES["en"], [
        ("limit_conflict", (2, 4)), ("vague_requirement", (3,)), ("retry_behavior", (5,)),
    ]),
    ("sample_ru", EXAMPLES["ru"], [
        ("limit_conflict", (2, 4)), ("vague_requirement", (3,)), ("retry_behavior", (5,)),
    ]),
    ("different_period", "The transfer limit per day is 100 000 KZT.\n"
                         "The limit per transfer is 50 000 KZT.", []),
    ("different_channel", "The card payment limit per day is 50,000 KZT.\n"
                          "The wallet payment limit per day is 100,000 KZT.", []),
    ("different_eligibility", "The daily transfer limit for verified users is 100 000 KZT.\n"
                             "The daily transfer limit for unverified users is 50 000 KZT.", []),
    ("same_number", "The daily transfer limit is 100 000 KZT.\n"
                    "The daily transfer limit is ₸100,000.", []),
    ("different_bound", "The minimum transfer limit per transfer is 100 KZT.\n"
                         "The maximum transfer limit per transfer is 100,000 KZT.", []),
    ("different_customer", "The daily transfer limit for new customers is 50 000 KZT.\n"
                            "The daily transfer limit for returning customers is 100 000 KZT.", []),
    ("numbered_headings", "2.1. The limit per transfer is 48,000.50 KZT.\n\n"
                         "4.7. The limit per transfer is 48,000.75 KZT.", [
                             ("limit_conflict", (1, 3)),
                         ]),
    ("explicit_timing", "The app must display the transfer status quickly, within 2 seconds.", []),
    ("separate_retry_rule", "If there is no response, the app must retry the transfer request.\n"
                            "The transfer must use the same operation ID and debit the account only once.", []),
    ("unrelated_retry_rule", "If there is no response, the app must retry the transfer request.\n"
                              "The refund must use the same operation ID and run only once.", [
                                  ("retry_behavior", (1,)),
                              ]),
    ("retry_prohibited", "If there is no response, the app must not retry a transfer request.", []),
    ("retry_status_only", "If there is no response, the app must retry the transfer request.\n"
                          "For the same transfer ID, the status service returns the original status.", [
                              ("retry_behavior", (1,)),
                          ]),
    ("clean_ru", "Клиенту должен отображаться статус перевода в течение 2 секунд.\n"
                 "Лимит на один перевод составляет 50 000 ₸.\n"
                 "Суточный лимит переводов составляет 100 000 ₸.", []),
    ("unknown_scope", "The transfer limit is 25 000 KZT.\nThe transfer limit is 50 000 KZT.", []),
    ("vague_ru", "Система должна показывать статус платежа как можно скорее.", [
        ("vague_requirement", (1,)),
    ]),
]


def score_case(name, text, expected):
    expected = set(expected)
    findings = analyze(text)["findings"]
    actual = {(item["code"], tuple(ref["line"] for ref in item["evidence"])) for item in findings}
    quotes_match = all(text[ref["start"]:ref["end"]] == ref["quote"]
                       for item in findings for ref in item["evidence"])

    def labels(items):
        return [{"code": code, "lines": list(lines)} for code, lines in sorted(items)]

    return {"id": name, "fixture": text, "passed": expected == actual and quotes_match,
            "expected": len(expected), "detected": len(actual), "evidence_valid": quotes_match,
            "expected_findings": labels(expected), "detected_findings": labels(actual),
            "matched_findings": labels(actual & expected), "unexpected_findings": labels(actual - expected),
            "missed_findings": labels(expected - actual)}


def evaluation_events():
    cases = []
    matched = unexpected = missed = 0
    yield {"type": "stage", "step": "eval_cases", "count": len(CASES)}
    for name, text, expected in CASES:
        case = score_case(name, text, expected)
        matched += len(case["matched_findings"])
        unexpected += len(case["unexpected_findings"])
        missed += len(case["missed_findings"])
        cases.append(case)
        yield {"type": "progress", "completed": len(cases)}
    yield {"type": "stage", "step": "eval_metrics"}
    report = {
        "cases": cases, "passed": sum(case["passed"] for case in cases),
        "matched": matched, "unexpected": unexpected, "missed": missed,
        "precision": matched / (matched + unexpected) if matched + unexpected else None,
        "recall": matched / (matched + missed) if matched + missed else None,
    }
    yield {"type": "result", "report": report}


def evaluate():
    return next(event["report"] for event in evaluation_events() if event["type"] == "result")
