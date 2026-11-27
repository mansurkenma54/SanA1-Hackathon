"""Verify reports against six labeled BCC-HUB findings and their corrected variants."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from hackathon_cli import audit_document


OFFICIAL_SHA256 = "e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381"
CONTROLS = (
    ("Месяц покупки", {38, 64}, 64, "Февральский", "Январский"),
    ("Повторное уведомление", {39, 40}, 40,
     "независимо от истории предыдущей настройки", "с учётом месячного ограничения"),
    ("Контракт чтения", {52, 103, 120}, 52, "Приложение читает и сохраняет настройки",
     "GET /alerts/getLimit читает текущие настройки без изменения. Приложение читает и сохраняет настройки"),
    ("Изменение через GET", {104, 120}, 104, "GET", "PATCH"),
    ("Статусы валидации", {151, 162, 170}, 171,
     '{"result":"ERROR","message":"Проверьте сумму"}', '{"result":"OK","amount":"50000","enabled":"1"}'),
    ("Область применения 403", {174, 189}, 188, "403. Unsuccessful — Forbidden", "404. Not found"),
)


def score(audit, text, controls):
    lines = text.splitlines()
    evidence = [item["source"] for item in audit["requirements"]]
    evidence.extend(source for item in audit["findings"] + audit["checks"] for source in item["evidence"])
    if not all(1 <= item["line"] <= item["end"] <= len(lines) and item["quote"] and
               item["quote"] in "\n".join(lines[item["line"] - 1:item["end"]]) for item in evidence):
        raise ValueError("В отчёте есть цитата, не совпадающая с указанными строками.")
    actual = {item["id"]: {source["line"] for source in item["evidence"]} for item in audit["findings"]}
    matched = set()
    missing = []
    for title, expected, *_ in controls:
        candidates = [item["id"] for item in audit["findings"] if expected <= actual[item["id"]]
                      and (title != "Повторное уведомление" or item["criterion"] != "Прослеживаемость")]
        if len(candidates) != 1 or candidates[0] in matched:
            missing.append(title)
        else:
            matched.add(candidates[0])
    return missing, sorted(actual.keys() - matched), len(evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to the official requirements.md.")
    parser.add_argument("--report", type=Path, help="Score a JSON audit from the CLI or web API.")
    args = parser.parse_args()
    try:
        data = args.input.read_bytes()
        text = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except (OSError, UnicodeError) as error:
        parser.error(str(error))
    if sha256(text.encode("utf-8")).hexdigest() != OFFICIAL_SHA256:
        parser.error("Этот набор привязан к опубликованной версии requirements.md с известной разметкой.")
    if args.report:
        try:
            result = json.loads(args.report.read_text(encoding="utf-8-sig"))
            audit = result.get("review", result)
            if audit["schema_version"] != 1 or audit["sha256"] != sha256(data).hexdigest():
                raise ValueError("Отчёт относится к другому входному файлу или версии формата.")
            missing, additional, citations = score(audit, text, CONTROLS)
        except (AttributeError, KeyError, OSError, TypeError, ValueError) as error:
            parser.error(str(error))
        print(f"Режим — {audit['mode']}. Контрольные ситуации — {len(CONTROLS) - len(missing)} из {len(CONTROLS)}.")
        print(f"Цитат сверено — {citations}. Замечания вне разметки — {', '.join(additional) or 'нет'}.")
        if missing:
            print("Не подтверждены — " + ", ".join(missing))
        return int(bool(missing))

    def matches_controls(source, controls):
        audit = audit_document(args.input, source.encode("utf-8"), rules_only=True)
        missing, _, _ = score(audit, source, controls)
        removed = [control for control in CONTROLS if control not in controls]
        removed_are_absent = all(not set(control[1]) <= {ref["line"] for ref in item["evidence"]}
                                 or control[0] == "Повторное уведомление" and item["criterion"] == "Прослеживаемость"
                                 for control in removed for item in audit["findings"])
        return not missing and removed_are_absent

    if not matches_controls(text, CONTROLS):
        print("Состав или ссылки нарушений в исходном кейсе изменились.")
        return 1

    lines = text.splitlines()
    corrected = lines.copy()
    for index, (title, _, line, before, after) in enumerate(CONTROLS):
        variant = lines.copy()
        if before not in lines[line - 1]:
            parser.error(f"Исходное значение для исправления не найдено — {title}.")
        variant[line - 1] = corrected[line - 1] = lines[line - 1].replace(before, after, 1)
        remaining = CONTROLS[:index] + CONTROLS[index + 1:]
        if not matches_controls("\n".join(variant), remaining):
            print(f"Исправленный вариант не прошёл проверку — {title}")
            return 1
        print(f"Проверено — {title}")
    if not matches_controls("\n".join(corrected), ()):
        print("После исправлений остались сигналы из шести исходных контролей.")
        return 1
    print("Исходный кейс — 6 из 6. Исправленные варианты — 6 из 6. После исправлений — 0 из шести исходных сигналов.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
