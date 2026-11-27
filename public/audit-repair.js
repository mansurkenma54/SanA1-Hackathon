import { evidenceSelection } from "./audit-view.js";
import { tableRow } from "./document-view.js";

const prefix = /^(?:[ \t]*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)?(?:(?:\*\*)?(?:[A-ZА-ЯЁ]{1,12}[-–_]\d+(?:[.-]\d+)*[.:]?(?:\*\*)?|§\s*\d+(?:\.\d+)*\.?)\s+)?)/u;
const attachments = value => value.match(/!\[[^\]]*\]\(attachment:fig-\d+\)/g) || [];
const purchaseRule = /месяц определяется по дате (?:совершения )?покупки/iu;
const monthAdjectives = {
  января: "Январский", февраля: "Февральский", марта: "Мартовский", апреля: "Апрельский",
  мая: "Майский", июня: "Июньский", июля: "Июльский", августа: "Августовский",
  сентября: "Сентябрьский", октября: "Октябрьский", ноября: "Ноябрьский", декабря: "Декабрьский",
};

export function revisionParts(text, source) {
  const range = evidenceSelection(text, source);
  if (!range) return [];
  const [start, end] = range;
  const lineStart = start ? text.lastIndexOf("\n", start - 1) + 1 : 0;
  const lineEnd = text.indexOf("\n", start);
  const raw = text.slice(lineStart, lineEnd < 0 ? text.length : lineEnd);
  if (end <= lineStart + raw.length && /^\s*\|.*\|\s*$/.test(raw)) {
    const bars = [...raw.matchAll(/(?<!\\)\|/g)].map(match => match.index);
    return bars.slice(0, -1).map((bar, index) => {
      const cell = raw.slice(bar + 1, bars[index + 1]);
      const from = bar + 1 + (cell.length - cell.trimStart().length);
      return { start: lineStart + from, end: lineStart + from + cell.trim().length, before: cell.trim(), cell: index + 1 };
    });
  }
  const before = text.slice(start, end);
  const kept = start === lineStart ? before.match(prefix)[0] : "";
  return [{ start: start + kept.length, end, before: before.slice(kept.length) }];
}

export function revisionPatch(text, part, value, append = false) {
  let wording = value.trim();
  if (!wording || wording === part.before) throw Error("wording");
  if (part.cell && (append || /[\r\n\t]/.test(wording))) throw Error("cell");
  if (!append && attachments(part.before).join("\n") !== attachments(wording).join("\n")) throw Error("attachments");
  if (part.cell) wording = wording.replace(/(?<!\\)\|/g, "\\|");
  const lineEnd = text.indexOf("\n", part.end);
  const finish = lineEnd < 0 ? text.length : lineEnd;
  if (append) return { start: finish, end: finish, before: "", after: "\n\n" + wording, anchor: part.start };
  return { start: part.start, end: part.end, before: part.before, after: wording };
}

export function applyRevisionPatches(text, patches, limit) {
  const ordered = [...patches].sort((a, b) => a.start - b.start);
  let end = -1;
  let previous;
  for (const patch of ordered) {
    if (!Number.isInteger(patch.start) || !Number.isInteger(patch.end) || patch.start < 0 || patch.end < patch.start ||
        patch.end > text.length || patch.start < end || patch.start === previous ||
        text.slice(patch.start, patch.end) !== patch.before || typeof patch.after !== "string") throw Error("overlap");
    end = patch.end;
    previous = patch.start;
  }
  const revised = ordered.reduceRight((value, patch) => value.slice(0, patch.start) + patch.after + value.slice(patch.end), text);
  if (Array.from(revised).length > limit) throw Error("length");
  return revised;
}

function choices(item, part) {
  if (!item) return [];
  if (item.criterion === "Непротиворечивость" && /месяц/iu.test(item.question) &&
      item.evidence.some(source => purchaseRule.test(source.quote))) {
    const acceptance = item.evidence.find(source =>
      /^\|\s*Покупка\s+\d{1,2}\s+([а-яё]+)/iu.test(source.quote));
    const [purchase, posting, result] = acceptance?.quote.trim().slice(1, -1).split("|").map(cell => cell.trim()) || [];
    const purchaseMonth = monthAdjectives[purchase?.match(/\d{1,2}\s+([а-яё]+)/iu)?.[1].toLowerCase()];
    const postingMonth = monthAdjectives[posting?.match(/^Провести(?:\s+покупку)?\s+\d{1,2}\s+([а-яё]+)/iu)?.[1].toLowerCase()];
    if (purchaseMonth && postingMonth && purchaseMonth !== postingMonth && result?.startsWith(postingMonth + " счётчик")) {
      if (part.cell && part.source === acceptance && part.before === result) {
        return [["Считать по месяцу покупки", part.before.replace(postingMonth, purchaseMonth)]];
      }
      if (!part.cell && purchaseRule.test(part.before)) {
        return [["Считать по месяцу проведения", part.before.replace(purchaseRule, "Месяц определяется по дате проведения покупки")]];
      }
    }
  }
  if (item.criterion === "Ограничения реализации" && item.explanation.includes("GET") &&
      (part.before === "HTTP method: GET" || part.before === "GET" && /rest type|http method/iu.test(part.source.quote))) {
    if (/созда(?:ёт|ет|вать|ния|ют)\s+заявк|creat(?:e|es|ing)\s+(?:a\s+)?(?:request|refund)/iu.test(
      [item.explanation, item.question, ...item.evidence.map(source => source.quote)].join(" "))) {
      return [["Команда через POST", part.before.replace("GET", "POST")]];
    }
    return [["Обновление через PATCH", part.before.replace("GET", "PATCH")], ["Команда через POST", part.before.replace("GET", "POST")]];
  }
  return [];
}

export function preferredRevisionPart(parts, item) {
  const choiceCell = parts.findIndex(part => part.cell && choices(item, part).length);
  if (choiceCell >= 0) return choiceCell;
  const withChoice = parts.findIndex(part => choices(item, part).length);
  if (withChoice >= 0) return withChoice;
  if (item?.criterion === "Непротиворечивость" && /лимит|\blimit\b/iu.test(item.question)) {
    const amount = parts.findIndex(part => part.cell && /\d\s*(?:₸|₽|\$|€|KZT\b|RUB\b|USD\b|EUR\b|тенге\b)|[₸₽$€]\s*\d/iu.test(part.before));
    if (amount >= 0) return amount;
  }
  return 0;
}

const text = {
  ru: {
    edit: "Изменить фрагмент", resolve: "Разобрать замечание", close: "Закрыть", context: "Исходные цитаты",
    target: "Какой фрагмент изменить", cellName: "Столбец", action: "Вид правки", replace: "Заменить фрагмент",
    append: "Добавить условие после фрагмента", answer: "Согласованное решение или новая формулировка",
    placeholder: "Опишите условие и ожидаемое поведение", options: "Варианты ответа", preview: "Посмотреть правку", ai: "Сформулировать с ИИ",
    aiNote: "ИИ подготовит формулировку по вашему решению.", waiting: "Модель готовит формулировку…",
    problem: "Что обнаружено", advice: "Что уточнить", decision: "Решение", compare: "Сравнение", steps: "Этап правки",
    aiError: "Модель не подготовила формулировку. Можно продолжить со своим текстом.",
    before: "Было", after: "Станет", staged: "Добавить в список правок", apply: "Внести правку", back: "К формулировке",
    another: "Изменить ещё фрагмент", remove: "Снять правку", prepared: "Правка подготовлена",
    missing: "Этот фрагмент не удалось однозначно найти. Проверьте документ и повторите аудит.",
    wording: "Введите новую формулировку с условием или действием.", cell: "Значение ячейки должно оставаться на одной строке.",
    attachments: "Сохраните ссылки на рисунки в этой правке.", overlap: "Здесь уже есть другая правка. Снимите её или сначала перепроверьте документ.",
    length: "После правки документ превышает допустимый объём.", stale: "Документ изменился. Откройте актуальную версию.",
  },
  en: {
    edit: "Edit passage", resolve: "Resolve finding", close: "Close", context: "Source quotations",
    target: "Passage to change", cellName: "Column", action: "Change type", replace: "Replace passage",
    append: "Add a condition after the passage", answer: "Agreed decision or new wording",
    placeholder: "Describe the condition and expected behavior", options: "Answer options", preview: "Preview change", ai: "Draft with AI",
    aiNote: "AI drafts wording from your decision.", waiting: "The model is drafting…",
    problem: "What was found", advice: "What to clarify", decision: "Decision", compare: "Comparison", steps: "Revision stage",
    aiError: "The model could not draft the change. You can continue with your wording.",
    before: "Before", after: "After", staged: "Add to pending changes", apply: "Apply change", back: "Edit wording",
    another: "Change another passage", remove: "Remove change", prepared: "Change prepared",
    missing: "This passage could not be found unambiguously. Check the document and rerun the audit.",
    wording: "Enter new wording that gives a condition or action.", cell: "Keep the cell value on a single line.",
    attachments: "Keep the illustration references in this change.", overlap: "Another edit overlaps this one. Remove it or recheck the document first.",
    length: "The edited document exceeds the allowed length.", stale: "The document changed. Open the current version.",
  },
};
text.kk = {
  ...text.ru,
  edit: "Үзіндіні өңдеу", resolve: "Ақауды қарау", close: "Жабу", context: "Бастапқы дәйексөздер",
  target: "Өзгеретін үзінді", cellName: "Баған", action: "Өзгеріс түрі", replace: "Үзіндіні ауыстыру",
  append: "Үзіндіден кейін шарт қосу", answer: "Автор шешімі немесе жаңа мәтін", placeholder: "Шарт пен күтілетін әрекетті жазыңыз",
  options: "Жауап нұсқалары", preview: "Түзетуді көру", ai: "ИИ-мен тұжырымдау",
  aiNote: "ИИ шешіміңізге сүйеніп, мәтін ұсынады.", waiting: "ИИ мәтін дайындап жатыр…",
  aiError: "ИИ мәтін ұсына алмады. Өз мәтініңізбен жалғастыра аласыз.",
  before: "Бұрын", after: "Кейін", staged: "Түзетулер тізіміне қосу", apply: "Түзетуді енгізу", back: "Мәтінге оралу",
  another: "Тағы бір үзіндіні өңдеу", remove: "Түзетуді алып тастау", prepared: "Түзету дайын",
  problem: "Табылған ақау", advice: "Нені нақтылау керек", decision: "Шешім", compare: "Салыстыру", steps: "Түзету қадамы",
  wording: "Шарты немесе әрекеті көрсетілген жаңа мәтін енгізіңіз.", cell: "Ұяшықтағы мәтін бір жолға сыйсын.",
};

export function showRevision(dialog, { documentText, item, sources, language, existing, submit, suggest }) {
  const t = text[language] || text.en;
  const el = (tag, content = "", css = "") => {
    const element = document.createElement(tag);
    element.textContent = content;
    element.className = css;
    return element;
  };
  const button = (label, action, css = "secondary") => {
    const control = el("button", label, "button " + css);
    control.type = "button";
    control.addEventListener("click", action);
    return control;
  };
  const head = el("header", "", "revision-head");
  const title = el("h2", item ? item.id + " · " + t.resolve : t.edit);
  title.id = "revision-title";
  head.append(title, button(t.close, () => dialog.close(), "text-button"));
  const content = el("div", "", "revision-content");
  const status = el("p", "", "revision-status");
  status.setAttribute("role", "status");
  const form = el("form", "", "revision-fields");
  const preview = el("section", "", "revision-preview");
  preview.hidden = true;
  const steps = el("ol", "", "revision-steps");
  steps.setAttribute("aria-label", t.steps);
  const decideStep = el("li", "1 · " + t.decision);
  const compareStep = el("li", "2 · " + t.compare);
  function showStage(compare) {
    decideStep.toggleAttribute("data-current", !compare);
    compareStep.toggleAttribute("data-current", compare);
  }
  steps.append(decideStep, compareStep);
  showStage(false);
  content.append(steps);
  let requestId = 0;
  let authoredAnswer = "";
  if (item) {
    const problem = el("section", "", "revision-problem");
    problem.dataset.severity = item.severity;
    problem.lang = "ru";
    const label = el("h3", t.problem);
    label.lang = language;
    problem.append(label, el("p", item.explanation, "revision-explanation"));
    const question = el("h3", item.question, "revision-question");
    question.lang = "ru";
    const advice = el("div", "", "revision-rationale");
    advice.append(el("strong", t.advice), el("p", item.next_step, "revision-advice"));
    advice.lastElementChild.lang = "ru";
    content.append(problem, question, advice);
  }
  if (sources.length > 1) {
    const context = el("details", "", "revision-context");
    context.append(el("summary", t.context));
    for (const source of sources) context.append(el("p", source.location + " · " + source.quote));
    content.append(context);
  }
  const parts = sources.flatMap(source => revisionParts(documentText, source).map(part => ({ ...part, source })));
  const unique = parts.filter((part, index) => parts.findIndex(other => other.start === part.start && other.end === part.end) === index);
  dialog.replaceChildren(head, content);
  dialog.showModal();
  dialog.scrollTop = 0;
  if (!unique.length) {
    content.append(el("p", t.missing));
    return;
  }
  const drafts = new Map();
  for (const { patch, answer, wording } of existing?.changes || []) {
    const index = unique.findIndex(part => (patch.anchor ?? patch.start) === part.start);
    if (index >= 0) drafts.set(index, { wording, answer, append: patch.anchor !== undefined });
  }
  let index = drafts.keys().next().value ?? preferredRevisionPart(unique, item);
  const pickerLabel = el("label", t.target);
  const picker = el("select");
  const location = part => part.source.location + (part.cell ? ` · ${t.cellName} ${part.cell}` : "");
  function markOption(optionIndex) {
    const part = unique[optionIndex];
    picker.options[optionIndex].textContent = `${location(part)} · ${part.before.slice(0, 80)}` +
      (drafts.has(optionIndex) ? ` · ${t.prepared}` : "");
  }
  for (const optionIndex of unique.keys()) {
    const option = el("option");
    option.value = String(optionIndex);
    picker.append(option);
    markOption(optionIndex);
  }
  const selected = () => unique[index];
  pickerLabel.append(picker);
  pickerLabel.hidden = unique.length === 1;
  const sourceText = el("blockquote", "", "revision-source");
  const actionLabel = el("label", t.action);
  const action = el("select");
  for (const [value, label] of [["replace", t.replace], ["append", t.append]]) {
    const option = el("option", label);
    option.value = value;
    action.append(option);
  }
  actionLabel.append(action);
  const choiceList = el("div", "", "revision-choices");
  choiceList.setAttribute("role", "group");
  choiceList.setAttribute("aria-label", t.options);
  const options = unique.flatMap((part, target) => choices(item, part).map(([label, value]) => ({ target, label, value })));
  const wordingLabel = el("label", t.answer);
  const wording = el("textarea");
  wording.rows = 3;
  wording.maxLength = 2000;
  wording.placeholder = t.placeholder;
  wordingLabel.append(wording);
  const buttons = el("div", "", "revision-actions");
  const prepare = el("button", t.preview, "button primary");
  prepare.type = "submit";
  buttons.append(prepare);
  const aiNote = el("p", t.aiNote, "revision-advice");
  const ai = suggest && button(t.ai, async () => {
    const part = selected();
    const answer = wording.value.trim();
    if (!answer) {
      status.textContent = t.wording;
      wording.focus();
      return;
    }
    const id = ++requestId;
    ai.disabled = true;
    status.textContent = t.waiting;
    try {
      const replacement = await suggest(part, answer);
      if (!form.isConnected || !dialog.open || id !== requestId) return;
      if (typeof replacement !== "string" || !replacement.trim()) throw Error();
      authoredAnswer = answer;
      wording.value = replacement;
      showPreview();
    } catch (error) {
      if (form.isConnected && dialog.open && id === requestId) status.textContent = error.question || t.aiError;
    } finally {
      if (id === requestId) ai.disabled = false;
    }
  });
  if (ai) buttons.append(ai);
  function invalidateSuggestion() {
    requestId++;
    status.textContent = "";
    if (ai) ai.disabled = false;
  }
  function refreshTarget(optionIndex) {
    invalidateSuggestion();
    index = optionIndex;
    picker.value = String(index);
    const part = selected();
    const previous = drafts.get(index);
    sourceText.textContent = part.before || "—";
    action.value = previous?.append ? "append" : "replace";
    actionLabel.hidden = !item || Boolean(part.cell) || tableRow(part.source.quote);
    wording.value = previous?.wording ?? (!item ? part.before : "");
    authoredAnswer = previous?.answer || "";
    if (ai) {
      ai.hidden = aiNote.hidden = part.source.quote.includes("\n") || !part.before;
    }
    syncChoiceControls();
  }
  function saveDraft() {
    const value = wording.value.trim();
    if (!value || (value === selected().before && action.value === "replace")) drafts.delete(index);
    else drafts.set(index, { wording: value, answer: authoredAnswer, append: action.value === "append" });
    markOption(index);
  }
  for (const option of options) {
    choiceList.append(button(option.label, () => {
      saveDraft();
      for (const alternative of options) {
        const draft = drafts.get(alternative.target);
        if (alternative.target !== option.target && matchesChoice(draft, alternative)) {
          drafts.delete(alternative.target);
          markOption(alternative.target);
        }
      }
      refreshTarget(option.target);
      wording.value = option.value;
      authoredAnswer = option.label;
      syncChoiceControls();
      wording.focus();
    }));
  }
  function matchesChoice(draft, option) {
    return draft?.wording === option.value && draft.answer === option.label;
  }
  function syncChoiceControls() {
    [...choiceList.children].forEach((control, optionIndex) => {
      const option = options[optionIndex];
      const draft = option.target === index ? { wording: wording.value.trim(), answer: authoredAnswer } : drafts.get(option.target);
      control.setAttribute("aria-pressed", String(matchesChoice(draft, option)));
    });
  }
  choiceList.hidden = !options.length;

  function openForm(optionIndex) {
    showStage(false);
    preview.hidden = true;
    form.hidden = false;
    refreshTarget(optionIndex);
    dialog.scrollTop = 0;
    wording.focus();
  }

  function showPreview() {
    saveDraft();
    const changes = [];
    for (const [optionIndex, draft] of drafts) {
      const part = unique[optionIndex];
      try {
        if (item && !part.cell && /^(да|нет|yes|no|ок)[.!]?$/iu.test(draft.wording)) throw Error("wording");
        const patch = revisionPatch(documentText, part, draft.wording, draft.append);
        changes.push({ patch, answer: draft.answer || draft.wording, wording: draft.wording, location: location(part), optionIndex });
      } catch (error) {
        openForm(optionIndex);
        status.textContent = t[error.message] || t.stale;
        return;
      }
    }
    try {
      if (!changes.length) throw Error("wording");
      changes.sort((a, b) => a.patch.start - b.patch.start);
      applyRevisionPatches(documentText, changes.map(({ patch }) => patch), Infinity);
      form.hidden = true;
      preview.hidden = false;
      showStage(true);
      preview.replaceChildren();
      for (const { patch, location, optionIndex } of changes) {
        const block = el("section", "", "revision-change");
        const heading = el("div", "", "revision-change-heading");
        heading.append(el("h3", location));
        if (changes.length > 1) {
          const edit = button(t.back, () => openForm(optionIndex), "button-compact text-button");
          const remove = button(t.remove, () => {
            drafts.delete(optionIndex);
            refreshTarget(changes.find(change => change.optionIndex !== optionIndex).optionIndex);
            markOption(optionIndex);
            showPreview();
          }, "button-compact text-button");
          edit.setAttribute("aria-label", `${t.back} · ${location}`);
          remove.setAttribute("aria-label", `${t.remove} · ${location}`);
          heading.append(edit, remove);
        }
        const diff = el("div", "", "revision-diff");
        for (const [name, value] of [[t.before, patch.before], [t.after, patch.after]]) {
          const pane = el("section");
          pane.append(el("h4", name), el("pre", value.trim() || "—"));
          diff.append(pane);
        }
        block.append(heading, diff);
        preview.append(block);
      }
      const actions = el("div", "", "revision-actions");
      const apply = button(item ? t.staged : t.apply, () => {
        try {
          if (item) submit(changes.map(({ optionIndex, ...change }) => change));
          else submit(changes[0].patch);
          dialog.close();
        } catch (error) { status.textContent = t[error.message] || t.stale; }
      }, "primary");
      actions.append(apply);
      if (changes.length === 1) actions.append(button(t.back, () => openForm(changes[0].optionIndex)));
      const unedited = unique.map((part, optionIndex) => ({ ...part, optionIndex }))
        .filter(part => !drafts.has(part.optionIndex));
      if (item && unedited.length) {
        const editedSources = new Set(changes.map(change => unique[change.optionIndex].source));
        const otherSources = unedited.filter(part => !editedSources.has(part.source));
        const options = otherSources.length ? otherSources : unedited;
        const next = options[preferredRevisionPart(options, item)].optionIndex;
        actions.append(button(t.another, () => openForm(next)));
      }
      preview.append(actions);
      status.textContent = "";
      dialog.scrollTop = 0;
      apply.focus();
    } catch (error) { status.textContent = t[error.message] || t.stale; }
  }
  picker.addEventListener("change", () => {
    const next = Number(picker.value);
    if (item) saveDraft();
    refreshTarget(next);
  });
  action.addEventListener("change", invalidateSuggestion);
  wording.addEventListener("input", () => {
    authoredAnswer = "";
    invalidateSuggestion();
    syncChoiceControls();
  });
  form.addEventListener("submit", event => {
    event.preventDefault();
    invalidateSuggestion();
    showPreview();
  });
  form.append(choiceList, pickerLabel, sourceText, actionLabel, wordingLabel, buttons);
  if (ai) form.append(aiNote);
  content.append(form, preview, status);
  refreshTarget(index);
  (unique.length > 1 ? picker : wording).focus();
}
