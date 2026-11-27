"""Create the Russian requirements review file used by the hackathon CLI."""

from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from document_input import MAX_UPLOAD, extract_document
from gemini import configured_models, provider_name
from hackathon_review import (CRITERIA_RU, DEFAULT_FALLBACK, DEFAULT_MODEL, OUTCOME_RU, SEVERITY_RU, Evidence,
                              completed_steps, review_requirements, review_requirements_steps)
from public_links import check_audit_links, github_repository, web_urls
from review_rules import (FROZEN_REFUND_QUESTION, KZT_INTEGER, REFUND_LIMIT_QUESTION, REFUND_ON_FROZEN_ACCOUNT, TIMING_QUESTION, api_contract,
                          internal_references, requirement_index)
from visual_review import review_diagram_text, review_figures


PROJECT = Path(__file__).resolve().parent
MARKDOWN_MIME = "text/markdown"
ERRORS = {
    "empty_file": "в документе нет читаемого текста",
    "invalid_document": "файл повреждён или его содержимое не соответствует расширению",
    "scanned_document": "в PDF нет текстового слоя, требуется распознанная копия",
    "encrypted_document": "PDF защищён паролем",
    "unsupported_file": "поддерживаются .md, .markdown, .txt, .pdf и .docx",
    "file_too_large": "размер файла превышает 4 МиБ",
    "text_too_long": "документ превышает допустимый объём текста",
    "too_many_pages": "PDF содержит слишком много страниц",
    "invalid_text_encoding": "не удалось прочитать кодировку текста",
    "no_requirements": "не найдено требований для проверки",
    "gemini_unconfigured": "настройте ИИ-провайдера в окружении или файле .env",
    "gemini_access": "ИИ-провайдер отклонил доступ по API-ключу",
    "gemini_quota": "исчерпан лимит запросов ИИ-провайдера",
    "gemini_model": "указанная модель недоступна",
    "gemini_busy": "ИИ-провайдер временно не обработал запрос",
    "gemini_timeout": "модель не ответила за отведённое время",
    "gemini_unavailable": "ошибка доступа к ИИ-провайдеру",
    "gemini_invalid_response": "ответ модели не прошёл проверку структуры",
    "gemini_invalid_evidence": "ответ модели содержит неподтверждённые ссылки или цитаты",
    "gemini_incomplete_inventory": "модель пропустила пункты, обязательные для проверки",
    "invalid_model": "укажите корректный идентификатор модели выбранного провайдера",
    "same_file": "выберите для отчёта путь, отличный от входного файла",
    "same_answers_file": "выберите для ответов путь, отличный от входного файла и отчёта",
    "same_json_file": "выберите для JSON путь, отличный от входного файла и остальных результатов",
    "invalid_output": "выберите файл отчёта с расширением .md или .json",
}
WARNINGS = {
    "partial_pdf": "Некоторые страницы PDF без текстового слоя пропущены. Для полного ревью нужен PDF с распознанным текстом.",
    "unreviewed_figures": "Аудит проверил текст. Сверьте схемы и изображения с требованиями вручную.",
}
PRIORITIES = {"blocker": 0, "major": 1, "minor": 2}
REFERENCE_STATUS = {"resolved": "Найдена", "missing": "Пункт отсутствует", "ambiguous": "Несколько пунктов"}
READ_OPERATION = re.compile(r"чтени|чита|\bread", re.I)
HTTP_ACCESS = re.compile(r"\b(?:403|404)\b")
HTTP_GET = re.compile(r"\bGET\b", re.I)
METHOD_DECISION = re.compile(r"(?:как(?:ой|им|ого)|чем\s+заменить).{0,35}(?:http[- ]?)?метод|безопасн\w*\s+семантик", re.I)
WRITE_OPERATION = re.compile(r"сохранен|сохраня|сохранить|изменен|изменя|модифиц|\bwrite|созда\w*\s+заявк", re.I)
HTTP_VALIDATION = re.compile(r"(?:\b200\b.*\bERROR\b|\bERROR\b.*\b200\b)", re.I)
HTTP_VALIDATION_CONFLICT = re.compile(r"(?=.*\b200\b)(?=.*\b400\b)(?=.*(?:неверн|некоррект|валид|ошибк))", re.I)
HTTP_STATUS_QUESTION = re.compile(r"http[- ]статус|код ответа|(?:\b200\b.*\b400\b|\b400\b.*\b200\b)", re.I)
PRODUCTION_ENV = re.compile(
    r"\bprod(?:uction)?\b|(?:промышленн|продуктивн|продуктов|боев)\w*\s+(?:сред|контур|окружен)", re.I,
)
ENDPOINT_ADDRESS = re.compile(r"\burl\b|адрес\w*\s+(?:метода|операции|запроса)", re.I)
MISSING_ADDRESS = re.compile(
    r"(?=.*(?:отсутств|не\s+(?:указан|задан|привед|определ)|нет))(?=.*(?:\burl\b|адрес))", re.I,
)
EMPTY_PROD_FIELD = re.compile(r"\bprod(?:uction)?\s*:\s*[—–-]+\s*(?=$|[|.])", re.I)
DEV_ROUTE = re.compile(r"\bdev\s*:\s*`?(?:https?://|/(?!/))[^\s|`]+", re.I)
ACCEPTANCE_RESULT_QUESTION = re.compile(
    r"(?=.*ожидаем\w*\s+результат)(?=.*(?:таблиц|строк)\w*.{0,32}при[её]мк)", re.I,
)
EMPTY_ACCEPTANCE_RESULT = re.compile(
    r"(?=.*(?:не\s+(?:заполнен|указан)|отсутству|пуст\w*\s+ячейк))(?=.*ожидаем\w*\s+результат)", re.I,
)
WEBHOOK_ACK_QUESTION = re.compile(r"(?=.*(?:вебхук|webhook))(?=.*(?:статус|код ответа))(?=.*(?:прекращ|останавли|подтвержд))", re.I)
TIMING_LIMIT = re.compile(
    r"(?:максимальн|предельн|допустим)\w*\s+(?:срок|время|задержк)|"
    r"количественн\w*\s+(?:требовани|критери)\w*\s+к\s+(?:скорост|времен|задержк)", re.I
)
CONFLICT_QUESTIONS = (
    re.compile(r"(?=.*(?:месяц|месячн))(?=.*(?:покупк|операци))(?=.*(?:дат[аеыу]|провед|соверш[её]н))", re.I),
    re.compile(r"(?=.*(?:уведомлен|\bpush\b|\bпуш\w*\b))(?=.*(?:порог|лимит))(?=.*(?:повторн|второ|уже отправлен|один раз|истори|сбрасыва|сброс))", re.I),
    re.compile(r"какая сумма|какое значение лимита|какой(?: размер)? лимит|какой предел", re.I),
)
REFUND_DECISION = re.compile(
    r"(?=.*возврат)(?=.*зачисл)(?=.*(?:до\s+(?:момента\s+)?(?:полн\w*\s+|окончательн\w*\s+)?снятия|"
    r"(?:ожида\w*|жда\w*)\s+сняти|отказ|удерж|незачисл|не\s+зачисл))", re.I,
)
REFUND_SEPARATE_DECISION = re.compile(r"\b(?:HTTP|код\w*|статус\w*|формат\w*|каким событием)\b", re.I)


def run_version():
    deployment_commit = os.environ.get("VERCEL_GIT_COMMIT_SHA", "")
    if re.fullmatch(r"[0-9a-f]{40}", deployment_commit):
        return deployment_commit

    def git(*arguments):
        return subprocess.run(("git", "-C", str(PROJECT), *arguments), check=True,
                              capture_output=True, text=True, timeout=5).stdout.strip()
    try:
        version = git("rev-parse", "HEAD")
        modified = git("status", "--porcelain", "--untracked-files=normal")
        return version + (" (есть локальные изменения)" if modified else "")
    except (OSError, subprocess.SubprocessError):
        return "коммит не определён"


def md(text):
    return re.sub(r"([\\|\[\]\x60*_])", r"\\\1", html.escape(" ".join(text.split()), quote=False))


def location(start, end, extension):
    label = f"L{start}" if start == end else f"L{start}–L{end}"
    return f"{label} (извлечённый текст)" if extension in {"pdf", "docx"} else label


def overlaps_rule(issue, rule, refs=None, *, blocks=None):
    """Match the same decision in the source, including known phrasing variants."""
    refs = set(issue.refs if refs is None else refs)
    overlap = refs.intersection(rule.refs)
    method_rule = rule.criterion == "design" and HTTP_GET.search(rule.explanation) and WRITE_OPERATION.search(rule.explanation)
    if method_rule and refs == set(rule.refs) and issue.explanation.split() == rule.explanation.split():
        return True
    get_write = (
        method_rule
        and ((HTTP_GET.search(issue.explanation) and WRITE_OPERATION.search(issue.explanation)
              and (issue.criterion == "design" or METHOD_DECISION.search(issue.question)
                   or METHOD_DECISION.search(issue.explanation)))
             or (HTTP_GET.search(issue.question) and WRITE_OPERATION.search(issue.question)))
    )
    if not overlap:
        if not get_write or not blocks:
            return False
        issue_scopes = {api_contract(blocks[ref].section) for ref in refs}
        rule_scopes = {api_contract(blocks[ref].section) for ref in rule.refs} - {None}
        return len(issue_scopes) == 1 and issue_scopes == rule_scopes
    if (issue.criterion == rule.criterion == "traceability" and refs == set(rule.refs)
            and rule.question.startswith("На какие существующие пункты должна вести ссылка")):
        targets = re.search(r"«([^»]+)»", rule.question)
        finding_text = issue.question + " " + issue.explanation
        if (targets and re.search(r"несуществ|отсутств|не найден|нет пункт", finding_text, re.I)
                and any(re.search(rf"(?<![\w-]){re.escape(target)}(?![\w-])", finding_text, re.I)
                        for target in targets[1].split(", "))):
            return True
    if (rule.question == FROZEN_REFUND_QUESTION and issue.criterion in {"consistency", "clarity", "completeness"}
            and REFUND_ON_FROZEN_ACCOUNT.search(issue.question) and REFUND_DECISION.search(issue.question)
            and not REFUND_SEPARATE_DECISION.search(issue.question)):
        return True
    if len(overlap) >= 2 and rule.criterion == issue.criterion == "consistency":
        if any(topic.search(issue.question) and topic.search(rule.question) for topic in CONFLICT_QUESTIONS):
            return True
    if refs == set(rule.refs) and issue.criterion == "consistency":
        column = rule.explanation.startswith("Итог столбца") and re.search(r"сумм\w*.*(?:столбц|строк)", issue.explanation, re.I)
        row = rule.explanation.startswith("В строке указан итог") and re.search(r"сумм\w*.*строк", issue.explanation, re.I)
        if (column or row) and not re.search(r"округл|конвертац|валют|налог|тариф|порядок", issue.question, re.I):
            return True
    if (refs == set(rule.refs) and rule.explanation.startswith("Нижняя граница")
            and re.search(r"диапазон|не\s+менее.*не\s+более", issue.explanation, re.I)
            and re.search(r"како[йие]+\s+(?:точн\w+\s+)?(?:срок|диапазон|границ)", issue.question, re.I)):
        return True
    if (refs == set(rule.refs) and rule.explanation.startswith("Выражение «")
            and issue.criterion == rule.criterion == "verifiability"
            and re.search(r"не имеет объективных критериев|непроверяем|неизмерим|нет измерим|субъектив|объективно провер",
                          issue.explanation, re.I)):
        term = rule.explanation.partition("«")[2].partition("»")[0]
        expression = re.escape(term[:-1]) + r"\w*" if term.endswith("но") else re.escape(term)
        if re.search(rf"\b{expression}\b", issue.explanation, re.I):
            return True
    if (rule.criterion == "verifiability" and rule.question.startswith(TIMING_QUESTION)
            and issue.criterion in {"verifiability", "clarity", "completeness"}
            and TIMING_LIMIT.search(issue.question)):
        return True
    if (rule.criterion == "verifiability" and rule.question.startswith("Что указать в этой строке приёмки")
            and "ожидаемый результат" in rule.question and rule.refs[-1] in refs):
        same_payload = r"с тем же ключом и (?:суммой|неизменным телом)"
        if (blocks and re.search(same_payload, blocks[rule.refs[-1]].text, re.I)
                and re.search(r"(?:друг|измен[её]н|отличающ)\w*\s+(?:сумм|тел)", issue.question, re.I)):
            return False
        same_retry_result = (
            issue.criterion == "verifiability" and refs == set(rule.refs)
            and EMPTY_ACCEPTANCE_RESULT.search(issue.explanation)
            and re.search(r"повтор\w*", issue.question, re.I)
            and re.search(same_payload, issue.question, re.I)
        )
        if same_retry_result:
            return True
        asks_api_contract = re.search(r"\b(?:HTTP|статус\w*|код\w*|тело|формат\w*)\b", issue.question, re.I)
        if not asks_api_contract:
            if ACCEPTANCE_RESULT_QUESTION.search(issue.question):
                return True
            if (refs <= set(rule.refs) and EMPTY_ACCEPTANCE_RESULT.search(issue.explanation)
                    and re.match(r"какой(?: именно)? результат|что именно должен увидеть", issue.question, re.I)):
                return True
            if refs == set(rule.refs):
                expected = re.search(r"ожидаем\w*\s+результат", issue.question, re.I)
                asks_for_result = re.match(r"какой результат\b", issue.question, re.I)
                if expected or asks_for_result and EMPTY_ACCEPTANCE_RESULT.search(issue.explanation):
                    return True
    if rule.question == REFUND_LIMIT_QUESTION and refs == set(rule.refs) and issue.criterion == "consistency":
        amounts = {"".join(amount.split()) for amount in re.findall(KZT_INTEGER, rule.explanation, re.I)}
        mentioned = {"".join(amount.split()) for amount in re.findall(KZT_INTEGER, issue.question, re.I)}
        separate_decision = re.search(r"\b(?:HTTP|статус\w*|код\w*|тел[оа]|поряд\w*|перв\w*|одновременно)\b",
                                      issue.question, re.I)
        if not separate_decision and re.search(r"лимит|максимальн\w*\s+(?:сумм|ограничени)", issue.question, re.I) and (
                re.search(r"возврат", issue.question, re.I) or len(amounts) == 2 and amounts == mentioned):
            return True
    if len(overlap) >= 2 and refs.issubset(rule.refs):
        if all(READ_OPERATION.search(item.question) for item in (issue, rule)):
            return True
        if all(set(HTTP_ACCESS.findall(item.explanation)) == {"403", "404"} for item in (issue, rule)):
            return True
        if (blocks and rule.question.startswith("Для каких отказов API возвращает 403")
                and set(HTTP_ACCESS.findall(issue.question)) == {"403", "404"}
                and re.fullmatch(r"Какой(?: именно)? (?:HTTP[- ]?)?(?:статус|код)(?: ответа)?"
                                 r"\s*\(?(?:403 или 404|404 или 403)\)?\s+"
                                 r"(?:должен возвращаться|возвращается)\s+(?:клиенту\s+)?при запросе\s+"
                                 r"чужой или (?:несуществующей|отсутствующей) карты\?", issue.question, re.I)):
            general_denial, exception = (blocks[ref].text for ref in rule.refs)
            if not re.search(r"чуж|владел|отсутств|несуществ", general_denial, re.I) and re.search(
                    r"для чужой карты возвращается 404, как и для отсутствующей карты", exception, re.I):
                return True
    if get_write:
        return True
    if rule.question.startswith("Какой HTTP-статус подтверждает обработку вебхука") and refs == set(rule.refs):
        statuses = r"\b2\d{2}\b"
        same_codes = set(re.findall(statuses, issue.question)) == set(re.findall(statuses, rule.question))
        if WEBHOOK_ACK_QUESTION.search(issue.question) or (
                same_codes and issue.criterion == "consistency"
                and re.search(r"статус|код (?:ответа|состояния)", issue.question, re.I)
                and re.search(r"успешн\w*\s+(?:обработк\w*|получени\w*)", issue.question, re.I)
                and re.search(r"событи|вебхук", issue.question, re.I)):
            return True
    if not HTTP_VALIDATION.search(rule.explanation):
        return False
    same_error = HTTP_VALIDATION.search(issue.explanation)
    same_status_decision = HTTP_STATUS_QUESTION.search(issue.question)
    if (issue.criterion == "consistency" and refs == set(rule.refs)
            and HTTP_VALIDATION_CONFLICT.search(issue.question)):
        return True
    return bool((same_error or HTTP_VALIDATION_CONFLICT.search(issue.explanation))
                and (same_status_decision or (same_error and len(refs) == 1)))


def evidence_payload(source, extension, page_spans):
    block = source.block if isinstance(source, Evidence) else source
    cited = location(source.line, source.end, extension)
    pages = [page for page, start, end in page_spans if start <= source.end and end >= source.line]
    if pages:
        label = f"стр. {pages[0]}" if len(pages) == 1 else f"стр. {pages[0]}–{pages[-1]}"
        cited = f"{label} · {cited}"
    return {"line": source.line, "end": source.end, "pages": pages, "location": cited,
            "section": block.section, "source_id": block.source_id,
            "quote": source.quote if isinstance(source, Evidence) else block.text}


def reference_payload(blocks, extension, page_spans):
    block_list = list(blocks.values())
    by_id = requirement_index(block_list)

    def source_location(block):
        payload = evidence_payload(block, extension, page_spans)
        del payload["quote"]
        return payload

    links = []
    for key, (label, origins) in internal_references(block_list).items():
        declarations = by_id.get(key, [])
        status = "missing" if not declarations else "resolved" if len(declarations) == 1 else "ambiguous"
        links.append({"target": label, "status": status, "label": REFERENCE_STATUS[status],
                      "origins": [source_location(block) for block in origins],
                      "declarations": [source_location(block) for block in declarations]})
    return links


def external_reference_payload(blocks, extension, page_spans):
    links = {}
    for block in blocks.values():
        for url in dict.fromkeys(web_urls(block.text)):
            if url not in links:
                links[url] = {"url": url, "check": "github" if github_repository(url) else "manual", "line": block.line, "origins": []}
            source = evidence_payload(block, extension, page_spans)
            links[url]["origins"].append(source["location"])
    return list(links.values())


def missing_production_address_keys(issue, evidence):
    if (issue.criterion not in {"completeness", "feasibility"} or not PRODUCTION_ENV.search(issue.question)
            or not ENDPOINT_ADDRESS.search(issue.question) or issue.question.count("?") != 1
            or re.search(r"\bи\s+(?:как|како\w*|где|когда)\b", issue.question, re.I)):
        return set()
    blocks = [item.block if isinstance(item, Evidence) else item for item in evidence]
    empty_fields = {block.ref for block in blocks if EMPTY_PROD_FIELD.search(block.text)}
    if empty_fields:
        return empty_fields
    return {frozenset(block.ref for block in blocks)} if MISSING_ADDRESS.search(issue.explanation) else set()


def scope_production_address(issue, evidence):
    address_keys = missing_production_address_keys(issue, evidence)
    if not address_keys:
        return issue
    for item in evidence:
        block = item.block if isinstance(item, Evidence) else item
        if block.ref in address_keys and DEV_ROUTE.search(block.text):
            return issue.model_copy(update={
                "severity": "major",
                "explanation": "Промышленный URL отсутствует. Dev-маршрут указан. Настройка и проверка интеграции в Prod зависят от согласования адреса.",
                "next_step": "Указать Prod URL перед производственной проверкой интеграции.",
            })
    return issue


def build_audit(result, path, extension, digest, warnings, page_spans, *, rules_only=False, pdf_coverage=None,
                pdf_origin=None, visual=None):
    title, blocks, inventory, set_review, rules, passes, omitted, replaced_quotes = result
    visual_findings, visual_coverage, visual_model = visual or ([], None, None)
    visual_by_issue = {id(item.issue): item.figure for item in visual_findings}
    if visual_model:
        passes = [*passes, ("Чтение схем", visual_model)]
    per_req = defaultdict(list)
    finding_data = []
    refs_to_req = defaultdict(list)
    numbered = [(f"REQ-{number:03}", entry, evidence)
                for number, (entry, evidence) in enumerate(inventory, 1)]
    for rid, entry, evidence in numbered:
        refs_to_req[entry.ref].append(rid)
        for issue in entry.issues:
            if not any(overlaps_rule(issue, rule, [entry.ref], blocks=blocks) for rule in rules):
                finding_data.append((scope_production_address(issue, [evidence]), [rid], [evidence], "LLM"))
    combined = [(issue, "Правило SanA1") for issue in rules]
    combined.extend((issue, "LLM") for issue in set_review.issues
                    if not any(overlaps_rule(issue, rule, blocks=blocks) for rule in rules))
    combined.extend((item.issue, "Сверка схемы с текстом") for item in visual_findings)
    for issue, source in combined:
        refs = list(dict.fromkeys(issue.refs))
        linked = list(dict.fromkeys(rid for ref in refs for rid in refs_to_req[ref]))
        evidence = [blocks[ref] for ref in refs]
        finding_data.append((scope_production_address(issue, evidence) if source == "LLM" else issue,
                             linked, evidence, source))
    findings = []
    production_address_keys = set()
    for issue, linked, evidence, source in sorted(finding_data, key=lambda row: PRIORITIES[row[0].severity]):
        address_keys = missing_production_address_keys(issue, evidence)
        if address_keys and address_keys <= production_address_keys:
            continue
        production_address_keys.update(address_keys)
        fid = f"Д-{len(findings) + 1:02}"
        for rid in linked:
            per_req[rid].append(fid)
        confidence = ("low" if source == "Сверка схемы с текстом" or re.search(
            r"(?:^|\n)\s*(?:проверьте|возможно|возможное|вероятно)\b", issue.explanation + "\n" + issue.question, re.I)
            else "medium" if source == "LLM" else "high")
        findings.append({"id": fid, "criterion": CRITERIA_RU[issue.criterion],
                         "severity": issue.severity, "priority": SEVERITY_RU[issue.severity],
                         "engine": source, "explanation": issue.explanation, "confidence": confidence,
                         "kind": "advice" if issue.severity == "minor" and confidence == "low" else "finding",
                         "question": issue.question, "next_step": issue.next_step,
                         "requirements": linked,
                         **({"visual_evidence": visual_by_issue[id(issue)]} if id(issue) in visual_by_issue else {}),
                         "evidence": [evidence_payload(item, extension, page_spans) for item in evidence]})
    requirements = [{"id": rid, "source_id": evidence.block.source_id,
                         "summary": entry.summary, "assessment": entry.assessment,
                         "assessment_status": "unchecked" if rules_only or entry.assessment.startswith("Не проверено.") else "reviewed",
                     "source": evidence_payload(evidence, extension, page_spans), "findings": per_req[rid]}
                    for rid, entry, evidence in numbered]
    checks = []
    for key in ("consistency", "completeness", "traceability", "feasibility"):
        check = getattr(set_review, key)
        linked_evidence = [source for issue, _, evidence, _ in finding_data if issue.criterion == key for source in evidence]
        if check.outcome != "issue" and linked_evidence:
            check = check.model_copy(update={
                "outcome": "issue",
                "comment": "Найдены нарушения по этому критерию. Подробности и вопросы приведены ниже.",
                "refs": [(source.block if isinstance(source, Evidence) else source).ref for source in linked_evidence],
            })
        checks.append({"criterion": CRITERIA_RU[key], "outcome": check.outcome,
                       "status": OUTCOME_RU[check.outcome], "comment": check.comment,
                       "evidence": [evidence_payload(blocks[ref], extension, page_spans)
                                    for ref in dict.fromkeys(check.refs)]})

    tally = Counter(item["severity"] for item in findings)
    counts = {key: tally[key] for key in PRIORITIES}
    visual_completed = visual_coverage and visual_coverage["status"] == "completed"
    notices = [WARNINGS.get(w, "Предупреждение при извлечении текста: " + w) for w in warnings
               if w != "unreviewed_figures" or not visual_completed]
    if visual_coverage:
        if visual_coverage["status"] == "unavailable":
            notices.append("Чтение схем ИИ недоступно в этом прогоне. Текст проверен.")
        elif visual_coverage["status"] == "completed":
            notices.append(f"С таблицами сопоставлено переходов на схемах — {visual_coverage['compared']}. "
                           "Распознавание и остальные изображения требуют ручной сверки.")
    if pdf_coverage and pdf_coverage["unread"]:
        pages = ", ".join(map(str, pdf_coverage["unread"]))
        notices.append(f"Страницы PDF без читаемого текста — {pages}.")
    if pdf_origin:
        pages = ", ".join(map(str, pdf_origin["unread"]))
        notices.append(f"Проверен отредактированный текст. При извлечении из исходного PDF не прочитаны страницы {pages} "
                       f"(всего страниц {pdf_origin['total']}). Ссылки относятся к текущему тексту.")
    if rules_only:
        notices.insert(0, "Локальные правила покрывают отдельные сценарии. Для оценки всего ТЗ нужен полный ИИ-аудит.")
    if omitted:
        notices.append(f"Записей модели исключено после проверки — {omitted}")
    if replaced_quotes:
        notices.append(f"Вместо неточных цитат приведены исходные блоки — {replaced_quotes}")
    if counts["blocker"]:
        readiness = "blocked"
        verdict = "Начинать разработку затронутых сценариев и фиксировать их приёмочные тесты пока рано."
    elif rules_only:
        readiness = "limited"
        verdict = "Для вывода о готовности документа требуется полный аудит."
    elif notices or counts["major"] or any(check["outcome"] != "ok" for check in checks):
        readiness = "clarify"
        verdict = "Разработку и тестирование затронутых сценариев можно планировать после уточнения перечисленных условий."
    else:
        readiness = "ready"
        verdict = "По результатам прогона можно начинать разработку и тестирование описанного поведения."
    return {"schema_version": 1, "mode": "rules" if rules_only else "gemini",
            **({} if rules_only else {"provider": provider_name()}),
            "document": title or path.name, "file": path.name, "sha256": digest,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "version": run_version(), "passes": [{"stage": stage, "model": model} for stage, model in passes],
            "warnings": notices, "requirements": requirements, "findings": findings, "checks": checks,
            **({"unreviewed_figures": True} if "unreviewed_figures" in warnings else {}),
            **({"visual_review": visual_coverage} if visual_coverage else {}),
            "references": reference_payload(blocks, extension, page_spans),
            "external_references": external_reference_payload(blocks, extension, page_spans),
            **({"pdf_coverage": pdf_coverage} if pdf_coverage else {}),
            **({"pdf_origin": pdf_origin} if pdf_origin else {}),
            "counts": counts, "readiness": readiness, "verdict": verdict}


def render_review(audit):
    requirements, findings, counts = (audit[key] for key in ("requirements", "findings", "counts"))
    rules_only = audit["mode"] == "rules"
    mode = "Локальные правила SanA1" if rules_only else "Модель и правила SanA1"
    lines = ["# Отчёт о проверке требований", "", "## Паспорт прогона", "",
             f"- Документ — {md(audit['document'])}", f"- Исходный файл — {md(audit['file'])}",
             f"- SHA-256 исходного файла — {audit['sha256']}", f"- Дата и время — {audit['generated_at']}",
             f"- Версия SanA1 (Git) — {audit['version']}", f"- Режим — {mode}"]
    lines.extend(f"- {stage['stage']} — {md(stage['model'])}" for stage in audit["passes"])
    if audit["warnings"]:
        lines.extend(["", "## Ограничения и проверка доказательств", ""])
        lines.extend(f"- {md(warning)}" for warning in audit["warnings"])
    if coverage := audit.get("pdf_coverage"):
        lines.extend(["", f"Страниц PDF с читаемым текстом — {coverage['total'] - len(coverage['unread'])} из {coverage['total']}."])

    lines.extend(["", "## Выделенные требования", "",
                  "| ID отчёта | ID в источнике | Краткая формулировка | Источник |",
                  "| --- | --- | --- | --- |"])
    for item in requirements:
        lines.append(f"| {item['id']} | {md(item['source_id'] or 'Без номера')} | {md(item['summary'])} | "
                     f"{item['source']['location']} |")
    if not requirements:
        lines.extend(["", "При разборе по формальным признакам отдельные требования не выделены."])
    detail_title = "Разбор выделенных требований" if rules_only else "Проверка каждого требования"
    lines.extend(["", f"## {detail_title}", ""])
    for item in requirements:
        source = item["source"]
        cited = source["location"] + (f", {md(source['section'])}" if source["section"] else "")
        lines.extend([f"### {item['id']} {md(item['summary'])}", "", f"> {md(source['quote'])}", "",
                      f"- Источник — {cited}", f"- Оценка — {md(item['assessment'])}",
                      f"- Связанные нарушения — {', '.join(item['findings']) or '—'}", ""])

    lines.extend(["## Проверка набора требований", "",
                  "| Критерий | Результат | Основание |", "| --- | --- | --- |"])
    for check in audit["checks"]:
        citations = ", ".join(source["location"] for source in check["evidence"])
        basis = f" ({citations})" if citations else ""
        lines.append(f"| {check['criterion']} | {check['status']} | {md(check['comment'])}{basis} |")

    if references := audit.get("references"):
        lines.extend(["", "### Внутренние ссылки", "",
                      "| Пункт | Статус | Откуда ссылаются | Объявления |", "| --- | --- | --- | --- |"])
        for link in references:
            origins = ", ".join(item["location"] for item in link["origins"])
            targets = ", ".join(item["location"] for item in link["declarations"]) or "—"
            lines.append(f"| {md(link['target'])} | {link['label']} | {origins} | {targets} |")

    if external := audit.get("external_references"):
        outcomes = {item["url"]: item for item in audit.get("external_link_checks", [])}
        labels = {"public": "Доступ подтверждён", "unconfirmed": "Публичный доступ не подтверждён",
                  "unavailable": "Ответ недоступен", "blocked": "Адрес недоступен для публичной проверки",
                  "redirect": "Получено перенаправление", "manual": "Проверить вручную"}
        lines.extend(["", "### Внешние ссылки", "",
                      "| Адрес | Источник | Проверка доступа |", "| --- | --- | --- |"])
        for link in external:
            outcome = outcomes.get(link["url"])
            method = (f"{labels[outcome['status']]} · {outcome['checked_at']}" if outcome
                      else "Доступ не проверен" if link["check"] == "github" else "Проверить вручную")
            lines.append(f"| {md(link['url'])} | {', '.join(link['origins'])} | {method} |")

    lines.extend(["", "## Найденные нарушения", ""])
    if not findings:
        summary = ("Локальные правила не нашли нарушений в поддерживаемых сценариях." if rules_only
                   else "В завершённом прогоне нарушения не зафиксированы.")
        lines.extend([summary, ""])
    for item in findings:
        lines.extend([f"### {item['id']} {item['criterion']}", "",
                      f"- Приоритет — {item['priority']}", f"- Обнаружено — {item['engine']}",
                      f"- Нарушение — {md(item['explanation'])}",
                      f"- Требования — {', '.join(item['requirements']) or 'см. места в документе ниже'}",
                      f"- Вопрос автору — {md(item['question'])}",
                      f"- Что уточнить или исправить — {md(item['next_step'])}", ""])
        if item.get("confidence") == "low":
            lines.extend(["- Уверенность — низкая. Проверьте по источнику.", ""])
        if figure := item.get("visual_evidence"):
            observation = figure.get("observed")
            description = md(observation) if observation is not None else (
                f"{md(figure['event'])} · на схеме {md(figure['figure_status'])}, в таблице {md(figure['table_status'])}.")
            lines.extend([f"- Рисунок {figure['number']}, чтение ИИ — {description}", ""])
        for source in item["evidence"]:
            lines.extend([f"> {source['location']} — {md(source['quote'])}", ""])
    lines.extend(["## Вопросы автору ТЗ", "", *author_question_lines(findings, include_answers=False)])
    critical = [f"{item['id']} — {md(item['explanation'])}" for item in findings
                if item["severity"] == "blocker"]
    lines.extend(["## Сводка и готовность к разработке", "",
                  f"- Требований — {len(requirements)}",
                  f"- Нарушений — {len(findings)}",
                  f"- Блокирующих — {counts['blocker']}, существенных — {counts['major']}, низкого приоритета — {counts['minor']}",
                  "- Критичные дефекты — " + (" · ".join(critical) or "не зафиксированы"), ""])
    lines.extend([audit["verdict"], "", "### Первые шаги", ""])
    if findings:
        for item in findings[:3]:
            lines.append(f"- **{item['id']}** — {md(item['next_step'])}")
    elif rules_only:
        lines.append("- Запустить полный ИИ-аудит и сверить требования с владельцем документа.")
    elif audit["readiness"] == "clarify":
        lines.append("- Уточнить основания неполных проверок и повторить проверку документа.")
    else:
        lines.append("- Согласовать сценарии с владельцем требований и использовать указанные критерии приёмки.")
    return "\n".join(lines) + "\n"


def author_question_lines(findings, *, include_answers):
    if not findings:
        return ["Вопросов по результатам прогона нет.", ""]
    lines = []
    for item in findings:
        locations = ", ".join(dict.fromkeys(source["location"] for source in item["evidence"]))
        lines.extend([f"### {item['id']} · {item['priority']}", "",
                      f"- Места в ТЗ — {locations}", f"- {md(item['question'])}"])
        if include_answers:
            lines.append("- Ответ: ____________________")
        lines.append("")
    return lines


def audit_document(input_path, source, model=None, *, rules_only=False, pdf_origin=None):
    return completed_steps(audit_document_steps(input_path, source, model, rules_only=rules_only, pdf_origin=pdf_origin))


def audit_document_steps(input_path, source, model=None, *, rules_only=False, pdf_origin=None,
                         stream=False, check_links=False, edited_figures=None, allow_rules_fallback=False,
                         unavailable_reason=None, previous=None, snapshot=None):
    yield {"stage": "read", "file": input_path.name, "bytes": len(source)} if allow_rules_fallback else "read"
    extension = input_path.suffix.lower().removeprefix(".")
    if extension == "markdown":
        extension = "md"
    document = extract_document(extension, source, preserve_boundary_lines=True, include_previews=False,
                                include_audit_figures=not rules_only and (extension == "docx" or
                                    extension == "pdf" and allow_rules_fallback))
    options = {"table_rows": document["table_rows"], "rules_only": rules_only}
    fallback = unavailable_reason
    try:
        if stream or previous or snapshot is not None:
            result = yield from review_requirements_steps(document["text"], extension, model, detailed=allow_rules_fallback,
                                                          previous=previous, snapshot=snapshot, **options)
        else:
            result = review_requirements(document["text"], extension, model, **options)
    except ValueError as error:
        fallback = str(error)
        if rules_only or not allow_rules_fallback or not fallback.startswith("gemini_"):
            raise
        rules_only = True
        yield "rules"
        result = review_requirements(document["text"], extension, rules_only=True, table_rows=document["table_rows"])
    visual = None
    if not rules_only and (figures := document.get("figures") or edited_figures):
        yield "figures"
        primary = configured_models(DEFAULT_MODEL, DEFAULT_FALLBACK, model)[0]
        visual = review_figures(figures, result[1], primary)
        if allow_rules_fallback and visual[1]["status"] == "skipped":
            visual = review_diagram_text(figures, result[1], primary)
    yield "references"
    audit = build_audit(result, input_path, extension, hashlib.sha256(source).hexdigest(),
                       document["warnings"], document["page_spans"], rules_only=rules_only,
                       pdf_coverage=document.get("pdf_coverage"), pdf_origin=pdf_origin, visual=visual)
    if check_links and audit["external_references"]:
        audit["external_link_checks"] = check_audit_links(audit["external_references"], include_public_web=True) if allow_rules_fallback else check_audit_links(audit["external_references"])
    if fallback:
        audit["ai_unavailable"] = fallback
        audit["warnings"].append("ИИ-проверка недоступна, выполнены только правила.")
    if allow_rules_fallback:
        yield {"stage": "verified", "requirements": len(audit["requirements"]), "findings": len(audit["findings"]),
               "tables": sum(block.kind == "table_header" for block in result[1].values()),
               "links": len(audit["external_references"])}
    yield "report"
    return audit


def review_file(input_path, output_path, model=None, *, rules_only=False, unified=False, answers_path=None,
                json_path=None):
    extension = output_path.suffix.lower()
    if extension not in {".md", ".json"}:
        raise ValueError("invalid_output")
    occupied = [input_path]
    for path, error in ((output_path, "same_file"), (answers_path, "same_answers_file"), (json_path, "same_json_file")):
        if path is None:
            continue
        if any(path.resolve() == used.resolve() or
               (path.exists() and used.exists() and path.samefile(used)) for used in occupied):
            raise ValueError(error)
        if path.exists() and not path.is_file():
            raise OSError(f"Путь для результата должен указывать на файл — {path}")
        occupied.append(path)
    with input_path.open("rb") as stream:
        source = stream.read(MAX_UPLOAD + 1)
    audit = completed_steps(audit_document_steps(input_path, source, model, rules_only=rules_only,
                                                 check_links=unified, allow_rules_fallback=unified))
    encoded = json.dumps(audit, ensure_ascii=False, indent=2) + "\n" if extension == ".json" or json_path else None
    files = {}
    if json_path is not None:
        files[json_path] = encoded
    if answers_path is not None:
        questions = ["# Вопросы автору ТЗ", "", f"Документ — {md(audit['document'])}", "",
                     *author_question_lines(audit["findings"], include_answers=True)]
        files[answers_path] = "\n".join(questions) + "\n"
    files[output_path] = render_review(audit) if extension == ".md" else encoded
    write_review_files(files)
    return audit


def write_review_files(files):
    with ExitStack() as cleanup:
        staged = {}
        for target, content in files.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            directory = Path(cleanup.enter_context(tempfile.TemporaryDirectory(dir=target.parent)))
            pending = directory / "new"
            pending.write_text(content, encoding="utf-8", newline="\n")
            backup = None
            if len(files) > 1 and target.exists():
                backup = directory / "previous"
                shutil.copy2(target, backup)
            staged[target] = pending, backup

        published = []
        try:
            for target, (pending, _) in staged.items():
                os.replace(pending, target)
                published.append(target)
        except OSError:
            for target in reversed(published):
                backup = staged[target][1]
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(backup, target)
            raise
