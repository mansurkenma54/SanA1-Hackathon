"""Verify the evidence for the 15 acceptance rows on the published organizer input."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

from hackathon_cli import audit_document
from tools.check_official_case import OFFICIAL_SHA256, score


# Each row requires one or more distinct decisions. A reference alone does not count.
CONTROLS = (
    ("Месяц покупки", (({38, 64}, r"в какой месяц|какая дата"),)),
    ("Повторный push и месячный лимит", (({39, 40}, r"отправлено второй раз|повторн\w+ (?:уведомлен|push)"),)),
    ("Расход уже достиг нового порога", (({40}, r"уже равна новому порогу|уже.{0,55}порог"),)),
    ("Момент доставки, задержка и нагрузка", (({23, 46}, r"процентил.*|нагруз"),)),
    ("Тиыны и хранение enabled", (({49}, r"сравнивать расход и порог"), ({49, 144}, r"где хранится.*enabled"))),
    ("Изменение через GET", (({104, 120}, r"метод должен изменять|метод.*сохран"),)),
    ("Отсутствует отдельный контракт чтения", (({52, 103, 120}, r"читает текущие настройки|для чтения"),)),
    ("200 с ERROR, 400 и недоописанный 201", (({151, 162, 170}, r"статус.*недопустим"), ({151, 165}, r"200.*201"))),
    ("Граница применения 403 и 404", (({174, 189}, r"для каких отказов"),)),
    ("Content-Type без тела и тип amount", (({147, 148}, r"Content-Type"), ({143, 156}, r"строка.*в ответе"))),
    ("Активность карты и валюта", (({37, 118}, r"неактивн.*валют"),)),
    ("Возвраты и незавершённые операции", (({38, 39}, r"возврате после уведомления"), ({38}, r"холд.*валют"))),
    ("Повторная доставка и контракт события", (({52}, r"распознавать повтор события"),)),
    ("Тестирование, согласующие, версия, откат и ИБ",
     (({57, 68, 91}, r"версия.*подтверждает"), ({68, 76, 82}, r"откат.*ИБ"), ({43}, r"экране блокировки"))),
    ("Неполная приёмка", (({39, 40, 61}, r"месячный лимит.*изменение порога"), ({37, 61}, r"граничные значения"),
                         ({38, 52, 61}, r"какие критерии приёмки подтверждают"))),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    source = args.input.read_bytes()
    text = source.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if sha256(text.encode()).hexdigest() != OFFICIAL_SHA256:
        parser.error("Проверка привязана к опубликованной версии документа.")
    if args.report:
        report = json.loads(args.report.read_text(encoding="utf-8-sig"))
        audit = report.get("review", report)
    else:
        audit = audit_document(args.input, source, rules_only=True)
    if audit["schema_version"] != 1 or audit["sha256"] != sha256(source).hexdigest():
        parser.error("Отчёт относится к другому файлу.")
    _, _, citations = score(audit, text, ())
    verified = 0
    for index, (title, decisions) in enumerate(CONTROLS, 1):
        matched = []
        for refs, question in decisions:
            matches = [item["id"] for item in audit["findings"]
                       if refs <= {ref["line"] for ref in item["evidence"]}
                       and re.search(question, item["question"], re.I)]
            if matches:
                matched.append(matches[0])
        complete = len(matched) == len(decisions)
        verified += complete
        marks = ", ".join(dict.fromkeys(matched)) or "—"
        print(f"{index:2}. {title} · {len(matched)}/{len(decisions)} · {marks}")
    print(f"Контрольные темы — {verified}/{len(CONTROLS)}. Дословных цитат — {citations}. Режим — {audit['mode']}.")
    return int(verified != len(CONTROLS))


if __name__ == "__main__":
    raise SystemExit(main())
