"""Local checks shared by the web interface and the evaluation suite."""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re


MAX_TEXT = 50_000
MAX_SECTIONS = 350

RULES = {
    "limit_conflict": {"severity": "high", "category": "consistency"},
    "vague_requirement": {"severity": "medium", "category": "testability"},
    "retry_behavior": {"severity": "high", "category": "completeness"},
    "broken_reference": {"severity": "medium", "category": "completeness"},
    "duplicate_clause": {"severity": "high", "category": "consistency"},
    "open_decision": {"severity": "medium", "category": "completeness"},
    "acceptance_gap": {"severity": "medium", "category": "testability"},
    "semantic_conflict": {"severity": "medium", "category": "consistency"},
    "missing_scenario": {"severity": "medium", "category": "completeness"},
}

NUMBERED_ID = r"(?:[A-ZА-ЯЁ]{1,12}[-–_]\d+|Ф\d+)(?:[.-]\d+)*"
CLAUSE_ID = rf"(?:§\s*\d+(?:\.\d+)*|{NUMBERED_ID})"
REFERENCE_ID = rf"{CLAUSE_ID}(?![\w-]|\.\d)"
EXPLICIT_ID = re.compile(
    rf"^(?P<label>§\s*[\w.]+|\d+(?:\.\d+)+|{NUMBERED_ID})"
    r"\.?(?:[*_]{1,3})?(?:\s*[:—–-]\s*|\s+|(?=\|)|$)"
)
MARKDOWN_CLAUSE_PREFIX = re.compile(r"^(?:#{1,6}\s+|[-+*]\s+|\d+[.)]\s+)?(?:[*_]{1,3})?")
REFERENCE_GROUP = re.compile(
    r"(?:\bsee\s+(?:requirements?\s+)?|\bсм\.\s*(?:пункт\w*\s+)?|\bсогласно\s+(?:пункт\w*\s+)?|"
    r"\bin\s+(?:sections?\s+)?(?=§)|\bв\s+(?:(?:пункте|пунктах|разделе|разделах)\s+)?(?=§))"
    rf"(?P<targets>{REFERENCE_ID}(?:(?:\s*,\s*(?:(?:and|и)\s+)?|\s+(?:and|и)\s+){REFERENCE_ID})*)",
    re.I,
)
REFERENCE_TOKEN = re.compile(REFERENCE_ID, re.I)
EXTERNAL_SOURCE = re.compile(
    r"\b(?:ISO|IEC|IEEE|RFC|GOST|ГОСТ|СТ\s+РК)\b|\.(?:pdf|docx?)\b|"
    r"\bof\s+(?:an?\s+|the\s+)?(?:external\s+|attached\s+|user\s+|operating\s+)*"
    r"(?:standard|manual|contract|policy|agreement|law|regulation)\b|"
    r"\b(?:external|vendor|supplier|attached)\s+(?:specification|document)\b|"
    r"\b(?:стандарта|договора|закона|регламента|руководства|соглашения)\b|"
    r"\b(?:внешн\w+|прилагаем\w+|дочерн\w+)\s+(?:документ\w*|спецификаци\w*)\b",
    re.I,
)
OPEN_VALUE = re.compile(r"\b(?:TBD|TBC)\b|\[(?:уточнить|согласовать|to be confirmed)\]", re.I)
LOCAL_CODES = tuple(code for code in RULES if code not in {"acceptance_gap", "semantic_conflict", "missing_scenario"})
VAGUE = re.compile(
    r"\b(?:quickly|fast|soon|as soon as possible|user[- ]friendly|within a reasonable time|"
    r"as needed|appropriate(?:ly)?|adequate(?:ly)?|reasonable|seamless(?:ly)?|"
    r"быстр\w*|оперативн\w*|мгновенн\w*|удобн\w*|по необходимости|разумн\w+ срок\w*|"
    r"как можно скорее|просто и удобно)\b", re.I
)
REQUIREMENT = re.compile(
    r"\b(?:must|shall|should|needs? to|required|has to|долж\w*|необходим\w*|"
    r"обяз\w*|требуется|следует)\b", re.I
)
TIMED = re.compile(
    r"(?:\bwithin\b|\bat most\b|\bup to\b|не более|не позднее|в течение|\bза\b|[≤<])"
    r"\s*\d+(?:[.,]\d+)?\s*(?:ms\b|s\b|seconds?\b|minutes?\b|hours?\b|"
    r"мс\b|с\b|сек\w*|мин\w*|час\w*)", re.I
)
SPEED = re.compile(r"quickly|fast|soon|reasonable time|быстр|оперативн|мгновенн|срок|скорее", re.I)
VAGUE_SKIPS = re.compile(
    r'["«](?:quickly|fast|быстро|удобно)["»]|'
    r"(?:\bnot\b|\bне\b)\s+(?:necessarily\s+|обязательно\s+|слишком\s+)?"
    r"(?:quickly|fast|быстро|удобно)\b", re.I
)

MONEY = re.compile(
    r"(?<![\w.,+\-−])(?:(?P<prefix>[$€₽₸])\s*)?"
    r"(?P<amount>\d{1,3}(?:[ \u00a0\u202f,.'’]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"\s*(?P<suffix>₸|₽|\$|€|KZT\b|RUB\b|USD\b|EUR\b|тенге\b|руб(?:\.|лей\b))?"
    r"(?![\w.,]\d|\d)", re.I
)
CURRENCIES = {
    "₸": "KZT", "тенге": "KZT", "kzt": "KZT", "₽": "RUB", "руб.": "RUB",
    "рублей": "RUB", "rub": "RUB", "$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR",
}
LIMIT = re.compile(r"\b(?:limit\w*|maximum|max|ceiling|cap|лимит\w*|максим\w*|предел\w*)\b", re.I)
MINIMUM = re.compile(r"\b(?:minimum|min|floor|at least|нижн\w+ границ\w*|миним\w*|не менее)\b", re.I)
LIMIT_EXCLUSION = re.compile(
    r"\b(?:previous\w*|formerly|proposed|example|illustrative|testing only|"
    r"not applicable|unlimited|прежн\w*|ранее|предлага\w*|например|"
    r"тестов\w* пример\w*|без ограничений|не применяется)\b", re.I
)
ACTION = {
    "transfer": re.compile(r"\b(?:transfer\w*|перевод\w*)\b", re.I),
    "payment": re.compile(r"\b(?:payment\w*|плат[её]ж\w*|оплат\w*)\b", re.I),
    "withdrawal": re.compile(r"\b(?:withdraw\w*|сняти\w*)\b", re.I),
    "refund": re.compile(r"\b(?:refund\w*|возврат\w*)\b", re.I),
}
PERIOD = {
    "transaction": re.compile(
        r"\b(?:per (?:individual |single )?(?:transaction|operation|transfer|payment|refund|withdrawal)|"
        r"(?:one|single|each) (?:transfer|payment|transaction|withdrawal|refund)|"
        r"(?:на|за|одна|один|одну|одной|одного|разов\w*)\s+"
        r"(?:(?:один|одну|одной|одного|кажд\w*)\s+)?"
        r"(?:транзакц\w*|операц\w*|перевод\w*|плат[её]ж\w*|сняти\w*|возврат\w*))\b", re.I
    ),
    "day": re.compile(r"\b(?:daily|per day|a day|in 24 hours|суточн\w*|дневн\w*|в день|за сутки|за 24 час\w*)\b", re.I),
    "week": re.compile(r"\b(?:weekly|per week|недельн\w*|в неделю|за неделю)\b", re.I),
    "month": re.compile(r"\b(?:monthly|per month|месячн\w*|в месяц|за месяц)\b", re.I),
}
QUALIFIERS = {
    "personal": r"personal|retail|individuals?|физлиц\w*|личн\w*",
    "business": r"business|corporate|merchant\w*|бизнес\w*|корпоратив\w*|юрлиц\w*",
    "domestic": r"domestic|внутренн\w*|внутри страны",
    "international": r"international|cross[- ]border|международ\w*|трансгранич\w*",
    "premium": r"premium|преми\w*",
    "standard": r"standard|стандарт\w*|базов\w*",
    "verified": r"verified|верифицир\w*|подтвержд[её]н\w*",
    "unverified": r"unverified|неверифицир\w*|неподтвержд[её]н\w*",
    "card": r"cards?|карт\w*",
    "wallet": r"wallets?|кошел[её]к\w*|кошельк\w*",
    "mobile": r"mobile|мобильн\w*",
    "atm": r"atm|банкомат\w*",
    "p2p": r"p2p",
    "online": r"web|online|онлайн",
}
QUALIFIERS = {key: re.compile(r"\b(?:" + value + r")\b", re.I) for key, value in QUALIFIERS.items()}
CONDITION = re.compile(r"\b(?:unless|except|only if|provided that|where|after|before|"
                       r"for (?:[\w-]+ ){0,4}(?:users|customers|clients|accounts)|"
                       r"кроме|исключая|только если|при условии|после|до момента|"
                       r"для (?:[\w-]+ ){0,4}(?:клиент\w*|пользовател\w*|счет\w*))\b", re.I)

RETRY = re.compile(r"\b(?:retry\w*|re[- ]?send\w*|repeat\w*|повтор\w*|переотправ\w*)\b", re.I)
TIMEOUT = re.compile(
    r"\b(?:timeout|timed out|no (?:response|reply)|(?:response|reply) (?:is )?lost|"
    r"not receive\w* (?:a |the )?response|connection (?:fails|error)|"
    r"тайм[- ]?аут\w*|нет ответа|ответ не (?:поступ\w*|приш[её]л)|"
    r"не получ\w* ответ\w*|ответ потер\w*|ошибк\w* соединения)\b", re.I
)
RETRY_OFF = re.compile(
    r"(?:\bnever\b|\bdo not\b|\bmust not\b|\bshall not\b|\bshould not\b|\bdisables?\b|\bне\b|\bзапрещ\w*\b)"
    r"(?:\s+\w+){0,2}\s+(?:retry\w*|re[- ]?send\w*|repeat\w*|повтор\w*|переотправ\w*)",
    re.I,
)
RETRY_ID = re.compile(
    r"\b(?:idempoten\w*|идемпотент\w*|same (?:operation|request|transaction|transfer) (?:id|identifier|reference)|"
    r"same key|одинаков\w+ (?:ключ\w*|идентификатор\w*)|"
    r"тот же (?:ключ\w*|идентификатор\w*)|идентификатор\w* исходн\w+ (?:операци\w*|запрос\w*))\b", re.I
)
ONCE = re.compile(
    r"\b(?:(?:debit\w*|charg\w*|process\w*|execut\w*|appl\w*)(?:\s+\w+){0,5}\s+"
    r"(?:at most once|only once|exactly once|once only)|"
    r"must not (?:debit|charge)(?:\s+\w+){0,4}\s+twice|"
    r"prevent\w* duplicate (?:debits?|charges?|transfers?|transactions?)|"
    r"без повторн\w+ списани\w*|не допуска\w+ повторн\w+ списани\w*|"
    r"(?:списа\w*|списыв\w*|прово[дж]\w*|выполн\w*)(?:\s+\w+){0,6}\s+(?:один раз|одного раза))\b", re.I
)


def normalized(text):
    return re.sub(r"\s+", " ", text).strip().casefold()


def sections_from(text, *, first_line=1):
    sections = []
    start = 0
    for line_number, raw in enumerate(text.split("\n"), first_line):
        value = raw.strip()
        offset = start + len(raw) - len(raw.lstrip())
        start += len(raw) + 1
        if not value or re.fullmatch(r"[#*_\-\s]+", value):
            continue
        clause_text = value[1:].lstrip() if value.startswith("|") else value
        clause_text = MARKDOWN_CLAUSE_PREFIX.sub("", clause_text, count=1)
        matched = EXPLICIT_ID.match(clause_text)
        label = matched["label"].rstrip(".") if matched else f"L{line_number}"
        content = clause_text[matched.end():].strip() if matched else value
        sections.append({
            "id": f"L{line_number}", "label": label, "line": line_number,
            "text": value, "content": content, "start": offset, "end": offset + len(value),
        })
    return sections


def evidence(section, quote=None):
    source = section["text"]
    quote = source if quote is None else quote
    relative = source.find(quote)
    if not quote or relative < 0:
        raise ValueError("Quote absent from source")
    return {**{key: section[key] for key in ("id", "label", "line")}, "quote": quote,
            "start": section["start"] + relative, "end": section["start"] + relative + len(quote)}


def finding(code, sources, values=None, origin="local", explanation=None):
    details = RULES[code]
    evidence_ids = "-".join(source["id"] for source in sources)
    item = {"id": f"{code}:{evidence_ids}", "code": code, **details, "origin": origin,
            "evidence": sources, "values": values or {}}
    if explanation:
        item["explanation"] = explanation
    return item


def _parse_amount(value):
    raw = re.sub(r"[\s'’]", "", value)
    if re.search(r"[.,]\d{1,2}$", raw):
        major, minor = re.split(r"[.,](?=\d{1,2}$)", raw, maxsplit=1)
        raw = re.sub(r"[.,]", "", major) + "." + minor
    else:
        raw = re.sub(r"[.,]", "", raw)
    return Decimal(raw)


def clause_key(label):
    return label.removeprefix("§").strip().upper().replace("–", "-")


def local_reference_targets(content):
    # A document name can qualify a whole sequence of section numbers.
    for statement in re.split(r"[;!?]|(?<=\.)\s+(?=[A-ZА-ЯЁ][a-zа-яё])", content):
        if EXTERNAL_SOURCE.search(statement):
            continue
        plain = re.sub(r"(?<!\w)[*_\x60]+|[*_\x60]+(?!\w)", "", statement)
        for group in REFERENCE_GROUP.finditer(plain):
            yield from REFERENCE_TOKEN.findall(group["targets"])


def structural_findings(sections):
    declared = defaultdict(list)
    for section in sections:
        if section["label"] != section["id"]:
            declared[clause_key(section["label"])].append(section)
    items = []
    for group in declared.values():
        if len(group) > 1:
            items.append(finding("duplicate_clause", [evidence(section) for section in group]))
    for section in sections:
        targets = list(dict.fromkeys(target for target in local_reference_targets(section["content"])
                                     if clause_key(target) not in declared))
        if targets:
            items.append(finding("broken_reference", [evidence(section)], {"targets": targets}))
    items.extend(open_decisions(sections))
    return items


def open_decisions(sections):
    for section in sections:
        markers = list(dict.fromkeys(match[0] for match in OPEN_VALUE.finditer(section["content"])))
        if markers:
            yield finding("open_decision", [evidence(section)], {"markers": markers})


def verify_findings(text, items):
    """Check the final combined report against the canonical source, including Unicode offsets."""
    sections = {part["id"]: part for part in sections_from(text)}
    verified = []
    seen = set()
    for item in items:
        refs = item["evidence"]
        if not refs or item["id"] in seen:
            continue
        for ref in refs:
            section = sections.get(ref["id"])
            if (not section or ref["line"] != section["line"] or ref["label"] != section["label"]
                    or not section["start"] <= ref["start"] < ref["end"] <= section["end"]
                    or text[ref["start"]:ref["end"]] != ref["quote"]):
                break
        else:
            seen.add(item["id"])
            verified.append(item)
    verified.sort(key=lambda item: (item["severity"] != "high", item["evidence"][0]["line"], item["code"]))
    return verified


def _limit(section):
    sentence = section["content"]
    if not LIMIT.search(sentence) or LIMIT_EXCLUSION.search(sentence) or MINIMUM.search(sentence):
        return None
    actions = [key for key, rule in ACTION.items() if rule.search(sentence)]
    scopes = [key for key, rule in PERIOD.items() if rule.search(sentence)]
    if len(actions) != 1 or len(scopes) != 1:
        return None
    qualifiers = tuple(key for key, rule in QUALIFIERS.items() if rule.search(sentence))
    condition = CONDITION.search(sentence)
    extra_condition = normalized(sentence[condition.start():].rstrip(".")) if condition else ""
    amounts = []
    for match in MONEY.finditer(sentence):
        symbol = match["prefix"] or match["suffix"]
        if not symbol:
            continue
        try:
            amounts.append((CURRENCIES[symbol.lower()], _parse_amount(match["amount"]), match))
        except (KeyError, InvalidOperation):
            continue
    if len(amounts) != 1:
        return None
    currency, amount, match = amounts[0]
    offset = len(section["text"]) - len(sentence)
    edit = {"line": section["line"], "quote": section["text"],
            "start": offset + match.start("amount"), "end": offset + match.end("amount"), "text": match["amount"]}
    return (actions[0], scopes[0], currency, qualifiers, extra_condition), amount, edit


def money_limit_findings(sections):
    grouped_limits = defaultdict(list)
    for section in sections:
        parsed = _limit(section)
        if parsed:
            signature, amount, edit = parsed
            grouped_limits[signature].append((amount, section, edit))
    for signature, entries in grouped_limits.items():
        amounts = {}
        for amount, section, _edit in entries:
            amounts.setdefault(amount, section)
        if len(amounts) < 2:
            continue
        values = {amount: format(amount, "f") for amount in amounts}
        yield finding("limit_conflict", [evidence(section) for section in amounts.values()],
                      {"amounts": list(values.values()), "currency": signature[2], "period": signature[1],
                       "limit_edits": [{**edit, "amount": values[amount]} for amount, _, edit in entries]})


def retry_findings(sections):
    for section in sections:
        value = section["content"]
        actions = [key for key, rule in ACTION.items() if rule.search(value)]
        if not actions or not RETRY.search(value) or not TIMEOUT.search(value) or RETRY_OFF.search(value):
            continue
        candidates = [line["content"] for line in sections if line is section or
                      (any(ACTION[action].search(line["content"]) for action in actions) and
                       not any(rule.search(line["content"]) for action, rule in ACTION.items()
                               if action not in actions))]
        if not (any(RETRY_ID.search(line) for line in candidates) and
                any(ONCE.search(line) for line in candidates)):
            yield finding("retry_behavior", [evidence(section)])


def analysis_events(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_TEXT:
        raise ValueError("text_too_long")
    yield {"type": "stage", "step": "segment"}
    sections = sections_from(text)
    if len(sections) > MAX_SECTIONS:
        raise ValueError("too_many_sections")
    if len(re.findall(r"[^\W\d_]+", text)) < 4:
        raise ValueError("text_too_short")
    yield {"type": "stage", "step": "references"}
    findings = structural_findings(sections)
    yield {"type": "stage", "step": "wording"}
    for section in sections:
        raw = section["content"]
        # A quoted example and an already quantified timing requirement are not signals.
        if REQUIREMENT.search(raw) and not VAGUE_SKIPS.search(raw):
            terms = list(dict.fromkeys(match[0].lower() for match in VAGUE.finditer(raw)
                                       if not (SPEED.search(match[0]) and TIMED.search(raw))))
            if terms:
                findings.append(finding("vague_requirement", [evidence(section)], {"terms": terms}))
    yield {"type": "stage", "step": "compare", "count": len(sections)}
    findings.extend(money_limit_findings(sections))
    yield {"type": "stage", "step": "scenarios"}
    findings.extend(retry_findings(sections))

    findings.sort(key=lambda item: (item["severity"] != "high", item["evidence"][0]["line"], item["code"]))
    trace = {}
    for item in findings:
        for ref in item["evidence"]:
            trace.setdefault(ref["line"], {"line": ref["line"], "label": ref["label"], "quote": ref["quote"][:160]})
            if len(trace) == 8:
                break
        if len(trace) == 8:
            break
    yield {"type": "stage", "step": "report", "evidence": list(trace.values())}
    yield {"type": "result", "report": {
        "schema_version": 1, "engine": "local", "findings": findings,
        "statistics": {"sections": len(sections), "characters": len(text)},
    }}


def analyze(text):
    return next(event["report"] for event in analysis_events(text) if event["type"] == "result")
