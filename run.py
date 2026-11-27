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
    args = parser.parse_args()
    if args.rules_only and args.model:
        parser.error("--rules-only cannot be used with --model")
    try:
        answers_path = args.output.with_suffix(".answers.md") if args.answers else None
        audit = review_file(args.input, args.output, args.model, rules_only=args.rules_only, unified=True,
                            answers_path=answers_path)
    except (ValueError, OSError) as error:
        parser.exit(2, "Проверка прервана — " + ERRORS.get(str(error), str(error)) + "\n")
    print(f"Отчёт сохранён — {args.output.resolve()}")
    if answers_path is not None:
        print(f"Вопросы автору сохранены — {answers_path.resolve()}")
    if reason := audit.get("ai_unavailable"):
        parser.exit(3, "Сохранён отчёт по правилам — " + ERRORS.get(reason, reason) + "\n")


if __name__ == "__main__":
    main()
