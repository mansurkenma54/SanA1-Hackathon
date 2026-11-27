"""Build an editable document from the reviewed text and its local raster previews."""

from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from io import BytesIO
import re

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from PIL import Image

from analyzer import MAX_TEXT
from public_links import web_urls


FIGURE = re.compile(r"!\[([^\]]*)\]\(attachment:(fig-\d+)\)")
JPEG_PREFIX = "data:image/jpeg;base64,"
INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def read_images(media):
    if not isinstance(media, list) or len(media) > 12:
        raise ValueError("invalid_document")
    images, pages = {}, {}
    for item in media:
        if not isinstance(item, dict) or not isinstance(item.get("src"), str) or not item["src"].startswith(JPEG_PREFIX):
            raise ValueError("invalid_document")
        try:
            binary = b64decode(item["src"][len(JPEG_PREFIX):], validate=True)
            with Image.open(BytesIO(binary)) as picture:
                if picture.format != "JPEG" or picture.width > 800 or picture.height > 900:
                    raise ValueError("invalid_document")
                safe = BytesIO()
                picture.convert("RGB").save(safe, format="JPEG", quality=88)
                image = (safe.getvalue(), picture.width)
        except (Base64Error, OSError, Image.DecompressionBombError) as error:
            raise ValueError("invalid_document") from error
        key = item.get("id")
        page = item.get("page")
        if isinstance(key, str) and re.fullmatch(r"fig-[1-8]", key) and key not in images:
            images[key] = image
        elif type(page) is int and 1 <= page <= 4 and page not in pages:
            pages[page] = image
        else:
            raise ValueError("invalid_document")
    return images, pages


def edited_audit_figures(text, media):
    if not isinstance(media, list) or len(media) > 4:
        raise ValueError("invalid_document")
    images, pages = read_images(media)
    if pages:
        raise ValueError("invalid_document")
    figures = []
    for line, value in enumerate(text.splitlines(), 1):
        for caption, key in FIGURE.findall(value):
            if key in images and caption.strip():
                data, _ = images.pop(key)
                figures.append({"number": int(key[4:]), "line": line, "label": caption.strip(),
                                "src": JPEG_PREFIX + b64encode(data).decode("ascii")})
    return figures


def row_cells(line):
    if " | " in line or (line.startswith("|") and line.endswith("|")):
        return [part.strip().replace(r"\|", "|") for part in re.split(r"(?<!\\)\|", line.removeprefix("|").removesuffix("|"))]
    if "\t" in line:
        return [part.strip() for part in line.split("\t")]
    return None


def add_image(paragraph, image, caption, width_cm):
    data, pixels = image
    shape = paragraph.add_run().add_picture(BytesIO(data), width=Cm(min(width_cm, pixels * 2.54 / 96)))
    shape._inline.docPr.set("descr", caption)


def add_linked_text(paragraph, text):
    cursor = 0
    for url in web_urls(text):
        start = text.index(url, cursor)
        paragraph.add_run(text[cursor:start])
        hyperlink = OxmlElement("w:hyperlink")
        relation = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
        hyperlink.set(qn("r:id"), relation)
        run = paragraph.add_run(url)
        run.underline = True
        hyperlink.append(run._r)
        paragraph._p.append(hyperlink)
        cursor = start + len(url)
    paragraph.add_run(text[cursor:])


def add_text(paragraph, text, images, width_cm=16.5):
    cursor = 0
    for match in FIGURE.finditer(text):
        add_linked_text(paragraph, text[cursor:match.start()])
        caption, image_id = match.groups()
        if image_id in images:
            add_image(paragraph, images[image_id], caption, width_cm)
        else:
            paragraph.add_run(caption or match.group())
        cursor = match.end()
    add_linked_text(paragraph, text[cursor:])


def build_word(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        raise ValueError("invalid_request")
    text = payload["text"].strip()
    if len(text) > MAX_TEXT:
        raise ValueError("text_too_long")
    if not text or INVALID_XML.search(text) or payload.get("locale", "en") not in ("en", "ru", "kk"):
        raise ValueError("invalid_request")
    images, pages = read_images(payload.get("media", []))
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.25)
    section.top_margin = section.bottom_margin = Cm(2)
    normal = document.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(11)
    normal.paragraph_format.space_after = Pt(5)
    document.core_properties.author = "SanA1"
    document.core_properties.language = payload.get("locale", "en")
    document.core_properties.title = text.splitlines()[0].strip("# ")[:120]
    table, width = None, 0
    cell_count = 0
    for raw in text.splitlines():
        line = raw.strip()
        cells = row_cells(line)
        if cells is not None:
            if all(re.fullmatch(r":?-{2,}:?", value) for value in cells):
                continue
            cell_count += len(cells)
            if cell_count > 6000:
                raise ValueError("invalid_document")
            # Word limits native tables to 63 columns. Partition oversized rows without dropping cells.
            for offset in range(0, len(cells), 63):
                values = cells[offset:offset + 63]
                if table is None or len(values) != width:
                    width = len(values)
                    table = document.add_table(rows=0, cols=width)
                    table.style = "Table Grid"
                for value, cell in zip(values, table.add_row().cells):
                    add_text(cell.paragraphs[0], value, images, max(.2, 16.5 / width - .35))
            continue
        table = None
        if not line:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            p = document.add_heading(level=len(heading[1]))
            add_text(p, heading[2], images)
        else:
            add_text(document.add_paragraph(), line, images)
    if pages:
        ru = payload.get("locale") == "ru"
        document.add_page_break()
        document.add_heading("Страницы исходного PDF" if ru else "Original PDF pages", level=1)
        for page_number, image in sorted(pages.items()):
            caption = ("Страница " if ru else "Page ") + str(page_number)
            document.add_paragraph(caption, style="Caption")
            add_image(document.add_paragraph(), image, caption, 16.5)
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()
