"""Run the workspace audit from the command line."""

import argparse
from pathlib import Path

from hackathon_cli import ERRORS, review_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--rules-only", action="store_true")
    parser.add_argument("--answers", action="store_true", help="Write a separate .answers.md worksheet.")
    parser.add_argument("--json", action="store_true", help="Save the same audit beside the Markdown report as .json.")
    parser.add_argument("--language", default="auto",
                        help="Markdown report language: auto follows the input; use ru for the competition, kk, en, or a language name.")
    args = parser.parse_args()
    if args.rules_only and args.model:
        parser.error("--rules-only cannot be used with --model")
    try:
        from report_language import normalize_report_language
        language = normalize_report_language(args.language)
        if (args.rules_only or args.output.suffix.lower() == ".json") and language not in {"auto", "ru"}:
            parser.error("--language requires a full model audit and a Markdown output path")
        answers_path = args.output.with_suffix(".answers.md") if args.answers else None
        json_path = args.output.with_suffix(".json") if args.json and args.output.suffix.lower() != ".json" else None
        audit = review_file(args.input, args.output, args.model, rules_only=args.rules_only, unified=True,
                            answers_path=answers_path, json_path=json_path, language=language)
    except (ValueError, OSError) as error:
        parser.exit(2, "Проверка прервана — " + ERRORS.get(str(error), str(error)) + "\n")
    print(f"Отчёт сохранён — {args.output.resolve()}")
    if answers_path is not None:
        print(f"Вопросы автору сохранены — {answers_path.resolve()}")
    if json_path is not None:
        print(f"JSON того же прогона сохранён — {json_path.resolve()}")
    if (args.rules_only or audit.get("ai_unavailable")) and args.output.suffix.lower() == ".md":
        print("Сохранена русская версия по локальным правилам. Для перевода нужен ИИ-провайдер.")
    if reason := audit.get("ai_unavailable"):
        parser.exit(3, "Сохранён отчёт по правилам — " + ERRORS.get(reason, reason) + "\n")


if __name__ == "__main__":
    main()
