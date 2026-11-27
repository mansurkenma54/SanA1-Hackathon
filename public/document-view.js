// All visible document content comes from the current editor text or a raster preview of the upload.
function node(tag, text = "", className = "") {
  const el = document.createElement(tag);
  el.textContent = text;
  if (className) el.className = className;
  return el;
}

export const pipeRow = (line) => line.includes(" | ") || /^\s*\|.*\|\s*$/.test(line);
export const tableRow = (line) => pipeRow(line) || /\S[^\n]*\t[^\n]*\S/u.test(line);
export const tableCells = (line) => (pipeRow(line)
  ? line.trim().replace(/^\||(?<!\\)\|$/g, "").split(/(?<!\\)\|/)
  : line.split("\t")).map((cell) => cell.trim().replace(/\\\|/g, "|"));
const divider = (line) => tableRow(line) && tableCells(line).every((cell) => /^:?-{2,}:?$/.test(cell));
const imagePattern = () => /!\[([^\]\n]*)\]\((?:<([^<>\n]+)>|([^\s)]+))(?:\s+"[^"\n]*")?\)/g;
const fencePattern = /^(\x60{3,}|~{3,})/;

export function localImageName(path) {
  if (/^(?:[a-z][a-z\d+.-]*:|[/\\]{2})/i.test(path)) return null;
  try {
    return decodeURIComponent(path.split(/[?#]/, 1)[0]).split(/[/\\]/).pop() || null;
  } catch {
    return null;
  }
}

function documentImage(media, path) {
  if (path.startsWith("attachment:")) return media.find(image => "attachment:" + image.id === path);
  const name = localImageName(path);
  return name ? media.find(image => image.name === name) : undefined;
}

export function wordImageReferences(text, media) {
  let fence = "";
  return text.split("\n").map(line => {
    const marker = line.trim().match(fencePattern)?.[1];
    if (fence) {
      if (marker?.startsWith(fence)) fence = "";
      return line;
    }
    if (marker) {
      fence = marker;
      return line;
    }
    return line.replace(imagePattern(), (source, caption, bracketed, bare) => {
      const image = documentImage(media, bracketed || bare);
      return image ? "![" + caption + "](attachment:" + image.id + ")" : source;
    });
  }).join("\n");
}

export function renderDocument(text, media, t, locateLine) {
  const page = node("article", "", "document-page");
  const safeRaster = (image) => image?.src?.startsWith("data:image/jpeg;base64,");
  function inlineText(parent, value) {
    let cursor = 0;
    for (const match of value.matchAll(/\*\*([^*\n]+)\*\*|\x60([^\x60\n]+)\x60/g)) {
      parent.append(value.slice(cursor, match.index), node(match[1] ? "strong" : "code", match[1] || match[2]));
      cursor = match.index + match[0].length;
    }
    parent.append(value.slice(cursor));
  }
  function inline(parent, value) {
    let cursor = 0;
    for (const match of value.matchAll(imagePattern())) {
      inlineText(parent, value.slice(cursor, match.index));
      const image = documentImage(media, match[2] || match[3]);
      if (safeRaster(image)) {
        const figure = node("figure", "", "doc-figure");
        const img = node("img");
        img.alt = match[1] || t.figure;
        img.src = image.src;
        figure.append(img, node("figcaption", match[1] || t.figure));
        parent.append(figure);
      } else {
        const name = localImageName(match[2] || match[3]);
        const label = [match[1] || t.figure, name].filter(Boolean).join(" · ");
        parent.append(node("span", label, "doc-unavailable-image"));
      }
      cursor = match.index + match[0].length;
    }
    inlineText(parent, value.slice(cursor));
  }
  function lineLink(line, label) {
    const button = node("button", label, "doc-line");
    button.type = "button";
    button.title = (t.editPassage || t.showSource) + " · " + t.line + " " + line;
    button.setAttribute("aria-label", button.title);
    button.addEventListener("click", () => locateLine(line));
    return button;
  }
  const lines = text.split("\n");
  const listPattern = /^([-+*]|\d{1,6}[.)])\s+(.+)/u;
  for (let i = 0; i < lines.length; i++) {
    const value = lines[i].trim();
    if (!value) continue;
    const fence = value.match(fencePattern);
    if (fence) {
      const block = node("pre");
      block.dataset.sourceLine = i + 1;
      const code = [];
      while (++i < lines.length && !lines[i].trim().startsWith(fence[1])) code.push(lines[i]);
      block.append(node("code", code.join("\n")));
      page.append(block);
    } else if (tableRow(value)) {
      const wrap = node("div", "", "doc-table-scroll");
      const table = node("table", "", "doc-table");
      const first = i;
      const firstCell = tableCells(value)[0];
      const hasHeaders = divider(lines[i + 1] || "") || (firstCell && !/^(?:§|\d|[A-Z]+-\d)/.test(firstCell) && tableRow(lines[i + 1] || ""));
      while (i < lines.length && tableRow(lines[i])) {
        if (!divider(lines[i])) {
          const row = table.insertRow();
          row.dataset.sourceLine = i + 1;
          const header = i === first && hasHeaders;
          tableCells(lines[i]).forEach((cell, column) => {
            const td = node(header ? "th" : "td");
            if (header) td.scope = "col";
            if (column === 0 && !header && !cell.includes("![")) {
              const edit = lineLink(i + 1, "");
              inline(edit, cell || String(i + 1));
              td.append(edit);
            } else inline(td, cell);
            row.append(td);
          });
        }
        i++;
      }
      i--;
      wrap.tabIndex = 0;
      wrap.setAttribute("aria-label", t.table);
      wrap.append(table);
      page.append(wrap);
    } else if (/^#{1,6}\s+/.test(value)) {
      const heading = node(value.startsWith("# ") ? "h3" : "h4");
      inline(heading, value.replace(/^#+\s+/, ""));
      heading.dataset.sourceLine = i + 1;
      page.append(heading);
    } else if (listPattern.test(value)) {
      const match = value.match(listPattern);
      const ordered = /^\d/.test(match[1]);
      const list = node(ordered ? "ol" : "ul", "", "doc-list");
      if (ordered) list.start = Number.parseInt(match[1], 10);
      for (; i < lines.length; i++) {
        const item = lines[i].trim().match(listPattern);
        if (!item || /^\d/.test(item[1]) !== ordered) break;
        const entry = node("li");
        entry.dataset.sourceLine = i + 1;
        if (ordered) entry.value = Number.parseInt(item[1], 10);
        const body = node("div", "", "doc-list-content");
        inline(body, item[2]);
        body.append(lineLink(i + 1, String(i + 1)));
        entry.append(body);
        list.append(entry);
      }
      i--;
      page.append(list);
    } else if (!value.includes("![") && /^.{1,42}(?:\s+→\s+[^→]{1,42}){1,6}$/u.test(value)) {
      const flow = node("ol", "", "doc-flow");
      flow.dataset.sourceLine = i + 1;
      flow.setAttribute("aria-label", t.flow);
      for (const label of value.split("→")) {
        const stage = node("li");
        stage.append(node("span", label.trim()));
        flow.append(stage);
      }
      page.append(flow);
    } else {
      const clause = value.match(/^(§\s*[\w.]+|\d+(?:\.\d+)+\.?|[A-Z]{1,5}-\d+)\s+/u);
      const row = node("div", "", "doc-paragraph");
      row.dataset.sourceLine = i + 1;
      row.append(lineLink(i + 1, clause?.[1] || String(i + 1).padStart(2, "0")));
      const quote = value.startsWith("> ");
      const body = node(quote ? "blockquote" : "div");
      inline(body, clause ? value.slice(clause[0].length) : quote ? value.slice(2) : value);
      row.append(body);
      page.append(row);
    }
  }
  return page;
}

export function formattedCopy(text, media, t, lang) {
  const doc = document.implementation.createHTMLDocument(t.copyTitle);
  doc.documentElement.lang = lang;
  const charset = doc.createElement("meta");
  charset.setAttribute("charset", "utf-8");
  const viewport = doc.createElement("meta");
  viewport.name = "viewport";
  viewport.content = "width=device-width,initial-scale=1";
  const style = doc.createElement("style");
  style.textContent = `
    * { box-sizing: border-box } body { margin: 0 auto; max-width: 52rem; padding: 2rem 5%; font: 16px/1.55 system-ui,sans-serif; color: #193627 }
    h3 { font-size: 1.85rem; margin: 0 0 1rem } h4 { font-size: 1.15rem; margin: 1.4rem 0 .4rem }
    table { width: 100%; border-collapse: collapse } th,td { padding: .45rem; border: 1px solid #b7c6bc; text-align: start } th { background: #e6efe8 }
    .doc-paragraph { display: flex; align-items: baseline; gap: .7rem; margin: .35rem 0 } .doc-line { font-weight: 650; color: #326347; white-space: nowrap }
    .doc-flow { display: flex; flex-wrap: wrap; gap: .5rem; padding: 0; list-style: none } .doc-flow li:not(:last-child)::after { content: ' →' }
    figure { margin: 1rem 0 } img { display: block; max-width: 100%; height: auto } figcaption { font-size: .85rem } td, .doc-paragraph div { overflow-wrap: anywhere }
    @media print { body { padding: 0; max-width: none } figure,tr { break-inside: avoid } h3,h4 { break-after: avoid } }
  `;
  doc.head.prepend(charset);
  doc.head.append(viewport, style);
  const content = renderDocument(text, media, t, () => {});
  for (const button of content.querySelectorAll("button")) {
    button.replaceWith(node("span", button.textContent, "doc-line"));
  }
  doc.body.append(content);
  return "<!doctype html>\n" + doc.documentElement.outerHTML;
}
