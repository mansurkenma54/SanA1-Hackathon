"""Extract readable text from supported document formats."""

from io import BytesIO
from base64 import b64encode
from threading import Lock
from zipfile import BadZipFile, ZipFile
import re

from analyzer import MAX_TEXT


MAX_UPLOAD = 4 * 1024 * 1024
MAX_PAGES = 40
MAX_AUDIT_FIGURES = 4
FILE_TYPES = {"txt", "md", "docx", "pdf"}
PDF_RENDER_LOCK = Lock()
READABLE_TEXT = re.compile(r"[^\W\d_]")
PDF_FIGURE_LINE = re.compile(r"(?:^|\b)(?:рисунок|figure)\s+\d+|\b(?:BPMN|Sequence Diagram|макет интерфейса)\b", re.I)


def thumbnail(image, maximum=(800, 900)):
    from PIL import Image
    if image.width * image.height > 16_000_000:
        raise ValueError("image_too_large")
    image.thumbnail(maximum, Image.Resampling.LANCZOS)
    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, "white")
    background.paste(rgba, mask=rgba.getchannel("A"))
    out = BytesIO()
    background.save(out, "JPEG", quality=72)
    return "data:image/jpeg;base64," + b64encode(out.getvalue()).decode("ascii")


def pdf_previews(data, count=4, *, first=1):
    import pypdfium2 as pdfium
    media = []
    with PDF_RENDER_LOCK, pdfium.PdfDocument(data) as document:
        if len(document) > MAX_PAGES:
            raise ValueError("too_many_pages")
        if not 1 <= first <= len(document):
            raise ValueError("invalid_page")
        for index in range(first - 1, min(first - 1 + count, len(document))):
            page = document[index]
            try:
                width, height = page.get_size()
                if min(width, height) <= 0:
                    continue
                bitmap = page.render(scale=min(1.6, 800 / max(width, height)))
                try:
                    media.append({"page": index + 1, "src": thumbnail(bitmap.to_pil())})
                finally:
                    bitmap.close()
            finally:
                page.close()
    return media


def pdf_page_preview(data, page):
    if not data.startswith(b"%PDF-"):
        raise ValueError("invalid_document")
    try:
        return pdf_previews(data, 1, first=page)[0]
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("invalid_document") from error


def _plain(data):
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return data.decode("utf-16")
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("invalid_text_encoding") from error


def _docx(data, include_previews=True, *, include_audit_figures=False):
    try:
        with ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            if (len(members) > 500 or sum(member.file_size for member in members) > 24 * 1024 * 1024
                    or "word/document.xml" not in archive.namelist()):
                raise ValueError("invalid_document")
    except BadZipFile as error:
        raise ValueError("invalid_document") from error

    try:
        from docx import Document
        from docx.table import Table
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.text.hyperlink import Hyperlink
        from PIL import Image
    except ImportError as error:
        raise ValueError("file_reader_unavailable") from error

    try:
        document = Document(BytesIO(data))
        has_figures = bool(document.element.body.xpath(".//w:drawing | .//w:pict"))
        lines = []
        media = []
        figures = []
        figure_count = 0
        warnings = []
        table_rows = {}
        has_title = False
        def paragraph_text(paragraph):
            nonlocal figure_count
            for drawing in paragraph._p.xpath(".//w:drawing"):
                refs = drawing.xpath(".//a:blip/@r:embed")
                if not refs:
                    if "preview_partial" not in warnings:
                        warnings.append("preview_partial")
                    continue
                figure_count += 1
                props = drawing.find(".//" + qn("wp:docPr"))
                caption = (props.get("descr", "") if props is not None else "").replace("\n", " ").replace("]", "")[:160]
                caption = caption.strip()
                marker = " " + caption + " " if caption else ""
                if include_audit_figures and caption and len(figures) < MAX_AUDIT_FIGURES:
                    try:
                        with Image.open(BytesIO(document.part.related_parts[refs[0]].blob)) as image:
                            src = thumbnail(image, (1280, 1280))
                        figures.append({"number": figure_count, "line": len(lines) + 1,
                                        "label": caption, "src": src})
                    except (OSError, KeyError, ValueError, Image.DecompressionBombError):
                        pass
                if include_previews:
                    try:
                        if len(media) >= 8:
                            raise ValueError("preview_limit")
                        part = document.part.related_parts[refs[0]]
                        with Image.open(BytesIO(part.blob)) as image:
                            src = thumbnail(image)
                        ident = "fig-" + str(len(media) + 1)
                        media.append({"id": ident, "src": src})
                        marker = f" ![{caption}](attachment:{ident}) "
                    except (OSError, KeyError, ValueError, Image.DecompressionBombError):
                        if "preview_partial" not in warnings:
                            warnings.append("preview_partial")
                # Preserve the position of the image relative to surrounding run text.
                replacement = OxmlElement("w:t")
                replacement.text = marker
                drawing.getparent().replace(drawing, replacement)
            fragments = []
            for part in paragraph.iter_inner_content():
                value = part.text
                if isinstance(part, Hyperlink):
                    try:
                        url = part.url
                    except KeyError:
                        url = ""
                    if url.lower().startswith(("https://", "http://")) and url != value:
                        value = f"{value} ({url})"
                fragments.append(value)
            return "".join(fragments).strip()
        for block in document.iter_inner_content():
            if isinstance(block, Table):
                for index, row in enumerate(block.rows):
                    cells = [""] * row.grid_cols_before
                    previous = None
                    for cell in row.cells:
                        value = "" if cell._tc is previous else " ".join(paragraph_text(p) for p in cell.paragraphs)
                        cells.append(value.replace("\n", " ").strip().replace("|", "\\|"))
                        previous = cell._tc
                    cells.extend([""] * row.grid_cols_after)
                    properties = row._tr.trPr
                    header = properties.find(qn("w:tblHeader")) if properties is not None else None
                    is_header = header is not None and header.get(qn("w:val")) not in {"0", "false", "off"}
                    table_rows[len(lines) + 1] = "table_header" if is_header else "table_row"
                    lines.append("| " + " | ".join(cells) + " |")
                    if index == 0 and is_header:
                        lines.append("| " + " | ".join("---" for _ in cells) + " |")
                lines.append("")
            else:
                value = paragraph_text(block)
                style = block.style.name if block.style else ""
                if style == "Title" and value:
                    has_title = True
                    value = "# " + value
                elif value and (heading := re.fullmatch(r"Heading ([1-9])", style)):
                    level = min(6, int(heading[1]) + has_title)
                    value = "#" * level + " " + value
                lines.extend(value.split("\n"))
                lines.append("")
        if has_figures:
            warnings.append("unreviewed_figures")
        return "\n".join(lines).rstrip(), warnings, media, table_rows, figures
    except Exception as error:
        raise ValueError("invalid_document") from error


def _pdf(data, include_previews=True, *, allow_scan_preview=False, include_audit_figures=False):
    if not data.startswith(b"%PDF-"):
        raise ValueError("invalid_document")
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ValueError("file_reader_unavailable") from error

    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError("encrypted_document")
        if len(reader.pages) > MAX_PAGES:
            raise ValueError("too_many_pages")
        pages = []
        spans = []
        unread = []
        figure_labels = []
        start = 1
        for number, page in enumerate(reader.pages, 1):
            extracted = (page.extract_text() or "").strip()
            if not READABLE_TEXT.search(extracted):
                unread.append(number)
                continue
            extracted = extracted.replace("\r\n", "\n").replace("\r", "\n")
            end = start + extracted.count("\n")
            spans.append((number, start, end))
            pages.append(extracted)
            if include_audit_figures and len(figure_labels) < MAX_AUDIT_FIGURES:
                caption = next(((index, line.strip()) for index, line in enumerate(extracted.split("\n"))
                                if PDF_FIGURE_LINE.search(line) and len(line) <= 160), None)
                if caption:
                    figure_labels.append((number, start + caption[0], caption[1]))
            start = end + 2
        scanned = not pages and bool(len(reader.pages))
        if scanned and not allow_scan_preview:
            raise ValueError("scanned_document")
        coverage = {"total": len(reader.pages), "unread": unread}
        warnings = ["scanned_document"] if scanned else ["partial_pdf"] if unread else []
        figures = []
        if figure_labels:
            warnings.append("unreviewed_figures")
            for number, line, label in figure_labels:
                try:
                    preview = pdf_page_preview(data, number)
                except ValueError:
                    continue
                figures.append({"number": number, "line": line, "label": label, "src": preview["src"]})
        if not include_previews:
            return "\n\n".join(pages), warnings, [], spans, coverage, figures
        try:
            media = pdf_previews(data)
        except Exception:
            media = []
            warnings.append("preview_partial")
        return "\n\n".join(pages), warnings, media, spans, coverage, figures
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("invalid_document") from error


def extract_document(extension, data, *, preserve_boundary_lines=False, include_previews=True,
                     allow_scan_preview=False, include_audit_figures=False):
    if extension not in FILE_TYPES:
        raise ValueError("unsupported_file")
    if not data:
        raise ValueError("empty_file")
    if len(data) > MAX_UPLOAD:
        raise ValueError("file_too_large")
    warnings = []
    media = []
    figures = []
    spans = []
    table_rows = {}
    if extension == "pdf":
        text, warnings, media, spans, pdf_coverage, figures = _pdf(
            data, include_previews, allow_scan_preview=allow_scan_preview, include_audit_figures=include_audit_figures)
    elif extension == "docx":
        text, warnings, media, table_rows, figures = _docx(
            data, include_previews, include_audit_figures=include_audit_figures)
    else:
        text = _plain(data)
        if "\x00" in text:
            raise ValueError("invalid_text_encoding")
        if extension == "md" and re.search(r"!\[[^\]\n]*\]\(attachment:fig-\d+\)", text):
            warnings.append("unreviewed_figures")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not preserve_boundary_lines and extension != "docx":
        text = text.strip()
    if not READABLE_TEXT.search(text) and "scanned_document" not in warnings:
        raise ValueError("empty_file")
    if len(text) > MAX_TEXT:
        raise ValueError("text_too_long")
    document = {"text": text, "warnings": warnings, "media": media}
    if extension == "pdf":
        document["pdf_coverage"] = pdf_coverage
    if preserve_boundary_lines:
        document["page_spans"] = spans
        document["table_rows"] = table_rows
    if figures:
        document["figures"] = figures
    return document
