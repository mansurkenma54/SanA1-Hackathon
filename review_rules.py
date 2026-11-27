"""Deterministic checks for relations between requirements and examples."""

from decimal import Decimal
import re

from analyzer import (REQUIREMENT, TIMED, clause_key, local_reference_targets,
                      money_limit_findings, open_decisions, retry_findings, sections_from)
from review_guidance import GUIDANCE
from quality_checks import quality_cases


MONTHS = re.compile(
    r"\b(?:январ[ьяе]|феврал[ьяе]|март[ае]?|апрел[ьяе]|ма[йяе]|июн[ьяе]|июл[ьяе]"
    r"|август[ае]?|сентябр[ьяе]|октябр[ьяе]|ноябр[ьяе]|декабр[ьяе])\b", re.I
)
NOTICE = r"\bpush\b|уведомлен"
PERIOD = r"месяц|сут[окки]+|недел|\bmonth\b|\bday\b"
BOUND_NUMBER = r"[-−]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?"
BOUND_UNIT = r"₸|тенге|KZT|мс|ms|секунд\w*|минут\w*|seconds?|minutes?|сут\w*|дн(?:ей|я)|days?|попыт\w*|attempts?|символ\w*|characters?"
REVERSED_LIMITS = re.compile(
    rf"(?:\bне менее|\bat least)\s+({BOUND_NUMBER})\s*({BOUND_UNIT})?\s*"
    rf"(?:,\s*(?:и\s+|and\s+)?|\s+(?:и|and)\s+)(?:не более|at most)\s+"
    rf"({BOUND_NUMBER})\s*({BOUND_UNIT})(?!\w)", re.I)


def bound_unit(unit):
    value = unit.casefold()
    if value.startswith(("сут", "дн", "day")):
        return "days"
    for prefix in ("секунд", "second", "минут", "minute", "попыт", "attempt", "символ", "character"):
        if value.startswith(prefix):
            return prefix
    return "kzt" if value in {"₸", "тенге", "kzt"} else "ms"


def quantity(value):
    return Decimal("".join(value.split()).replace("−", "-").replace(",", "."))
CODES = re.compile(r"\b(200|400|403|404)\b")
API_DETAIL_SECTION = re.compile(
    r"^(?:ответ(?:ы)?|статусы(?: ответа)?|коды (?:ошибок|ответов)|"
    r"запрос|параметры запроса|логика(?: работы метода)?|выполнение|(?:http )?метод|"
    r"responses?|status(?: codes)?|request(?: parameters)?|processing|"
    r"(?:http )?method|[1-5]\d{2}(?:\b.*)?)$", re.I
)
MISSING_AUTH = re.compile(
    r"(?:без\s+(?:необходимой\s+)?(?:авторизаци|аутентификаци)|"
    r"(?:при\s+)?отсутств(?:ии|ует)\b.{0,35}(?:сесси|токен|авторизаци|аутентификаци)|"
    r"(?:сесси\w*|токен\w*)\s+отсутств\w*)",
    re.I,
)
AUTH_STATUS_QUESTION = re.compile(r"(?:(?:http[- ]?)?статус|код\w*\s+ответа)", re.I)
AUTH_STATUS_SECTION = re.compile(r"(?:^| / )(?:статусы(?: ответа)?|коды (?:ошибок|ответов)|"
                                 r"status(?: codes)?)(?: / |$)", re.I)
AUTH_OTHER_DECISION = re.compile(
    r"исте[кч]|просроч|недейств|невалид|валидност|срок|сброс|проверки|"
    r"содержим|формат|тел[оа]\s+ответ|сообщени|обновлен|отзыв|владельц|\b403\b|\b404\b",
    re.I,
)
AUTH_OVERVIEW = re.compile(r"(?:^| / )(?:общие параметры|api overview|endpoint overview)$", re.I)
BEARER_DECLARATION = re.compile(
    r"^\|\s*\**(?:Authorization|Авторизаци[яи])\**\s*\|\s*Bearer(?:\s*,\s*сессия владельца карты)?\s*\|$",
    re.I,
)
BEARER_EXAMPLE_ROW = re.compile(r"^\|\s*\**curl\**\s*\|.*\bAuthorization:\s*Bearer\s+\S", re.I)
SECOND_AUTH_CHANNEL = re.compile(r"cookie|кук[аи]|x-session|\bsession[-_ ]?id\b|идентификатор\w*\s+сессии", re.I)
MONTHLY_NOTICE_CAP = r"(?:один|одно|1)\s+(?:тако(?:й|е)\s+)?(?:push\b|уведомлени[ея])\s+(?:за|в)\s+(?:календарн\w+\s+)?месяц\b"
CARD_NOTICE_SCOPE_QUESTION = re.compile(
    rf"(?:распространяется|применяется|действует)\s+ли\s+(?:ограничение|лимит)\s+"
    rf"«?(?:максимум|не\s+более|в)\s+{MONTHLY_NOTICE_CAP}»?\s+"
    r"на\s+каждую\s+карту(?:\s+отдельно)?\s+или\s+на\s+"
    r"(?:(?:весь\s+)?договор(?:\s+клиента)?|клиента(?:\s+в\s+целом)?)\?", re.I,
)
CARD_NOTICE_CAP = re.compile(
    rf"(?:^|[.!?]\**\s+)на\s+(?:каждую\s+)?карту\s+приходится\s+"
    rf"(?:максимум|не\s+более)\s+{MONTHLY_NOTICE_CAP}(?:\*\*)?(?:\.|$)",
    re.I,
)
CUSTOMER_NOTICE_SCOPE = re.compile(
    r"\b(?:на|для|по)\s+(?:(?:весь|всего|одного|каждого)\s+)?(?:клиент[ау]|договор[ау]?)\b", re.I,
)
ACCEPTANCE_SECTION = re.compile(r"при[её]мк|acceptance", re.I)
ACCEPTANCE_COLUMNS = {
    "исходное состояние": {"исходные условия", "исходное состояние", "состояние", "предусловия",
                           "initial state", "initial conditions", "preconditions", "given"},
    "действие": {"действие", "шаг", "action", "step", "when"},
    "ожидаемый результат": {"ожидаемый результат", "результат", "итог", "expected result",
                            "expected outcome", "then"},
}
KZT_INTEGER = r"(\d{1,3}(?:[ \u00a0\u202f]\d{3}){1,4}|\d{1,15})\s*(?:₸|KZT\b|тенге\b)"
REFUND_CAP = re.compile(
    rf"(?:максимальная сумма|лимит) на один возврат(?: составляет)?\s+{KZT_INTEGER}(?:\.|$)", re.I,
)
REFUND_BALANCE = re.compile(rf"покупка (?:на )?{KZT_INTEGER} без (?:прежних|предыдущих) возвратов\.?$", re.I)
REFUND_REQUEST = re.compile(rf"запросить один возврат на {KZT_INTEGER}\.?$", re.I)
REFUND_CAP_REJECTION = re.compile(r"заявка отклонена по лимиту одного возврата\.?$", re.I)
REFUND_CAP_ACCEPTANCE = re.compile(r"заявка принята\.\s+", re.I)
REFUND_LIMIT_QUESTION = "Какой лимит на один возврат действует для сценария приёмки?"
REFUND_REJECTION_QUESTION = re.compile(
    r"\b(?:лимит\w*|максимальн\w+\s+(?:сумм\w*|ограничени\w*)|правило лимита)\b", re.I,
)
REFUND_EXAMPLE_SCOPE = re.compile(
    r"\bв (?:тестовом примере|(?:примере|сценарии|таблице)(?: при[её]мки)?)\b|\bпри покупке\b", re.I,
)
REFUND_ASKED_AMOUNT = re.compile(rf"\b(?:запроса|возврата) на {KZT_INTEGER}", re.I)
REFUND_REJECTION_OTHER_DECISION = re.compile(
    r"\b(?:HTTP|код\w*|статус\w*|тел[оа]|одновременно|если|валют\w*|округлен\w*)\b", re.I,
)
REFUND_CHECK_ORDER = re.compile(r"\b(?:перв\w*|сначала|поряд\w*|очер[её]д\w*)\b", re.I)
REFUND_CAP_EXCEPTION = re.compile(r"\b(?:кроме|исключени\w*|если|при условии)\b", re.I)
TIMING_SMELL = re.compile(
    r"\b(?:quickly|promptly|as soon as possible|within a reasonable time|"
    r"быстро|оперативно|незамедлительно|как можно скорее|в разумный срок)\b", re.I
)
TIMING_QUOTED = re.compile(r'«[^»\n]*»|“[^”\n]*”|"[^"\n]*"')
TIMING_NEGATED = re.compile(r"\b(?:не|not)\s+(?:обязательно\s+|necessarily\s+)?$", re.I)
TIMING_TRIGGER = re.compile(r"\b(?:после|с момента|при поступлении|after|from the moment)\s+\w", re.I)
TIMING_QUESTION = "Какой предельный срок допустим"
TIMING_WORDING = re.compile(r"\b(?:удали\w*|убра\w*|исключи\w*)\s+(?:ли\s+)?(?:слов\w*|термин\w*|выражени\w*)", re.I)
WORD_DURATION = re.compile(
    r"(?:\bwithin\s+(?:an?|one)\s+(?:second|minute|hour)\b|"
    r"\bв течение\s+(?:одной\s+|одного\s+)?(?:секунды|минуты|часа)\b)", re.I
)
TIMING_REF = re.compile(
    r"\b(?:срок\w*|время ответа|задержк\w*|response time|time limit|latency)\s*"
    r"(?:[:—–-]\s*)?(?:см\.\s*|согласно\s+|по\s+|see\s+|per\s+)"
    r"([a-zа-яё]{1,12}[-–_]\d+(?:[.-]\d+)*)(?![\w-]|\.\d)", re.I
)
SENTENCE_BREAK = re.compile(r"(?<!\bсм\.)(?<=[.!?])\s+|\n", re.I)
FROZEN_REFUND_QUESTION = "Зачислять возврат на замороженный счёт в установленный срок или ждать снятия заморозки?"
REFUND_ON_FROZEN_ACCOUNT = re.compile(r"замороженн\w*\s+сч[её]т|заморозк\w*\s+сч[её]т|сняти\w*\s+заморозк", re.I)
REFUND_CREDIT = re.compile(r"\bзачисля(?:ет|ть|ется)\b.{0,80}\bвозврат\w*", re.I)
FROZEN_CREDIT_SCOPE = re.compile(
    r"\b(?:это\s+правило|указанный\s+срок)\s+(?:также\s+)?(?:применяется|действует)\s+"
    r"(?:(?:также|и)\s+)?(?:к|для|на)\s+замороженн\w*\s+сч[её]т", re.I,
)
REFUND_HELD = re.compile(
    r"\bвозврат\w*(?:\s+(?:карточной\s+)?покупки)?\s+не\s+зачисляется\s+до\s+снятия\s+заморозки",
    re.I,
)


def matches(blocks, pattern):
    return next((block for block in blocks if re.search(pattern, block.text, re.I)), None)


def finding(criterion, severity, blocks, explanation, question, next_step):
    return {"criterion": criterion, "severity": severity,
            "refs": [block.ref for block in blocks], "explanation": explanation,
            "question": question, "next_step": next_step}


def month_prefix(date):
    word = date[0].casefold()
    return r"ма[йяе]" if word in {"май", "мая", "мае"} else word[:3]


def calendar_review(blocks):
    rule = matches(blocks, r"месяц\w*\s+(?:определя\w*|счита\w*)\s+по\s+дате\s+(?:совершения\s+)?(?:покупки|операции)")
    if not rule:
        return None
    for row in blocks:
        if row.kind != "table_row":
            continue
        columns = row.text.strip("|").split("|")
        if len(columns) != 3 or not re.search(r"сч[её]тчик|расход|уч[её]т", columns[-1], re.I):
            continue
        dates = [MONTHS.search(column) for column in columns[:2]]
        if not all(dates) or not re.search(r"покупк|операци", columns[0], re.I):
            continue
        purchase, posting = map(month_prefix, dates)
        if purchase != posting and re.search(rf"\b{posting}\w*", columns[-1], re.I):
            return finding(
                "consistency", "blocker", [rule, row],
                "Общее правило относит расход к дате покупки, но пример приёмки увеличивает счётчик другого месяца по дате проведения. "
                "До согласования нельзя выбрать месяц для агрегации и зафиксировать ожидаемый счётчик в граничном тесте.",
                "В какой месяц входит покупка, совершённая в одном месяце и проведённая в следующем?",
                "Согласовать основание для выбора месяца и синхронизировать правило с граничным примером приёмки.",
            )
    return None


def acceptance_rows(blocks):
    """Yield typed acceptance rows with their header and column positions."""
    header = None
    previous = None
    columns = {}
    for block in blocks:
        if block.kind == "table_header":
            header = None
            if ACCEPTANCE_SECTION.search(block.section):
                labels = [" ".join(cell.strip(" *_\x60").casefold().split()) for cell in block.cells]
                columns = {role: index for role, names in ACCEPTANCE_COLUMNS.items()
                           for index, label in enumerate(labels) if label in names}
                if len(columns) == len(ACCEPTANCE_COLUMNS):
                    header = block
        elif header and block.kind == "table_row" and block.section == header.section:
            first_row = previous is header
            if block.line != previous.end + (2 if first_row else 1):
                header = None
            elif any(block.cells):
                yield header, block, columns
        else:
            header = None
        previous = block


def acceptance_review(blocks):
    """Check explicitly structured scenarios and cite the original header and row."""
    for header, block, columns in acceptance_rows(blocks):
        missing = [role for role, index in columns.items()
                   if index >= len(block.cells) or not block.cells[index].strip()]
        if missing:
            yield finding(
                "verifiability", "major", [header, block],
                "В строке приёмки остались пустые поля — " + ", ".join(missing) + ".",
                "Что указать в этой строке приёмки для полей «" + "», «".join(missing) + "»?",
                "Заполнить пустые ячейки и согласовать воспроизводимый сценарий проверки.",
            )


def stated_refund_cap(block):
    if block.kind != "paragraph" or REFUND_CAP_EXCEPTION.search(block.text):
        return None
    cap = REFUND_CAP.match(sections_from(block.text)[0]["content"])
    return int("".join(cap[1].split())) if cap else None


def refund_scenario(row, columns):
    if max(columns.values()) >= len(row.cells):
        return None
    balance = REFUND_BALANCE.fullmatch(row.cells[columns["исходное состояние"]])
    request = REFUND_REQUEST.fullmatch(row.cells[columns["действие"]])
    if balance and request:
        return (int("".join(balance[1].split())), int("".join(request[1].split())),
                row.cells[columns["ожидаемый результат"]])
    return None


def refund_cap_review(blocks):
    caps = [(block, amount) for block in blocks if (amount := stated_refund_cap(block)) is not None]
    if len(caps) != 1:
        return
    rule, limit = caps[0]
    for _, row, columns in acceptance_rows(blocks):
        if not (scenario := refund_scenario(row, columns)):
            continue
        balance, requested, expected = scenario
        accepted = REFUND_CAP_ACCEPTANCE.match(expected)
        example_cap = REFUND_CAP.fullmatch(expected[accepted.end():]) if accepted else None
        if not example_cap:
            continue
        expected_limit = int("".join(example_cap[1].split()))
        if 0 < limit < requested <= min(balance, expected_limit):
            yield finding(
                "consistency", "blocker", [rule, row],
                f"Требование задаёт лимит {limit} ₸, а приёмочный пример принимает запрос и задаёт лимит {expected_limit} ₸. "
                "Разработчик и тестировщик получат разные ожидаемые результаты.",
                REFUND_LIMIT_QUESTION,
                "Подтвердить один лимит на операцию и привести результат примера в соответствие с ним.",
            )


def documented_refund_outcome(question, explanation, blocks, sources):
    """Check the reason for a specific rejection using the cited rule and acceptance row."""
    question = " ".join(question.split())
    decision_text = question + " " + " ".join(explanation.split())
    if (len(sources) != 2 or question.count("?") != 1 or not REFUND_REJECTION_QUESTION.search(question)
            or not REFUND_EXAMPLE_SCOPE.search(decision_text) or REFUND_REJECTION_OTHER_DECISION.search(question)
            or not re.search(r"отклон|отказ|применя|противореч", decision_text, re.I)):
        return None
    limit = next((value for source in sources if (value := stated_refund_cap(source)) is not None), None)
    if limit is None:
        return None
    for _, row, columns in acceptance_rows(blocks):
        if row not in sources or not (scenario := refund_scenario(row, columns)):
            continue
        available, requested, expected = scenario
        if not REFUND_CAP_REJECTION.fullmatch(expected):
            return None
        asked = REFUND_ASKED_AMOUNT.search(question)
        if asked and int("".join(asked[1].split())) != requested:
            return None
        stated_amounts = {int("".join(match[1].split())) for match in re.finditer(KZT_INTEGER, decision_text, re.I)}
        if stated_amounts <= {requested, available, limit} and 0 < limit < requested <= available:
            return "order" if REFUND_CHECK_ORDER.search(question) else "rejection"
    return None


def requirement_index(blocks):
    by_id = {}
    for block in blocks:
        if block.kind in {"heading", "paragraph", "text", "table_row"} and block.source_id:
            by_id.setdefault(clause_key(block.source_id), []).append(block)
    for key, entries in by_id.items():
        headings = {}
        aliases = set()
        for block in entries:
            if block.kind == "heading":
                headings[block.section] = block.ref
            elif block.section in headings:
                aliases.add(headings.pop(block.section))
        by_id[key] = [block for block in entries if block.ref not in aliases]
    return by_id


def internal_references(blocks):
    """Group explicit references to the same clause, once per source block."""
    links = {}
    for block in blocks:
        if block.kind not in {"paragraph", "text", "table_row"}:
            continue
        values = [*local_reference_targets(block.text), *block.acceptance_references]
        targets = {clause_key(target): target for target in values}
        for key, target in targets.items():
            _, origins = links.setdefault(key, (target, []))
            origins.append(block)
    return links


def reference_review(blocks, by_id):
    references = internal_references(blocks)
    missing = {}
    for key, (label, origins) in references.items():
        if key not in by_id:
            for block in origins:
                missing.setdefault(block, []).append(label)
    for block in blocks:
        if block in missing:
            targets = ", ".join(missing[block])
            yield finding(
                "traceability", "major", [block],
                f"В документе нет пунктов, указанных во внутренней ссылке — {targets}.",
                f"На какие существующие пункты должна вести ссылка «{targets}»?",
                "Указать существующие идентификаторы или добавить недостающие пункты.",
            )
    for key, declarations in by_id.items():
        if len(declarations) > 1:
            source_id = declarations[0].source_id
            origins = references.get(key, (None, []))[1]
            evidence = list(dict.fromkeys([*declarations, *origins]))
            yield finding(
                "traceability", "major", evidence,
                f"Идентификатор {source_id} объявлен несколько раз. Ссылка на него неоднозначна.",
                f"Какой пункт должен сохранять идентификатор {source_id}?",
                "Назначить остальным пунктам отдельные идентификаторы и обновить ссылки.",
            )


def resolved_timing_reference(reference, block, by_id):
    if reference:
        candidates = by_id.get(clause_key(reference[1]), [])
        if len(candidates) == 1 and candidates[0] is not block:
            target = TIMING_QUOTED.sub(" ", candidates[0].text)
            if TIMED.search(target) or WORD_DURATION.search(target):
                return candidates[0]
    return None


def timing_review(blocks, by_id):
    """Find unmeasurable timing in obligations, with explicit timing references as context."""
    for block in blocks:
        if block.kind not in {"paragraph", "text", "table_row"}:
            continue
        if not block.source_id and not REQUIREMENT.search(block.text):
            continue
        sentences = SENTENCE_BREAK.split(TIMING_QUOTED.sub(" ", block.text))
        for index, sentence in enumerate(sentences):
            term = next((match for match in TIMING_SMELL.finditer(sentence)
                         if not TIMING_NEGATED.search(sentence[:match.start()])), None)
            if not term or TIMED.search(sentence) or WORD_DURATION.search(sentence):
                continue
            reference = TIMING_REF.search(sentence)
            if not reference and index + 1 < len(sentences):
                reference = TIMING_REF.match(sentences[index + 1])
            if resolved_timing_reference(reference, block, by_id):
                continue
            trigger = TIMING_TRIGGER.search(sentence)
            yield finding(
                "verifiability", "major", [block],
                f"Выражение «{term[0]}» оставляет срок без измеримой границы.",
                TIMING_QUESTION + (" после указанного события?" if trigger
                                   else " и с какого события начинать отсчёт?"),
                ("Добавить предельное время с единицей измерения." if trigger
                 else "Добавить предельное время с единицей измерения и событие, запускающее отсчёт."),
            )
            break


def repeat_notice_review(blocks):
    cap = matches(blocks, rf"(?:максимум|не более)\s+од[иное]+\s+(?:\w+\s+)?(?:{NOTICE}).*(?:{PERIOD})")
    changed = matches(
        blocks, rf"(?:изменении|смене)\s+(?:\w+\s+)?(?:порога|лимита).*(?:{NOTICE}).*независимо\s+от\s+истории")
    if not cap or not changed or cap == changed:
        return None
    return finding(
        "consistency", "blocker", [cap, changed],
        "Лимит на одно уведомление за период пересекается с правилом отправки после изменения порога независимо от истории. "
        "Разработчику нужно выбрать, сохраняется ли признак уже отправленного уведомления, а тесту — ожидать ноль или один новый push.",
        "Если уведомление уже отправлено в этом периоде, будет ли оно отправлено второй раз после изменения порога и его достижения? "
        "A — новое уведомление не отправляется, действует лимит. B — отправляется ещё одно, изменение порога является исключением.",
        "Согласовать приоритет правил и включить отдельный сценарий приёмки для изменения порога после уведомления.",
    )


def frozen_refund_review(blocks):
    """Compare an explicit credit rule and a freeze hold in the same section."""
    requirements = [block for block in blocks if block.source_id and block.kind != "heading"]
    for held in requirements:
        if not REFUND_HELD.search(held.text):
            continue
        credit = next((block for block in requirements if block != held and
                       (block.section == held.section or
                        block.section and held.section.startswith(block.section + " / "))
                       and REFUND_CREDIT.search(block.text) and FROZEN_CREDIT_SCOPE.search(block.text)
                       and not REFUND_HELD.search(block.text)), None)
        if credit:
            return finding(
                "consistency", "blocker", [credit, held],
                "Один пункт требует зачислить возврат на замороженный счёт, другой — ждать снятия заморозки. "
                "Нельзя определить, должен ли обработчик изменить баланс до снятия заморозки, "
                "и зафиксировать это в приёмочном тесте.",
                FROZEN_REFUND_QUESTION,
                "Согласовать приоритет правил и указать единый ожидаемый баланс для замороженного счёта.",
            )
    return None


def read_and_save_review(blocks):
    requirement = matches(blocks, r"чита[еют]+\s+и\s+сохраня[еют]+\s+настройк")
    operation = matches(blocks, r"сохранение\s+(?:порога|лимита|настроек).*чтение\s+(?:порога|лимита|настроек)")
    writing = matches(blocks, r"(?:заменить|изменить|обновить)\s+настройк")
    reading = matches(blocks, r"\/[\w/-]*(?:getlimit|readlimit|readsettings|getsettings)\b")
    if not requirement or not operation or not writing or reading:
        return None
    return finding(
        "completeness", "major", [requirement, operation, writing],
        "Интеграция должна читать и сохранять настройки. Спецификация смешивает назначение операций и описывает изменение состояния, но не задаёт контракт чтения.",
        "Каким методом приложение читает текущие настройки и в каком виде получает сохранённые значения?",
        "Явно выделить операцию чтения с её параметрами, результатом и гарантией отсутствия изменения настройки.",
    )


def api_contract(section):
    parts = section.split(" / ") if section else []
    for index, part in enumerate(parts):
        if API_DETAIL_SECTION.fullmatch(part):
            return " / ".join(parts[:index])
    return None


def http_response_review(blocks, all_blocks, contract):
    success = matches(blocks, r"200\b[^.\n]{0,12}\.?\*{0,2}.{0,45}успеш|200\s+или\s+201\s*[—–-]\s*успеш")
    bad_request = matches(blocks, r"\b400\b.*параметры\s+запроса.*неверно")
    error_example = next((block for block in blocks
                          if block.kind == "example" and re.search(r"\b200\b", block.section)
                          and re.search(r'"\w+"\s*:\s*"ERROR"', block.text, re.I)), None)
    if not success or not bad_request or not error_example:
        return None
    evidence = [success, bad_request, error_example]
    if contract and error_example.section.startswith(bad_request.section + " / "):
        rejection = matches(
            (block for block in all_blocks
             if block.section.rpartition(" / ")[0] == contract or block.section == contract),
            r"при\s+отклонении\s+(?:суммы|параметра).*\bERROR\b",
        )
        if rejection and rejection not in evidence:
            evidence.append(rejection)
    return finding(
        "consistency", "blocker", evidence,
        "Отклонённый ввод описан как ошибка 400, но в примерах под HTTP 200 указан ERROR для неверного значения. "
        "До согласования клиент не может выбрать ветку обработки, а контрактный тест не может закрепить ожидаемые статус и тело ответа.",
        "Какой HTTP-статус и какое тело получает клиент при недопустимом значении суммы или другого параметра?",
        "Выбрать одну схему ошибки валидации и согласовать таблицу кодов с образцом JSON.",
    )


def http_get_write_review(blocks):
    declaration = r"(?:REST\s+type|HTTP[- ]метод|HTTP\s+method)\W+"
    methods = [block for block in blocks if re.search(declaration, block.text, re.I)]
    for method in methods:
        if not re.search(declaration + r"GET\b", method.text, re.I):
            continue
        parent = api_contract(method.section) or method.section.rpartition(" / ")[0]
        if not parent:
            continue
        related = [block for block in blocks if block.section == parent or block.section.startswith(parent + " / ")]
        if sum(block in methods for block in related) != 1:
            continue
        writes = matches(related, r"(?:заменить|изменить|обновить|сохранить)\s+(?:текущ\w*\s+)?настройк")
        if writes:
            yield finding(
                "design", "major", [method, writes],
                "Контракт назначает GET операции, которая изменяет настройки. "
                "По RFC 9110 GET следует безопасной семантике, поэтому клиенты могут повторять или предварительно выполнять его как чтение.",
                "Какой отдельный метод должен изменять настройки и какой запрос только читает их?",
                "Разделить чтение и изменение состояния в контракте и согласовать повтор запроса на сохранение.",
            )
            continue
        creates_refund = matches(
            related, r"\b(?:метод|операция|запрос|сервис)\s+созда[её]т\s+заявку\s+на\s+возврат\b")
        if creates_refund:
            yield finding(
                "design", "major", [method, creates_refund],
                "Контракт назначает GET операции, которая создаёт заявку на возврат. "
                "Клиент может повторить или предварительно выполнить GET как чтение, хотя запрос изменяет состояние.",
                "Каким HTTP-методом следует создавать заявку на возврат?",
                "Согласовать отдельный метод создания заявки и проверить повтор запроса с тем же ключом.",
            )


def access_review(blocks):
    generic_denial = matches(blocks, r"\b403\b.*доступ\s+запрещ[её]н")
    exception = next((block for block in blocks if "403" in CODES.findall(block.section)
                      and re.search(r"\b404\b.*(?:отсутствующ|не найден)|(?:чужой|другого владельца).*\b404\b",
                                    block.text, re.I)), None)
    if not generic_denial or not exception:
        return None
    return finding(
        "clarity", "major", [generic_denial, exception],
        "Общее описание отказа содержит 403, тогда как специальный абзац внутри раздела 403 задаёт 404. Правило для чужой карты есть, а область применения 403 нуждается в границе.",
        "Для каких отказов API возвращает 403, если чужая и отсутствующая карта уже возвращают 404?",
        "Разнести правила 403 и 404 и добавить тесты для разных причин отказа, сохранив явно заявленное поведение для чужой карты.",
    )


def webhook_ack_review(blocks):
    for handler, retry in zip(blocks, blocks[1:]):
        if (handler.section != retry.section or handler.kind not in {"paragraph", "text"}
                or retry.kind not in {"paragraph", "text"}
                or not re.search(r"\b(?:событи[яе]|вебхук\w*)\s+POST\s+/\S+", handler.text, re.I)):
            continue
        ack = re.search(r"\bпри успешн\w+ обработк\w+ (?:сервис )?отвечает HTTP (2\d{2})\b", handler.text, re.I)
        stop = re.search(r"\bповторная доставка прекращается после HTTP (2\d{2})\.\s+"
                         r"любой другой статус запускает повтор", retry.text, re.I)
        if ack and stop and ack[1] != stop[1]:
            yield finding(
                "consistency", "major", [handler, retry],
                f"Обработчик подтверждает событие через HTTP {ack[1]}, а отправитель прекращает повтор только после "
                f"HTTP {stop[1]}. Успешная обработка вызовет повторную доставку.",
                f"Какой HTTP-статус подтверждает обработку вебхука и прекращает повторную доставку — {ack[1]} или {stop[1]}?",
                "Согласовать один статус подтверждения и проверить, что после него повторная доставка не запускается.",
            )


def operational_review(blocks):
    sections = []
    source_by_line = {}
    for block in blocks:
        if block.kind not in {"text", "paragraph", "table_row"}:
            continue
        for section in sections_from(block.text, first_line=block.line):
            sections.append(section)
            source_by_line[section["line"]] = block

    for detect, criterion, severity in (
        (money_limit_findings, "consistency", "blocker"),
        (retry_findings, "completeness", "major"),
        (open_decisions, "completeness", "major"),
    ):
        for item in detect(sections):
            sources = list(dict.fromkeys(source_by_line[ref["line"]] for ref in item["evidence"]))
            guidance = GUIDANCE["ru"][item["code"]]
            explanation = guidance["description"]
            if item["code"] == "limit_conflict":
                amounts = ", ".join(item["values"]["amounts"])
                explanation += (f" Указанные суммы — {amounts} {item['values']['currency']}. "
                                "Нельзя выбрать порог отказа и зафиксировать результат для операции между указанными суммами.")
            elif item["code"] == "open_decision":
                explanation += " Пометка — " + ", ".join(item["values"]["markers"]) + "."
            yield finding(criterion, severity, sources, explanation, guidance["question"], guidance["recommendation"])


def rule_findings(blocks):
    issues = [issue for check in (calendar_review, repeat_notice_review, frozen_refund_review, read_and_save_review)
              if (issue := check(blocks)) is not None]
    issues.extend(acceptance_review(blocks))
    issues.extend(refund_cap_review(blocks))
    by_id = requirement_index(blocks)
    issues.extend(reference_review(blocks, by_id))
    issues.extend(timing_review(blocks, by_id))
    issues.extend(http_get_write_review(blocks))
    issues.extend(webhook_ack_review(blocks))
    issues.extend(operational_review(blocks))
    for block in blocks:
        if block.kind not in {"paragraph", "text", "table_row"}:
            continue
        for match in REVERSED_LIMITS.finditer(block.text):
            minimum, lower_unit, maximum, upper_unit = match.groups()
            if lower_unit and bound_unit(lower_unit) != bound_unit(upper_unit):
                continue
            if quantity(minimum) <= quantity(maximum):
                continue
            issues.append(finding(
                "consistency", "blocker", [block],
                f"Нижняя граница ({minimum} {lower_unit or upper_unit}) выше верхней ({maximum} {upper_unit}). "
                "Ни одно значение не удовлетворяет условию.",
                "Какие минимальное и максимальное значения должны пройти приёмку?",
                "Указать согласованный диапазон и проверять обе границы в приёмочных тестах.",
            ))
            break
    contracts = {}
    for block in blocks:
        contract = api_contract(block.section)
        contracts.setdefault(block.section if contract is None else contract, []).append(block)
    for contract, related in contracts.items():
        for issue in (http_response_review(related, blocks, contract), access_review(related)):
            if issue is not None:
                issues.append(issue)
    issues.extend(finding(*case) for case in quality_cases(blocks))
    return issues


def documented_auth_status(question, blocks):
    if (question.count("?") != 1 or not AUTH_STATUS_QUESTION.search(question)
            or not MISSING_AUTH.search(question) or AUTH_OTHER_DECISION.search(question)):
        return None
    answers = []
    for block in blocks:
        if block.kind not in {"paragraph", "table_row", "text"} or not AUTH_STATUS_SECTION.search(block.section):
            continue
        for line in block.text.splitlines():
            if MISSING_AUTH.search(line):
                codes = re.findall(r"\b[1-5]\d{2}\b", line)
                if codes:
                    answers.append((tuple(codes), block))
    if answers and all(codes == ("401",) for codes, _ in answers):
        return answers[0][1]
    return None


def documented_bearer_channel(question, blocks, sources):
    """Resolve an assumed second channel only when the contract demonstrates one channel."""
    if (len(sources) != 1 or question.count("?") != 1 or SECOND_AUTH_CHANNEL.search(question)
            or re.search(r"как\w*\s+провер|связ\w*|валидн|срок|исте[кч]|\bи\s+как\b", question, re.I)
            or not re.search(r"переда\w*.*сесси.*(?:помимо|кроме).*\bAuthorization\b.*\bBearer\b", question, re.I)):
        return None
    declaration = sources[0]
    if (declaration.kind != "table_row" or not AUTH_OVERVIEW.search(declaration.section)
            or not BEARER_DECLARATION.fullmatch(declaration.text)):
        return None
    scope = declaration.section.rpartition(" / ")[0]
    if not scope or any(SECOND_AUTH_CHANNEL.search(block.text)
                        for block in blocks if block.section == scope or block.section.startswith(scope + " / ")):
        return None
    examples = [block for block in blocks if block.section == declaration.section and block.kind == "table_row"
                and BEARER_EXAMPLE_ROW.search(block.text)]
    return examples[0] if len(examples) == 1 else None


def documented_notice_scope(question, blocks, sources):
    """Resolve a redundant scope question when the cited cap is explicitly per card."""
    if len(sources) != 1 or not CARD_NOTICE_SCOPE_QUESTION.fullmatch(" ".join(question.split())):
        return None
    source = sources[0]
    if source.kind not in {"paragraph", "text"} or not CARD_NOTICE_CAP.search(source.text):
        return None
    if any(CUSTOMER_NOTICE_SCOPE.search(sentence) and re.search(NOTICE, sentence, re.I) and
           re.search(r"месяц|лимит|ограничени|не более|максимум", sentence, re.I)
           for block in blocks for sentence in SENTENCE_BREAK.split(block.text)):
        return None
    return source


def answered_by_document(question, blocks, sections=None, *, sources=()):
    """Resolve common questions only when the answer is explicit in the source."""
    wording = TIMING_SMELL.search(question)
    if wording and TIMING_WORDING.search(question):
        by_id = requirement_index(blocks)
        for block in sources:
            text = TIMING_QUOTED.sub(" ", block.text)
            if wording[0].casefold() in text.casefold():
                target = resolved_timing_reference(TIMING_REF.search(text), block, by_id)
                if target:
                    return target
    if (re.search(r"возврат", question, re.I) and re.search(r"месяц", question, re.I)
            and re.search(r"исходн\w*\s+покупк", question, re.I)):
        return matches(blocks, r"возврат\s+уменьшает\s+расходы\s+месяца\s+исходной\s+покупки")
    if re.search(r"тенге.*тиын|тиын.*тенге", question, re.I) and re.search(r"порог|лимит", question, re.I):
        return matches(blocks, r"(?:порог|лимит).{0,75}(?:₸|в тенге)")
    if answer := documented_bearer_channel(question, blocks, sources):
        return answer
    if answer := documented_notice_scope(question, blocks, sources):
        return answer
    if sections is not None:
        scopes = {api_contract(section) for section in sections}
        if len(scopes) != 1 or None in scopes:
            return None
        scope = scopes.pop()
        blocks = [block for block in blocks if api_contract(block.section) == scope]
        if answer := documented_auth_status(question, blocks):
            return answer
        if (re.search(r"\bкаки[ем]\b.*\b(?:значени|критери)\w*", question, re.I)
                and re.search(r"\bсумм\w*\b", question, re.I)
                and re.search(r"\bERROR\b|отклон", question, re.I)
                and not re.search(r"HTTP|код\w*\s+ответ|статус", question, re.I)
                and matches(sources, r"при\s+отклонении\s+суммы.*\bERROR\b")):
            candidates = [block for block in blocks
                          if block.kind == "table_row"
                          and re.search(r"(?:^| / )(?:Запрос|Параметры запроса|Query-параметры|Query parameters)(?: / |$)",
                                        block.section, re.I)
                          and re.match(r"\|\s*`?amount`?\s*\|", block.text, re.I)]
            if len(candidates) == 1 and re.search(
                    r"\|\s*integer\s*\|.*\d[\d\s]*\s*[—–-]\s*\d", candidates[0].text, re.I):
                return candidates[0]
    if (re.search(r"\bкаки[ем]\b.*\b(?:ограничени|правил|значени|диапазон)\w*", question, re.I)
            and re.search(r"\bсумм\w*\b", question, re.I)
            and re.search(r"\bпереключател\w*\b", question, re.I)):
        for block in blocks:
            if block.kind != "table_row" or not re.search(r"\|\s*`?amount`?\s*\|", block.text, re.I):
                continue
            if not re.search(r"[0-9][0-9\s]*\s*[—–-]\s*[0-9]", block.text):
                continue
            toggle = matches((item for item in blocks if item.kind == "table_row" and item.section == block.section),
                             r"\|\s*`?enabled`?\s*\|.*\b0\s+или\s+1\b")
            if toggle:
                return block
    format_alternatives = re.search(
        r"(?:строк\w*\s+или\s+(?:как\s+)?числ|числ\w*\s+или\s+(?:как\s+)?строк|"
        r"(?:string|integer)\s+или\s+(?:string|integer))", question, re.I)
    if format_alternatives and not any(block.kind == "example" for block in sources):
        amount_row = r"^\|\s*`?amount`?\s*\|\s*(?:string|integer)\s*\|"
        candidates = [block for block in blocks if block.kind == "table_row"
                      and re.search(r"(?:^| / )(?:Ответ|Response)(?:$| / )", block.section, re.I)
                      and re.search(amount_row, block.text, re.I)]
        refers_to_amount = re.search(r"\bamount\b", question, re.I) or (
            re.search(r"\bпорог\w*\b", question, re.I) and
            any(block in sources and re.search(r"\bпорог\w*\b", block.text, re.I) for block in candidates))
        if refers_to_amount and len(candidates) == 1:
            response_row = candidates[0]
            if re.search(r"ответ", question, re.I) or (
                    len(sources) == 1 and response_row in sources
                    and re.search(r"\b(?:возвращ\w*|вернуть)\b", question, re.I)):
                return response_row
    if (re.search(r"какой\s+(?:HTTP[- ]?)?(?:статус|код).*для\s+чужой\s+карты", question, re.I)
            and re.search(r"\b(?:403|404)\b", question)):
        return matches(blocks, r"для чужой карты возвращается 404")
    return None
