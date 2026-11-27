"""Verify labeled QR refund findings for an original or corrected DOCX fixture."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from document_input import extract_document
from hackathon_cli import audit_document
from tools.check_official_case import score


FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
FIXTURE_HASHES = {
    "469689629e334ada5ecd368448a95891697be224509ba6dfdd6ff4ce637d58ec": False,
    "aec280acfb0e0968cb7b7df7b17adee4b67bf287b215f4db9545c20106db6e2a": True,
}
CONTROL_LINES = {
    "Замороженный счёт": {11, 21},
    "Лимит возврата": {9, 74},
    "GET создаёт заявку": {39, 46},
    "Пустой результат приёмки": {72, 75},
    "Подтверждение webhook": {58, 60},
    "Статус на схеме": {55, 68},
}
DIAGRAM = "Статус на схеме"


def assess(audit, text, *, corrected):
    _, _, citations = score(audit, text, ())
    findings = audit["findings"]
    lines = {item["id"]: {evidence["line"] for evidence in item["evidence"]} for item in findings}
    if len(lines) != len(findings):
        raise ValueError("В отчёте повторяется ID замечания.")
    visual = [item for item in findings if item.get("visual_evidence")]
    coverage = audit.get("visual_review", {})
    compared = coverage.get("compared", 0)
    if type(compared) is not int or compared < 0 or compared and coverage.get("status") != "completed":
        raise ValueError("Некорректное число проверенных переходов.")
    if corrected:
        return {"citations": citations, "compared": compared, "visual": len(visual),
                "total": len(findings)}

    matched = set()
    associated = set()
    missing = []
    duplicate = {}
    for name, expected in CONTROL_LINES.items():
        candidates = [item for item in findings if expected <= lines[item["id"]]]
        associated.update(item["id"] for item in candidates)
        if len(candidates) > 1:
            duplicate[name] = [item["id"] for item in candidates]
            continue
        if len(candidates) != 1 or candidates[0]["id"] in matched:
            missing.append(name)
            continue
        item = candidates[0]
        if name == DIAGRAM:
            figure = item.get("visual_evidence", {})
            if (not compared or figure.get("number") != 1 or figure.get("line") != 68
                    or figure.get("figure_status") != "PENDING" or figure.get("table_status") != "SETTLED"):
                missing.append(name)
                continue
        matched.add(item["id"])
    return {"matched": len(matched), "citations": citations, "missing": missing,
            "duplicate": duplicate, "additional": sorted(lines.keys() - associated)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=FIXTURES / "qr-refund-audit.docx")
    parser.add_argument("--report", type=Path, help="Verify an existing JSON report instead of running the local audit.")
    args = parser.parse_args()
    try:
        raw = args.input.read_bytes()
        digest = sha256(raw).hexdigest()
        if digest not in FIXTURE_HASHES:
            raise ValueError("Файл не совпадает с размеченной парой QR DOCX.")
        corrected = FIXTURE_HASHES[digest]
        if args.report:
            payload = json.loads(args.report.read_text(encoding="utf-8-sig"))
            audit = payload.get("review", payload)
        else:
            audit = audit_document(args.input, raw, rules_only=True)
        if audit["schema_version"] != 1 or audit["sha256"] != digest or audit["mode"] not in {"rules", "gemini"}:
            raise ValueError("Отчёт относится к другому файлу, версии формата или режиму.")
        text = extract_document("docx", raw, include_previews=False, preserve_boundary_lines=True)["text"]
        result = assess(audit, text, corrected=corrected)
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as error:
        parser.error(str(error))

    rules = audit["mode"] == "rules"
    print(f"Режим — {audit['mode']}. Версия — {audit['version']}. Цитат сверено — {result['citations']}.")
    if corrected:
        print(f"Исправленный файл. Всего замечаний — {result['total']}. "
              f"Сверено переходов — {result['compared']}. Расхождений схемы — {result['visual']}.")
        if rules:
            return int(result["total"] != 0)
        return int(not result["compared"] or result["visual"] != 0)

    print(f"Контрольный результат — {result['matched']}/{len(CONTROL_LINES)}.")
    for name, ids in result["duplicate"].items():
        print(f"Повтор — {name} ({', '.join(ids)}).")
    if result["missing"]:
        print("Не подтверждены — " + ", ".join(result["missing"]) + ".")
    print("Замечания вне разметки — " + (", ".join(result["additional"]) or "нет") + ".")
    expected_missing = [DIAGRAM] if rules else []
    return int(bool(result["duplicate"]) or result["missing"] != expected_missing
               or rules and bool(result["additional"]))


if __name__ == "__main__":
    raise SystemExit(main())
