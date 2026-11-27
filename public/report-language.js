import { tableCells } from "./document-view.js";

const wording = {
  ru: {
    title: "Язык отчёта", source: "Язык документа", other: "Другой язык", name: "Название языка", translate: "Перевести",
    download: "Скачать отчёт (.md)", original: "Скачать оригинал (RU)", closeOriginal: "Открыть оригинал",
    notice: "Меняется язык пояснений. Цитаты остаются на языке документа.",
    loading: "Готовим перевод отчёта…", rate: "Достигнут лимит запросов. Повторите позже или откройте русский оригинал.",
    failed: "Перевод не получен. Повторите попытку или откройте русский оригинал.", retry: "Повторить перевод",
    originalNote: "Для сдачи на хакатон используйте русский оригинал.", language: "Отчёт",
    pending: "Выберите «Перевести», чтобы прочитать отчёт на этом языке.", invalid: "Проверьте название выбранного языка.",
    unknown: "Не удалось определить язык документа. Выберите язык отчёта в списке или введите его название.",
  },
  kk: {
    title: "Есеп тілі", source: "Құжат тілі", other: "Басқа тіл", name: "Тілдің атауы", translate: "Аудару",
    download: "Есепті жүктеу (.md)", original: "Түпнұсқаны жүктеу (RU)", closeOriginal: "Түпнұсқаны ашу",
    notice: "Түсіндірмелер аударылады. Дәйексөздер құжаттың өз тілінде қалады.",
    loading: "Есеп аударылып жатыр…", rate: "Сұрау шегіне жеттіңіз. Кейінірек қайталап көріңіз немесе орысша түпнұсқаны ашыңыз.",
    failed: "Аударма алынбады. Қайталап көріңіз немесе орысша түпнұсқаны ашыңыз.", retry: "Аударманы қайталау",
    originalNote: "Хакатонға тапсыру үшін орысша түпнұсқаны пайдаланыңыз.", language: "Есеп",
    pending: "Есепті осы тілде оқу үшін «Аудару» батырмасын басыңыз.", invalid: "Таңдалған тілдің атауын тексеріңіз.",
    unknown: "Құжаттың тілі анықталмады. Есеп тілін тізімнен таңдаңыз немесе оның атауын енгізіңіз.",
  },
  en: {
    title: "Report language", source: "Document language", other: "Other language", name: "Language name", translate: "Translate",
    download: "Download report (.md)", original: "Download original (RU)", closeOriginal: "Read the original",
    notice: "The explanations are translated. Source quotations keep their original wording.",
    loading: "Translating the report…", rate: "The request limit was reached. Try again later or open the Russian original.",
    failed: "The translation was unavailable. Try again or open the Russian original.", retry: "Retry translation",
    originalNote: "Use the Russian original for the hackathon submission.", language: "Report",
    pending: "Choose Translate to read the report in this language.", invalid: "Check the name of the selected language.",
    unknown: "The document language could not be identified. Select the report language or enter a language name.",
  },
};
const presets = { ru: "Русский", kk: "Қазақша", en: "English" };
function element(tag, text = "", className = "") {
  const el = document.createElement(tag);
  el.textContent = text;
  if (className) el.className = className;
  return el;
}

export function literalReportText(value) {
  return value.replace(/\\([\\|\[\]`*_])/g, "$1")
    .replace(/&(amp|lt|gt);/g, (_, key) => ({ amp: "&", lt: "<", gt: ">" })[key]);
}

// The audit writer emits headings, lists, tables and literal source quotations.
// All content is inserted as text, including any HTML copied from a source.
export function reportArticle(markdown) {
  const article = element("article", "", "report-article");
  const lines = markdown.split(/\r?\n/);
  const tableLine = line => /^\s*\|.*\|\s*$/.test(line);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    const heading = line.match(/^(#{1,6})\s+(.*)/);
    const listItem = line.match(/^([-*]|\d+\.)\s+/);
    if (heading) {
      article.append(element("h" + Math.min(6, heading[1].length + 2), literalReportText(heading[2])));
    } else if (tableLine(line) && tableLine(lines[i + 1] || "") && tableCells(lines[i + 1]).every(cell => /^:?-{2,}:?$/.test(cell))) {
      const wrapper = element("div", "", "report-table");
      wrapper.tabIndex = 0;
      const table = element("table");
      const headerRow = table.createTHead().insertRow();
      for (const cell of tableCells(line)) {
        const header = element("th", literalReportText(cell));
        header.scope = "col";
        headerRow.append(header);
      }
      const body = table.createTBody();
      i += 2;
      while (i < lines.length && tableLine(lines[i])) {
        const row = body.insertRow();
        for (const cell of tableCells(lines[i++])) row.insertCell().textContent = literalReportText(cell);
      }
      i--;
      wrapper.append(table);
      article.append(wrapper);
    } else if (listItem) {
      const ordered = /^\d/.test(listItem[1]);
      const marker = ordered ? /^\d+\.\s+/ : /^[-*]\s+/;
      const list = element(ordered ? "ol" : "ul");
      if (ordered) list.start = parseInt(listItem[1], 10);
      while (i < lines.length && marker.test(lines[i].trim())) {
        list.append(element("li", literalReportText(lines[i].trim().replace(marker, ""))));
        i++;
      }
      i--;
      article.append(list);
    } else if (line.startsWith(">")) article.append(element("blockquote", literalReportText(line.replace(/^> ?/, ""))));
    else article.append(element("p", literalReportText(line)));
  }
  return article;
}

function languageName(code, locale) {
  if (presets[code]) return presets[code];
  if (/^[a-z]{2,3}(?:-[a-zA-Z0-9]+)*$/.test(code)) {
    try { return new Intl.DisplayNames([locale], { type: "language" }).of(code); } catch {}
  }
  return code;
}

export function reportTarget(choice, customName, sourceLanguage) {
  if (choice === "source") return sourceLanguage && sourceLanguage !== "und" ? sourceLanguage : "auto";
  if (choice === "other") return customName.trim();
  return Object.hasOwn(presets, choice) ? choice : "";
}

export function reportLanguagePanel({ audit, markdown, locale, saved, translate, download, change, official }) {
  const root = element("div", "", "report-language-panel");
  const form = element("form", "", "report-language-form");
  const label = element("label");
  const caption = element("span");
  const select = element("select");
  select.dataset.reportLanguage = "";
  for (const code of ["source", ...Object.keys(presets), "other"]) select.add(new Option("", code));
  select.value = ["source", "ru", "kk", "en", "other"].includes(saved?.choice) ? saved.choice : "source";
  label.append(caption, select);
  const customLabel = element("label");
  const customCaption = element("span");
  const custom = element("input");
  custom.type = "text";
  custom.maxLength = 64;
  custom.dir = "auto";
  custom.value = typeof saved?.custom === "string" ? saved.custom.slice(0, 64) : "";
  customLabel.append(customCaption, custom);
  const submit = element("button", "", "button primary button-compact");
  submit.type = "submit";
  form.append(label, customLabel, submit);
  const note = element("p", "", "audit-verdict");
  const status = element("p", "", "report-language-status");
  status.setAttribute("role", "status");
  const actions = element("div", "", "audit-actions");
  const save = element("button", "", "button primary button-compact");
  const original = element("button", "", "button secondary button-compact");
  const readOriginal = element("button", "", "button text-button button-compact");
  for (const button of [save, original, readOriginal]) button.type = "button";
  actions.append(save, original, readOriginal);
  const preview = element("div", "", "report-language-preview");
  root.append(form, note, status, actions, preview);
  const source = official ? "ru" : audit.source_language;
  const cache = new Map([["ru", { language: "ru", markdown }]]);
  const target = () => reportTarget(select.value, custom.value, source);
  const cached = saved?.result;
  if (cached?.target === target() && typeof cached.markdown === "string" && typeof cached.language === "string"
      && cached.markdown.trim() && cached.language.trim() && target() !== "ru") cache.set(target(), cached);
  let controller, error = "", rendered;
  const current = () => cache.get(target());

  function render() {
    const t = wording[locale] || wording.en;
    const result = current();
    caption.textContent = t.title;
    const known = source && source !== "und" ? " · " + languageName(source, locale) : "";
    for (const opt of select.options) opt.text = presets[opt.value] || (opt.value === "source" ? t.source + known : t.other);
    customLabel.hidden = select.value !== "other";
    custom.required = !customLabel.hidden;
    customCaption.textContent = t.name;
    submit.textContent = error ? t.retry : t.translate;
    submit.hidden = Boolean(result);
    submit.disabled = Boolean(controller) || !target();
    note.textContent = t.notice + (official ? " " + t.originalNote : "");
    status.textContent = controller ? t.loading : error ? t[error] : result ? t.language + " · " + languageName(result.language, locale) : t.pending;
    status.dataset.error = String(Boolean(error));
    preview.setAttribute("aria-busy", String(Boolean(controller)));
    save.hidden = !result;
    save.textContent = t.download;
    original.textContent = t.original;
    readOriginal.textContent = t.closeOriginal;
    readOriginal.hidden = target() === "ru";
    original.hidden = target() === "ru";
    if (result !== rendered && !root.closest(".audit-pane")?.hidden) {
      preview.replaceChildren(...(result ? [reportArticle(result.markdown)] : []));
      preview.lang = result && /^[a-z]{2,3}(?:-[a-zA-Z0-9]+)*$/.test(result.language) ? result.language : "";
      preview.dir = "auto";
      rendered = result;
    }
    change();
  }
  function cancel() {
    controller?.abort();
    controller = undefined;
    error = "";
  }
  function selectLanguage() {
    cancel();
    render();
  }
  async function generate() {
    const requested = target();
    if (!requested || current() || controller) return;
    const attempt = new AbortController();
    controller = attempt;
    error = "";
    render();
    try {
      const data = await translate(requested, attempt.signal);
      if (controller !== attempt || requested !== target()) return;
      if (typeof data?.markdown !== "string" || !data.markdown.trim() || typeof data.language !== "string" || !data.language.trim()) throw Error();
      if (Object.hasOwn(presets, requested) && data.language.split("-")[0] !== requested) throw Error();
      if (data.language !== "ru" && data.markdown.trim() === markdown.trim()) throw Error();
      if (cache.size >= 5) cache.delete([...cache.keys()].find(key => key !== "ru"));
      cache.set(requested, { language:data.language, markdown:data.markdown });
    } catch (failure) {
      if (controller !== attempt || attempt.signal.aborted) return;
      const reason = {source_language_unknown: "unknown", invalid_report_language: "invalid"}[failure.message];
      error = failure.status === 429 ? "rate" : reason || "failed";
    } finally {
      if (controller === attempt) { controller = undefined; render(); }
    }
  }
  form.addEventListener("submit", event => { event.preventDefault(); generate(); });
  select.addEventListener("change", selectLanguage);
  custom.addEventListener("input", selectLanguage);
  save.onclick = () => { const result = current(); if (result) download(result); };
  original.onclick = () => download(cache.get("ru"));
  readOriginal.onclick = () => { select.value = "ru"; selectLanguage(); };
  return {
    root, current, cancel, generate, render, target,
    setLanguage(next) { locale = next; render(); },
    snapshot() {
      const result = current();
      return {choice:select.value, custom:custom.value, result:result && target() !== "ru" ? { ...result, target:target() } : null};
    },
  };
}
