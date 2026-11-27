"""High-precision checks for arithmetic, wording, specifications and acceptance coverage."""

from decimal import Decimal
import re
from urllib.parse import urlsplit


NUMBER = re.compile(r"([−+-]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?)\s*(₸|KZT|тенге|тиын\w*|USD|EUR|%)?", re.I)
TOTAL = re.compile(r"^(?:итого|всего|общая сумма|grand total|total|sum)(?:\s*[,(/].*)?$", re.I)
NON_ADDITIVE = re.compile(r"\b(?:id|дата|date|номер|код|code|единица|unit|процент\w*|rate)\b|%", re.I)
LOCAL_DOC = re.compile(r"(?<!!)\[[^\]\n]+\]\((?![a-z][a-z\d+.-]*:|//)([^()\s]+\.(?:md|markdown|txt|pdf|docx))(?:#[^()\s]+)?\)", re.I)
MARKDOWN_HTTP = re.compile(r"\[[^\]\n]+\]\((https?:[^)\n]*)\)", re.I)
INCLUSIVE_RANGE = re.compile(r"от (?P<low>\d[\d \u00a0\u202f]*?) до (?P<high>\d[\d \u00a0\u202f]*?)\s*(?:₸|KZT|тенге)\s+включительно", re.I)
WORDING = re.compile(r"\b(?:удобно|над[её]жно|интуитивно|как правило|по возможности|при необходимости|"
                     r"subject to availability|when appropriate|as needed|user-friendly)\b|\bи т\.\s*д\.", re.I)
COMPARATIVE = re.compile(r"\b(?:быстрее|лучше|faster|better)\b", re.I)


def find(blocks, pattern):
    return next((block for block in blocks if re.search(pattern, block.text, re.I)), None)


def numeric(cell):
    match = NUMBER.fullmatch(cell.strip(" *`"))
    if not match:
        return None
    amount, unit = match.groups()
    unit = (unit or "").casefold()
    if unit in {"₸", "тенге"}:
        unit = "kzt"
    if unit.startswith("тиын"):
        unit = "tiyn"
    return Decimal("".join(amount.split()).replace("−", "-").replace(",", ".")), unit


def sum_case(parts, result):
    if len(parts) < 2 or result is None or any(part is None for part in parts):
        return None
    units = {unit for _, unit in [*parts, result] if unit}
    if len(units) > 1 or "%" in units:
        return None
    calculated = sum(value for value, _ in parts)
    return calculated if calculated != result[0] else None


def arithmetic_checks(blocks):
    header = previous = None
    data = []
    for block in blocks:
        if block.kind == "table_header":
            header, previous, data = block, block, []
            continue
        if (not header or block.kind != "table_row" or block.section != header.section
                or block.line != previous.end + (2 if previous is header else 1)):
            header = None
            continue
        previous = block
        raw_columns = re.split(r"(?<!\\)\|", block.text.strip().removeprefix("|").removesuffix("|"))
        if len(raw_columns) != len(header.cells):
            yield ("clarity", "major", [header, block],
                   "Число ячеек в строке не совпадает с заголовком таблицы.",
                   "В каком столбце пропущена или добавлена ячейка?",
                   "Выровнять ячейки по заголовку, оставив явное значение для неприменимого поля.")
            continue
        values = [numeric(cell) for cell in block.cells]
        if not values:
            continue
        if TOTAL.fullmatch(block.cells[0].strip(" *")):
            if len(data) > 15:
                continue
            for i, (label, value) in enumerate(zip(header.cells[1:], values[1:]), 1):
                if NON_ADDITIVE.search(label):
                    continue
                expected = sum_case([row[i] for _, row in data], value)
                if expected is not None:
                    name = label.strip(" *`")
                    yield ("consistency", "major", [header, *(row for row, _ in data), block],
                           f"Итог столбца «{name}» равен {value[0]}, сумма строк равна {expected}.",
                           f"Какой итог или исходные суммы должны быть записаны в столбце «{name}»?",
                           "Сверить исходные операции и пересчитать итог в указанной единице.")
            continue
        data.append((block, values))
        for i, label in enumerate(header.cells):
            if not TOTAL.fullmatch(label.strip(" *")):
                continue
            inputs = [value for j, (name, value) in enumerate(zip(header.cells, values))
                      if j != i and not NON_ADDITIVE.search(name) and not TOTAL.fullmatch(name.strip(" *"))
                      and (value is not None or re.search(r"сумм|сбор|fee|amount|charge|₸|KZT", name, re.I))]
            expected = sum_case(inputs, values[i])
            if expected is not None:
                yield ("consistency", "major", [header, block],
                       f"В строке указан итог {values[i][0]}, сумма её компонентов равна {expected}.",
                       "Какой итог или какие значения строки необходимо исправить?",
                       "Сверить компоненты и пересчитать итог этой строки.")


def wording_checks(blocks):
    for block in blocks:
        if block.kind not in {"paragraph", "text", "table_row"}:
            continue
        for target in dict.fromkeys(LOCAL_DOC.findall(block.text)):
            yield ("traceability", "major", [block],
                   f"Приложение «{target}» упомянуто ссылкой на файл, который не входит в загрузку.",
                   "Где находится действующая версия приложения?",
                   "Приложить текст зависимого документа или указать доступный адрес и версию.")
        for target in dict.fromkeys(MARKDOWN_HTTP.findall(block.text)):
            try:
                url = urlsplit(target)
                valid = bool(url.hostname and not re.search(r"\s", target) and url.port != 0)
            except ValueError:
                valid = False
            if not valid:
                yield ("traceability", "major", [block],
                       "В адресе ссылки отсутствует корректное имя узла или порт.",
                       "Какой адрес должен открываться по этой ссылке?",
                       "Исправить адрес и убедиться, что он открывается без входа.")
        if not (block.source_id or re.search(r"\b(?:долж\w*|обязан\w*|must|shall)\b", block.text, re.I)):
            continue
        text = re.sub(r'«[^»]*»|"[^"\n]*"|`[^`\n]*`', "", block.text)
        smell = WORDING.search(text)
        relative = COMPARATIVE.search(text)
        if relative and re.search(r"\b(?:чем|than)\b", text, re.I):
            relative = None
        if clue := smell or relative:
            yield ("verifiability", "minor", [block],
                   f"Выражение «{clue[0]}» не задаёт наблюдаемое условие приёмки.",
                   "Какое условие или измеримый результат заменит эту формулировку?",
                   "Назвать наблюдаемое действие, условия и ожидаемый результат.")


def capability_checks(blocks):
    clauses = [b for b in blocks if b.kind in {"paragraph", "text", "table_row"}]
    corpus = "\n".join(b.text for b in clauses)
    changed = find(clauses, r"изменени\w* порога.*ниже нового порога")
    if changed and not re.search(r"(?:уже|нов\w* порог).{0,55}(?:выше|равн|превыш|достиг)|(?:выше|равн\w*|превыш)\w*\s+нов\w* порог", corpus, re.I):
        yield ("completeness", "major", [changed],
               "После изменения порога описан только случай, когда текущие расходы ниже нового значения.",
               "Что делать, если накопленная сумма уже равна новому порогу или превышает его?",
               "Указать, отправляется ли уведомление сразу, с учётом месячного ограничения.")

    goal = find(clauses, r"узнать.{0,85}в момент покупки")
    queue = find(clauses, r"переда[её]т\w*\s+(?:push|уведомлен\w*)\s+на отправку\s+в течение")
    if goal and queue and goal != queue and not re.search(r"достав\w*\s+(?:в течение|не позднее)|получает.{0,70}в течение", corpus, re.I):
        yield ("verifiability", "major", [goal, queue],
               "Цель описывает момент получения клиентом. Лимит измеряет только передачу на отправку после события.",
               "Какой срок измеряется до получения push клиентом, при какой нагрузке и для какого процентиля?",
               "Определить измеряемые начало и конец, допустимую задержку и профиль нагрузки.")

    storage = find(clauses, r"сумм\w+ покупки в тиынах.{0,100}порог в тенге")
    if storage and not re.search(r"\b100\s+тиын|дел\w*\s+на 100|умнож\w*\s+на 100|перевод\w*.{0,30}тиын", corpus, re.I):
        yield ("completeness", "major", [storage],
               "Сумма покупки и порог хранятся в разных единицах, а правило сравнения и округления не задано.",
               "В какой единице сравнивать расход и порог и как учитывать дробную часть?",
               "Определить переход между тенге и тиынами и добавить тест на один тиын у границы.")
    flag = find(clauses, r"\|\s*`?enabled`?\s*\|.*признак включения")
    if storage and flag and not re.search(r"\benabled\b|признак включения|состояни\w* переключателя", storage.text, re.I):
        yield ("completeness", "major", [storage, flag],
               "API использует признак включения. Перечень хранимых данных указывает только признак отправки.",
               "Где хранится настройка enabled и как она отличается от признака отправки?",
               "Описать состояние переключателя в модели данных или сослаться на его владельца.")

    active = find(clauses, r"держатель активной карты KZT")
    owner = find(clauses, r"проверить принадлежность карты")
    if active and owner and not re.search(r"провер\w*.{0,40}(?:активност\w*|валют\w*)\s+карт", corpus, re.I):
        yield ("completeness", "major", [active, owner],
               "Для настройки нужна активная карта KZT. Описанная проверка принадлежности этого не подтверждает.",
               "Какие ответы должен вернуть API для неактивной карты и карты в другой валюте?",
               "Задать проверки статуса и валюты или указать, где они выполняются.")

    retry = find(clauses, r"повторная доставка.{0,100}событи\w+\s+процессинга")
    if retry and not re.search(r"\b(?:idempotency[-_ ]key|event[_ ]?id)\b|ключ\w*\s+(?:дедупликации|идемпотентности)", corpus, re.I):
        yield ("completeness", "major", [retry],
               "Повторная доставка не должна менять итог, но идентичность сообщений и контракт события не определены.",
               "По какому полю и в какой области уникальности распознавать повтор события процессинга?",
               "Описать схему события, ключ и срок дедупликации. Проверить повтор и параллельную доставку.")

    refund = find(clauses, r"возврат уменьшает расходы месяца исходной покупки")
    notice = find(clauses, r"максимум один.{0,25}(?:push|уведомлен)")
    if refund and notice and not re.search(r"возврат.{0,60}(?:после (?:push|уведомлен)|сбрасыва\w* признак|отрицательн)|после отправки.{0,60}возврат", corpus, re.I):
        yield ("completeness", "major", [refund, notice],
               "Правило привязывает возврат к исходной покупке и не описывает его влияние на уже отправленный push или возможный отрицательный итог.",
               "Что происходит со счётчиком и признаком отправки при возврате после уведомления?",
               "Задать поведение на позднем возврате, частичной сумме и повторном пересечении порога.")
    if refund and "проведённые покупки" in refund.text and not re.search(
            r"(?:холд|блокировк|предавторизац|авторизационн\w* удержан).{0,50}(?:учит|счётчик|расход)", corpus, re.I):
        yield ("clarity", "minor", [refund],
               "Указаны только проведённые покупки. Не определены промежуточное удержание, отмена и пересчёт иной валюты.",
               "В какой момент и по какой сумме учитывать холд, отмену и покупку в другой валюте?",
               "Описать статусы операции, момент пересчёта и источник курса для применимых операций.")
    push_data = find(clauses, r"передать последние четыре цифры карты")
    if push_data and not re.search(r"экран\w* блокировк|содержим\w+ push|логирован\w*.{0,55}маскиров|маскиров\w+.{0,35}журнал", corpus, re.I):
        yield ("clarity", "minor", [push_data],
               "Проверьте, достаточно ли ограничения полезной нагрузки последними четырьмя цифрами карты и суммой для канала push.",
               "Разрешено ли показывать эти данные на экране блокировки и записывать их в журнал доставки?",
               "Согласовать допустимые поля и видимость с владельцем ИБ.")


def api_document_checks(blocks):
    groups = {}
    for block in blocks:
        if re.search(r"(?:^| / )(?:request body|тело запроса)$", block.section, re.I):
            groups.setdefault(block.section, []).append(block)
    for related in groups.values():
        mime = find(related, r"content-type.+application/json")
        empty = find(related, r"тело не используется|no request body|body is not used")
        if mime and empty:
            yield ("clarity", "minor", list(dict.fromkeys([mime, empty])),
                   "В разделе тела запроса указан JSON Content-Type, хотя тело не используется.",
                   "Должен ли клиент передавать Content-Type для этого запроса без тела?",
                   "Указать условие для заголовка и отличить его от формата ответа.")

    for start in (i for i, b in enumerate(blocks) if b.kind == "heading" and re.search(r"^#+\s+ответ$", b.text, re.I)):
        endpoint = blocks[start].section.rsplit(" / ", 1)[0]
        related = [b for b in blocks[start:] if b.section == endpoint or b.section.startswith(endpoint + " / ")]
        success = find(related, r"результат 200 или 201")
        created = find(related, r"200\. Successful\s*[—–-]\s*Created")
        if success and created and not find(related, r"^#+\s*201\b|201[.:]\s*(?:Created|создан)"):
            yield ("clarity", "major", [success, created],
                   "Успех допускает 201 без отдельного контракта, а обозначение Created присвоено 200.",
                   "Когда возвращается 200, а когда 201, и какие поля получает клиент?",
                   "Определить успешные ветки и привести заголовки, статусы и примеры к одному контракту.")
        before = [b for b in blocks[:start] if b.section.startswith(endpoint + " / ")]
        request_type = find(before, r"^\|\s*`amount`\s*\|\s*integer\s*\|.*\blimit_kzt\b")
        response_type = find(related, r"^\|\s*`amount`\s*\|\s*string\s*\|.*\blimit_kzt\b")
        if request_type and response_type and not find(related, r"форматирован|преобразова|сериализа"):
            yield ("clarity", "minor", [request_type, response_type],
                   "Поле amount для одной настройки имеет разные типы в запросе и ответе. Правило сериализации не описано.",
                   "Проверьте, ожидается ли строка в ответе и в каком числовом формате она передаётся?",
                   "Указать формат сериализации либо использовать согласованный тип поля.")

    review_note = find(blocks, r"версия/дата.{0,35}не заполнен")
    if review_note:
        cited = [review_note]
        for check in (r"заполняются тестировщиками", r"\|\s*\|\s*\|\s*\|"):
            if entry := find(blocks, check):
                cited.append(entry)
        yield ("completeness", "major", cited,
               "Паспорт и отметки ревью явно оставлены незаполненными. По ним нельзя подтвердить готовность версии.",
               "Какая версия передана на ревью и кто подтверждает тестирование и согласование?",
               "Заполнить паспорт, назначить согласующих и зафиксировать решения о тестировании, откате и ИБ.")
        open_safety = [b for b in blocks if "чек-лист" in review_note.text.lower() and "Да / Нет" in b.text
                       and re.search(r"схем\w* отката|риск\w* информационной безопасности", b.text, re.I)]
        if open_safety:
            yield ("completeness", "major", [review_note, *open_safety],
                   "Чек-лист ставит вопросы об откате и рисках ИБ, а решения оставлены открытыми.",
                   "Как откатить изменение и какие меры ИБ согласовать перед выпуском?",
                   "Указать условия, ответственных и проверку отката. Оформить решение по данным и логированию.")

    acceptance = [b for b in blocks if b.kind == "table_header" and re.search(r"при[её]мк", b.section, re.I)]
    for header in acceptance:
        rows = [b for b in blocks if b.kind == "table_row" and b.section == header.section]
        if not rows or len(rows) > 20:
            continue
        corpus = "\n".join(b.text for b in rows)
        notice = find(blocks, r"максимум один.{0,30}(?:push|уведомлен)")
        changed = find(blocks, r"изменени\w* порога.*ниже нового порога")
        if notice and changed and not re.search(r"повтор|изменени\w*\s+порог|нов\w+ порог", corpus, re.I):
            yield ("traceability", "major", [notice, changed, header],
                   "В таблице приёмки есть обычная отправка, но нет проверки повторной отправки за месяц и смены порога.",
                   "Какие тесты приёмки должны подтвердить месячный лимит и изменение порога?",
                   "Связать критерии с ID требований и добавить возвраты, повторы и проверки обеих границ суммы.")
        refund = find(blocks, r"возврат уменьшает расходы месяца исходной покупки")
        retry = find(blocks, r"повторная доставка.{0,100}событи\w+\s+процессинга")
        absent = []
        if refund and not re.search(r"возврат", corpus, re.I):
            absent.append((refund, "возврат к исходной покупке"))
        if retry and not re.search(r"повтор|дубликат", corpus, re.I):
            absent.append((retry, "повтор события"))
        if absent:
            scenarios = ", ".join(label for _, label in absent)
            yield ("traceability", "major", [header, *(block for block, _ in absent)],
                   f"В таблице приёмки не указаны сценарии: {scenarios}.",
                   "Какие критерии приёмки подтверждают эти сценарии?",
                   "Добавить отдельный пример с начальным состоянием, действием и ожидаемым итогом для каждой указанной ветки.")
        limits = next((b for b in blocks if b.source_id and INCLUSIVE_RANGE.search(b.text)), None)
        values = {item[0] for item in re.findall(r"(?<!\d)(\d[\d \u00a0\u202f]*?)(\s*(?:₸|KZT|тенге))", corpus, re.I)}
        if limits and not all("".join(value.split()) in {"".join(item.split()) for item in values}
                              for value in INCLUSIVE_RANGE.search(limits.text).groups()):
            yield ("traceability", "minor", [limits, header],
                   "У диапазона есть явные границы, но таблица приёмки не проверяет верхнюю границу.",
                   "Какие граничные значения нужно принять или отклонить в приёмке?",
                   "Зафиксировать нижнюю, верхнюю и соседние недопустимые суммы.")


def quality_cases(blocks):
    yield from arithmetic_checks(blocks)
    yield from wording_checks(blocks)
    yield from capability_checks(blocks)
    yield from api_document_checks(blocks)
