"""SanA1 web app and local command-line evaluation."""

import argparse
import json
import os
from http.client import HTTPException
from pathlib import Path
import sys
from urllib.parse import unquote

from flask import Flask, Response, jsonify, redirect, request, send_from_directory
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from analyzer import LOCAL_CODES, MAX_TEXT, analysis_events, analyze, verify_findings
from document_input import FILE_TYPES, MAX_PAGES, MAX_UPLOAD, extract_document, pdf_page_preview
from examples import AUDIT_DEMO, CASES, WORKSPACE_EXAMPLES, evaluate, evaluation_events, score_case
from gemini import ClarificationNeeded, enhance, is_configured, propose_correction
from organizer_input import OFFICIAL_SHA256, SOURCE_URL, official_input_bytes
from public_links import check_public_repository, github_repository
from review_guidance import GUIDANCE
from review_snapshot import MAX_TOKEN, read_snapshot, sign_snapshot
from word_output import MIME as DOCX_MIME, build_word, edited_audit_figures


PUBLIC = Path(__file__).resolve().parent / "public"
ASSETS = {"app.js", "strings.js", "document-view.js", "styles.css", "brand-mark.png", "favicon.png", "display.woff2"}
ASSETS.update({"transfer-case-en.docx", "transfer-case-ru.docx", "qr-refund-demo.docx"})
ASSETS.update({"spec-profiles.js", "word-export.js", "document-focus.css", "correction.css", "standards.css"})
ASSETS.update({"audit-view.js", "audit-compare.js", "audit-repair.js", "audit.css", "workspace.css"})
ASSETS.update({"workspace-session.js", "hero-field.js"})
MAX_JSON = 6 * MAX_TEXT + 4096
MAX_REPORT_JSON = 12 * MAX_TEXT + 4096  # A Unicode code point can be two escaped UTF-16 units.
LOCAL_REVIEW_ROUTE = "/api/analyze"
GEMINI_REVIEW_ROUTE = "/api/analyze/gemini"
REPORT_OPERATION = "report"
REPORT_TEXT_TYPES = {"md", "markdown", "txt"}
DEFAULT_REPORT_FILENAME = "requirements.md"
REPORT_DOWNLOAD_FILENAME = "sana1-requirements-review.md"
OFFICIAL_REPORT_PATH = "/reports/official.md"
REVIEW_STREAM = "application/x-ndjson"
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
app.json.ensure_ascii = False


def gemini_available():
    return is_configured()


def accepts_events():
    return request.accept_mimetypes.best_match(("application/json", REVIEW_STREAM)) == REVIEW_STREAM


def record(event):
    return json.dumps(event, ensure_ascii=False) + "\n"


@app.after_request
def response_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    return response


@app.before_request
def check_origin():
    origin = request.headers.get("Origin")
    scheme = "https" if os.environ.get("VERCEL") else request.scheme
    if request.method == "POST" and origin and origin != f"{scheme}://{request.host}":
        return {"error": "origin_rejected"}, 403


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(_error):
    uploads_file = request.path == "/api/extract" or request.mimetype == "application/octet-stream"
    return {"error": "file_too_large" if uploads_file else "text_too_long"}, 413


@app.errorhandler(BadRequest)
def invalid_request(_error):
    return {"error": "invalid_request"}, 400


@app.get("/")
@app.get("/workspace")
def index():
    return send_from_directory(PUBLIC, "index.html")


@app.get("/evaluation")
def legacy_workspace():
    return redirect("/workspace", code=308)


@app.get(OFFICIAL_REPORT_PATH)
def official_report():
    return send_from_directory(PUBLIC, "reports/official.md", mimetype="text/plain")


@app.get("/api/official-input")
def official_input():
    try:
        source = official_input_bytes()
    except (OSError, HTTPException, ValueError):
        return {"error": "official_input_unavailable", "source": SOURCE_URL}, 503
    return Response(source, content_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": 'inline; filename="requirements.md"'})


@app.get("/<path:name>")
def static_asset(name):
    if name not in ASSETS:
        return {"error": "not_found"}, 404
    # Windows registry MIME mappings can disagree with Python's JS module type.
    return send_from_directory(PUBLIC, name, mimetype="text/javascript" if name.endswith(".js") else None)


@app.get("/api/config")
def config():
    return {"gemini": gemini_available(), "max_chars": MAX_TEXT, "max_upload": MAX_UPLOAD}


@app.get("/api/public-link")
def public_link():
    url = request.args.get("url", "")
    try:
        repository = github_repository(url) if len(url) <= 180 else None
    except ValueError:
        repository = None
    if repository is None:
        return {"status": "manual"}
    return {"status": check_public_repository(*repository)}


@app.get("/api/audit-contract")
def audit_contract():
    """Describe the same Russian audit the workspace and CLI produce."""
    from hackathon_cli import MARKDOWN_MIME

    return {
        "contract_version": 1,
        "method": "POST",
        "example_report": {"method": "GET", "path": OFFICIAL_REPORT_PATH, "language": "ru"},
        "organizer_input": {"method": "GET", "path": "/api/official-input", "url": SOURCE_URL,
                            "sha256": OFFICIAL_SHA256},
        "endpoints": {
            "gemini": {"path": f"{GEMINI_REVIEW_ROUTE}?operation={REPORT_OPERATION}", "requires_server_key": True},
            "rules": {"path": f"{LOCAL_REVIEW_ROUTE}?operation={REPORT_OPERATION}", "requires_server_key": False},
            "workspace": {"path": f"{GEMINI_REVIEW_ROUTE}?operation={REPORT_OPERATION}&fallback=rules",
                          "requires_server_key": False, "fallback_field": "review.ai_unavailable"},
        },
        "inputs": {
            "application/json": {"required": ["text"], "defaults": {"filename": DEFAULT_REPORT_FILENAME},
                                 "extensions": sorted(REPORT_TEXT_TYPES),
                                 "pdf_origin": "Optional {total, unread} from prior PDF extraction when auditing edited text.",
                                 "figures": "Optional list of up to four JPEG previews referred to in the edited text by attachment ID.",
                                 "example": {"text": "Ф-1. Сервис хранит отчёт 30 дней.",
                                             "filename": DEFAULT_REPORT_FILENAME}},
            "application/octet-stream": {"required_headers": ["X-File-Name"],
                                         "extensions": sorted(FILE_TYPES | REPORT_TEXT_TYPES)},
        },
        "outputs": {
            "language": "ru",
            REVIEW_STREAM: {"events": ["stage", "result", "error"], "result_field": "report"},
            "application/json": {"fields": ["review", "markdown"], "report_version_field": "review.schema_version",
                                 "sha256_field": "review.sha256"},
            MARKDOWN_MIME: {"filename": REPORT_DOWNLOAD_FILENAME},
            "default_by_input": {"application/json": "application/json", "application/octet-stream": MARKDOWN_MIME},
        },
        "limits": {"max_chars": MAX_TEXT, "max_upload_bytes": MAX_UPLOAD, "max_pdf_pages": MAX_PAGES},
    }


@app.get("/api/guidance")
def guidance():
    return GUIDANCE


@app.get("/api/example")
def example():
    if request.args.get("case") == "audit":
        return {"text": AUDIT_DEMO, "filename": "virtual-card-demo.md"}
    return {"text": WORKSPACE_EXAMPLES.get(request.args.get("lang"), WORKSPACE_EXAMPLES["en"])}


@app.get("/api/evaluate")
def evaluation():
    if accepts_events():
        return Response(map(record, evaluation_events()), mimetype=REVIEW_STREAM)
    return evaluate()


@app.get("/api/evaluate/fixtures")
def fixtures():
    return {"cases": [{"id": name, "text": text,
                       "expected_findings": [{"code": code, "lines": list(lines)} for code, lines in expected]}
                      for name, text, expected in CASES]}


@app.post("/api/evaluate/case")
def evaluate_case():
    if request.mimetype != "application/json":
        return {"error": "invalid_request"}, 415
    request.max_content_length = MAX_JSON
    payload = request.get_json()
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        return {"error": "invalid_request"}, 400
    text = payload["text"].replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_TEXT:
        return {"error": "text_too_long"}, 413
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return {"error": "invalid_request"}, 400
    entries = payload.get("expected_findings")
    if not isinstance(entries, list) or len(entries) > 350:
        return {"error": "invalid_expectation"}, 422
    line_count = text.count("\n") + 1
    expected = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("code") not in LOCAL_CODES:
            return {"error": "invalid_expectation"}, 422
        lines = entry.get("lines")
        if (not isinstance(lines, list) or not lines
                or any(type(line) is not int or not 1 <= line <= line_count for line in lines)
                or len(set(lines)) != len(lines)):
            return {"error": "invalid_expectation"}, 422
        key = (entry["code"], tuple(sorted(lines)))
        if key in expected:
            return {"error": "invalid_expectation"}, 422
        expected.add(key)
    try:
        return score_case("custom", text, expected)
    except ValueError as error:
        return {"error": str(error)}, 422


@app.post("/api/extract")
def extract():
    if request.mimetype != "application/octet-stream":
        return {"error": "invalid_request"}, 415
    try:
        extension = request.headers.get("X-File-Type", "").lower()
        data = request.get_data(cache=False)
        page = request.args.get("page")
        if page is not None:
            if extension != "pdf" or len(page) > 2 or not page.isascii() or not page.isdecimal() or not 1 <= int(page) <= MAX_PAGES:
                raise ValueError("invalid_page")
            return pdf_page_preview(data, int(page))
        document = extract_document(extension, data, allow_scan_preview=request.args.get("view") == "pdf")
    except ValueError as error:
        code = str(error)
        if not code.replace("_", "").isalnum() or len(code) > 48:
            code = "invalid_document"
        return {"error": code}, 413 if code in ("file_too_large", "text_too_long") else 422
    return document


@app.post("/api/export/docx")
def export_word():
    if request.mimetype != "application/json":
        return {"error": "invalid_request"}, 415
    payload = request.get_json()
    try:
        binary = build_word(payload)
    except ValueError as error:
        code = str(error)
        if code not in ("invalid_request", "text_too_long", "invalid_document"):
            code = "invalid_document"
        return {"error": code}, 413 if code == "text_too_long" else 422
    return Response(binary, mimetype=DOCX_MIME,
                    headers={"Content-Disposition": 'attachment; filename="SanA1-specification.docx"'})


@app.post(LOCAL_REVIEW_ROUTE)
@app.post(GEMINI_REVIEW_ROUTE)
def review():
    gemini_route = request.path == GEMINI_REVIEW_ROUTE
    operation = request.args.get("operation")
    if operation == "correction" and gemini_route:
        return handle_correction()
    if operation == REPORT_OPERATION:
        return download_requirements_report(rules_only=not gemini_route)
    if request.mimetype != "application/json":
        return {"error": "invalid_request"}, 415
    request.max_content_length = MAX_JSON
    payload = request.get_json()
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        return {"error": "invalid_request"}, 400
    doc = payload["text"].replace("\r\n", "\n").replace("\r", "\n")
    try:
        doc.encode("utf-8")
    except UnicodeEncodeError:
        return {"error": "invalid_request"}, 400
    locale = payload.get("locale", "en")
    if locale == "kk":
        locale = "ru"
    mode = "gemini" if gemini_route else payload.get("mode", "local")
    if locale not in ("en", "ru") or mode not in ("local", "gemini"):
        return {"error": "invalid_request"}, 400
    # The Vercel firewall limits only the dedicated provider route.
    use_model = mode == "gemini" and (gemini_route or not os.environ.get("VERCEL")) and gemini_available()
    if accepts_events():
        return Response(review_stream(doc, locale, mode, use_model), mimetype=REVIEW_STREAM)
    try:
        report = analyze(doc)
    except ValueError as error:
        return {"error": str(error)}, 413 if str(error) == "text_too_long" else 422
    return finalize_review(finish_review(report, doc, mode, use_model, locale), doc, locale)


def download_requirements_report(*, rules_only):
    from hackathon_cli import MARKDOWN_MIME, audit_document_steps, completed_steps, render_review, run_version

    text_request = request.mimetype == "application/json"
    if not text_request and request.mimetype != "application/octet-stream":
        return {"error": "invalid_request"}, 415
    try:
        path, source, pdf_origin, figures, token = report_input(text_request=text_request)
        streaming = accepts_events()
        unified = request.args.get("fallback") == "rules"
        version = run_version() if unified else ""
        snapshot = {} if unified and not rules_only and streaming else None
        steps = audit_document_steps(path, source, rules_only=rules_only, pdf_origin=pdf_origin,
                                     stream=streaming, check_links=True, edited_figures=None if rules_only else figures,
                                     allow_rules_fallback=unified,
                                     unavailable_reason="provider_route" if rules_only and unified and
                                     request.args.get("provider_unavailable") == "1" else None,
                                     previous=read_snapshot(token, version) if snapshot is not None else None,
                                     snapshot=snapshot)
        if streaming:
            return Response(requirements_report_stream(steps, render_review, snapshot, version), mimetype=REVIEW_STREAM)
        audit = completed_steps(steps)
    except ValueError as error:
        code = str(error)
        if code == "invalid_request":
            status = 400
        elif code.startswith("gemini_"):
            status = {"gemini_quota": 429, "gemini_unconfigured": 503,
                      "gemini_busy": 503, "gemini_timeout": 504}.get(code, 502)
        else:
            status = 413 if code in {"file_too_large", "text_too_long"} else 422
        return {"error": code}, status
    markdown = render_review(audit)
    accepted = request.accept_mimetypes
    json_priority = accepted["application/json"]
    markdown_priority = accepted[MARKDOWN_MIME]
    if json_priority > markdown_priority or (text_request and json_priority == markdown_priority):
        response = jsonify(review=audit, markdown=markdown)
    else:
        response = Response(markdown, mimetype=MARKDOWN_MIME,
                            headers={"Content-Disposition": f'attachment; filename="{REPORT_DOWNLOAD_FILENAME}"'})
    response.vary.add("Accept")
    return response


def requirements_report_stream(steps, render_review, snapshot=None, version=""):
    while True:
        try:
            stage = next(steps)
        except StopIteration as completed:
            audit = completed.value
            report = {"review": audit, "markdown": render_review(audit)}
            if token := sign_snapshot(snapshot, version):
                report["recheck_token"] = token
            yield record({"type": "result", "report": report})
            return
        except ValueError as error:
            yield record({"type": "error", "error": str(error)})
            return
        yield record({"type": "stage", **(stage if isinstance(stage, dict) else {"stage": stage})})


def report_input(*, text_request):
    if text_request:
        request.max_content_length = MAX_UPLOAD
        payload = request.get_json()
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            raise ValueError("invalid_request")
        token = payload.get("recheck_token")
        if token is not None and (not isinstance(token, str) or len(token) > MAX_TOKEN):
            raise ValueError("invalid_request")
        if "figures" not in payload and len(request.get_data()) > MAX_REPORT_JSON + len(token or ""):
            raise RequestEntityTooLarge()
        name = payload.get("filename", DEFAULT_REPORT_FILENAME)
        if not isinstance(name, str):
            raise ValueError("invalid_request")
        try:
            name.encode("utf-8")
            source = payload["text"].encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("invalid_request") from error
    else:
        name = unquote(request.headers.get("X-File-Name", ""))
    filename = Path(name.replace("\\", "/")).name
    if not filename or len(filename) > 255 or "\0" in filename:
        raise ValueError("invalid_request")
    path = Path(filename)
    if text_request:
        if path.suffix.lower().removeprefix(".") not in REPORT_TEXT_TYPES:
            raise ValueError("unsupported_file")
        figures = edited_audit_figures(payload["text"], payload.get("figures", []))
        return path, source, report_pdf_origin(payload.get("pdf_origin")), figures, token
    return path, request.get_data(cache=False), None, [], None


def report_pdf_origin(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("invalid_request")
    total, unread = value.get("total"), value.get("unread")
    if (type(total) is not int or not 2 <= total <= MAX_PAGES or not isinstance(unread, list)
            or not 1 <= len(unread) < total or any(type(page) is not int or not 1 <= page <= total for page in unread)
            or len(set(unread)) != len(unread)):
        raise ValueError("invalid_request")
    return {"total": total, "unread": sorted(unread)}


@app.post("/api/correction/propose")
def correction_proposal():
    if os.environ.get("VERCEL"):
        # Keep every billed provider request behind the same public firewall rule.
        return redirect("/api/analyze/gemini?operation=correction", code=307)
    return handle_correction()


def handle_correction():
    if request.mimetype != "application/json":
        return {"error": "invalid_request"}, 415
    request.max_content_length = MAX_JSON * 2 + 18_000
    try:
        return propose_correction(request.get_json())
    except ClarificationNeeded as error:
        response = {"error": "clarification_needed"}
        if error.question:
            response["question"] = error.question
        return response, 422
    except ValueError as error:
        code = str(error)
        status = {"invalid_request": 400, "text_too_long": 413,
                  "gemini_quota": 429, "gemini_unconfigured": 503, "gemini_busy": 503, "gemini_timeout": 504}
        if code not in status and code not in {"gemini_access", "gemini_model", "gemini_unavailable", "gemini_invalid_response"}:
            code = "gemini_unavailable"
        return {"error": code}, status.get(code, 502)


def finish_review(report, doc, mode, use_model, locale):
    report["warnings"] = []
    if use_model:
        try:
            extra, discarded, model = enhance(doc, locale, report["findings"])
            report["findings"].extend(extra)
            report["engine"] = "gemini"
            report["model"] = model
            if discarded:
                report["warnings"].append("gemini_unverified_findings")
        except ValueError as error:
            report["warnings"].append(str(error))
    elif mode == "gemini":
        report["warnings"].append("gemini_unconfigured")
    return report


def finalize_review(report, doc, locale):
    original = report["findings"]
    report["findings"] = verify_findings(doc, original)
    report["verification"] = {"verified_quotes": sum(len(item["evidence"]) for item in report["findings"]),
                              "excluded_findings": len(original) - len(report["findings"])}
    report["locale"] = locale
    for item in report["findings"]:
        guide = GUIDANCE[locale][item["code"]].copy()
        if item.get("explanation"):
            guide["description"] = item["explanation"]
        for field in ("question", "recommendation", "acceptance_test"):
            if item.get(field):
                guide[field] = item[field]
        item["guidance"] = guide
    return report


def review_stream(doc, locale, mode, use_model):
    try:
        for event in analysis_events(doc):
            if event["type"] == "result":
                if use_model:
                    rules = event["report"]
                    yield record({"type": "stage", "step": "model", "sections": rules["statistics"]["sections"],
                                  "findings": len(rules["findings"])})
                report = finish_review(event["report"], doc, mode, use_model, locale)
                yield record({"type": "stage", "step": "verify"})
                event["report"] = finalize_review(report, doc, locale)
            yield record(event)
    except ValueError as error:
        yield record({"type": "error", "error": str(error)})


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--port", type=int, default=8765)
    cli.add_argument("--evaluate", action="store_true", help="Run the labeled fixtures and exit.")
    cli.add_argument("--input", type=Path, help="Path to a requirements document.")
    cli.add_argument("--output", type=Path, help="Path to the Russian review (.md or .json).")
    cli.add_argument("--model", help="Override the model for the configured provider.")
    cli.add_argument("--rules-only", action="store_true", help="Audit with local rules without calling a model.")
    args = cli.parse_args()
    if args.input is not None or args.output is not None or args.model is not None or args.rules_only:
        if args.input is None or args.output is None or args.evaluate:
            cli.error("--input and --output are required together and cannot be combined with --evaluate.")
        if args.rules_only and args.model is not None:
            cli.error("--rules-only and --model select different review modes.")
        from hackathon_cli import ERRORS, review_file

        try:
            review_file(args.input, args.output, args.model, rules_only=args.rules_only)
        except ValueError as error:
            message = ERRORS.get(str(error), "не удалось сформировать проверенный отчёт")
            print(f"Проверка прервана: {message}.", file=sys.stderr)
            return 1
        except OSError as error:
            print(f"Проверка прервана: {error}.", file=sys.stderr)
            return 1
        print(f"Отчёт сохранён: {args.output}")
        return 0
    if args.evaluate:
        report = evaluate()
        print(json.dumps(report, indent=2))
        return 0 if report["passed"] == len(report["cases"]) else 1
    app.run(host="127.0.0.1", port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
