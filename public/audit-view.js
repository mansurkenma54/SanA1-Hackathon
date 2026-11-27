import { tableCells, tableRow } from "./document-view.js";

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  if (className) element.className = className;
  return element;
}

export function evidenceSelection(text, { line, end, quote }) {
  if (!quote) return null;
  const lines = text.split("\n");
  if (Number.isInteger(line) && Number.isInteger(end) && line >= 1 && end >= line && end <= lines.length) {
    const excerpt = lines.slice(line - 1, end).join("\n");
    const first = excerpt.indexOf(quote);
    if (first >= 0 && excerpt.indexOf(quote, first + 1) < 0) {
      const start = first + lines.slice(0, line - 1).reduce((length, row) => length + row.length + 1, 0);
      return [start, start + quote.length];
    }
  }
  const start = text.indexOf(quote);
  return start >= 0 && text.indexOf(quote, start + 1) < 0 ? [start, start + quote.length] : null;
}

function evidenceList(sources, openEvidence, labelText, labelAttribute) {
  const list = node("div", "", "audit-evidence");
  for (const source of sources) {
    const quote = node("figure");
    quote.append(node("figcaption", [source.location, source.section].filter(Boolean).join(" · ")),
      node("blockquote", source.quote));
    if (openEvidence) {
      const edit = labelText(node("button", "", "button button-compact secondary audit-open-source"), "Показать в ТЗ", "Show in specification");
      edit.type = "button";
      labelAttribute(edit, "aria-label", "Показать в ТЗ", "Show in specification", source.location);
      edit.addEventListener("click", () => openEvidence(source));
      quote.append(edit);
    }
    list.append(quote);
  }
  return list;
}

function details(title, className) {
  const section = node("details", "", className);
  section.append(node("summary", title));
  return section;
}

function fact(title, text) {
  const row = node("p", "", "audit-fact");
  row.append(node("strong", title), node("span", text));
  return row;
}

function comparisonView(comparison, focusedBefore, confirmedBefore, revealFinding, appliedEdits, labelText) {
  const { repeated, needs_review: needsReview, unmatched_after: unmatched } = comparison;
  const section = details("Сравнение с аудитом до правок", "audit-comparison audit-section");
  section.open = true;
  if (appliedEdits?.size) {
    const revisions = node("section", "", "audit-applied-revisions");
    revisions.append(labelText(node("h3"), "Изменения в документе", "Changes applied to the document"));
    for (const [id, edits] of appliedEdits) {
      for (const { location, before, after } of edits) {
        const heading = node("h4", [id, location].filter(Boolean).join(" · "));
        const diff = node("div", "", "revision-diff");
        for (const [ru, en, value] of [["Было", "Before", before], ["Стало", "After", after]]) {
          const pane = node("section");
          pane.append(labelText(node("h4"), ru, en), node("pre", value.trim() || "—"));
          diff.append(pane);
        }
        const change = node("div", "", "audit-applied-revision");
        change.append(heading, diff);
        revisions.append(change);
      }
    }
    section.append(revisions);
  }
  const totals = node("dl", "", "audit-totals audit-comparison-totals");
  const pendingCount = node("dd");
  for (const [label, value] of [
    ["Повторились", node("dd", String(repeated.length))],
    ["На проверке", pendingCount],
    ["Без пары", node("dd", String(unmatched.length))],
  ]) {
    const cell = node("div");
    cell.append(node("dt", label), value);
    totals.append(cell);
  }
  section.append(totals);
  const instruction = node("p", "", "audit-verdict");
  if (needsReview.length) section.append(instruction);
  function updatePending() {
    const pending = needsReview.filter(({ id }) => !confirmedBefore.has(id)).length;
    pendingCount.textContent = String(pending);
    instruction.textContent = pending
      ? "Сверьте исходный вопрос и цитаты с новой версией ТЗ, затем подтвердите исправление."
      : "Все изменения в списке проверены вручную.";
  }
  updatePending();

  function followFinding(label, id) {
    const button = node("button", label, "button button-compact secondary");
    button.type = "button";
    button.addEventListener("click", () => revealFinding(id));
    return button;
  }

  const pairs = node("div", "", "audit-links audit-comparison-links");
  for (const { before_id: before, after_id: after } of repeated) {
    pairs.append(followFinding(`${before} → ${after} · Совпало`, after));
  }
  for (const id of unmatched) pairs.append(followFinding(`${id} · Без точной пары`, id));
  if (pairs.childElementCount) section.append(pairs);

  for (const item of needsReview) {
    const row = details(`${item.id} · ${item.explanation}`, "audit-card audit-comparison-item");
    row.open = item.id === focusedBefore;
    const status = node("p", "", "audit-decision-status");
    status.setAttribute("role", "status");
    const button = node("button", "", "button button-compact secondary");
    button.type = "button";
    function updateReviewStatus() {
      const confirmed = confirmedBefore.has(item.id);
      status.textContent = confirmed ? "Исправление подтверждено вручную" : "Ожидает ручной проверки";
      button.textContent = confirmed ? "Отменить подтверждение" : "Подтвердить исправление";
    }
    button.addEventListener("click", () => {
      if (!confirmedBefore.delete(item.id)) confirmedBefore.add(item.id);
      updateReviewStatus();
      updatePending();
    });
    updateReviewStatus();
    row.append(status, fact("Исходный вопрос", item.question), evidenceList(item.evidence));
    for (const edit of appliedEdits?.get(item.id) || []) {
      const label = edit.location ? `Внесённая правка · ${edit.location}` : "Внесённая правка";
      row.append(fact(label, edit.after.trim()));
    }
    row.append(button);
    section.append(row);
  }
  return section;
}

const labels = {
  blocked: "Есть блокирующие дефекты", clarify: "Нужны уточнения", ready: "Можно начинать разработку",
  limited: "Ограниченная проверка",
};
const priorities = { all: "Все", blocker: "Блокирующие", major: "Существенные", minor: "Низкий приоритет" };

function normalizedSearch(text) {
  return text.normalize("NFKC").toLocaleLowerCase("ru").replace(/[‐‑‒–—−]/g, "-").replace(/ё/g, "е").trim();
}

export function assessmentCoverage(requirements) {
  const reviewed = requirements.filter(item => item.assessment_status === "reviewed").length;
  const unchecked = requirements.filter(item => item.assessment_status === "unchecked").length;
  return { reviewed, unchecked, total: requirements.length, recorded: reviewed + unchecked === requirements.length };
}

export function formatAuditQuestions(findings) {
  if (!findings.length) return "";
  const groups = findings.map(({ id, priority, question, requirements, evidence }) => {
    const locations = [...new Set(evidence.map(source => source.location))];
    const lines = [`${id} · ${priority}`];
    if (requirements.length) lines.push(`Требования — ${requirements.join(", ")}`);
    if (locations.length) lines.push(`Места в ТЗ — ${locations.join(", ")}`);
    lines.push(question, "Ответ — ____________________");
    return lines.join("\n");
  });
  return ["Вопросы автору ТЗ", ...groups].join("\n\n") + "\n";
}

export function renderAudit(host, audit, {
  download, exportDocument, openRepair, openEvidence, onPanelChange, initialPanel,
  comparison, modeChanged, focusedBefore, confirmedBefore, appliedEdits, demo, renderStructure, openLinkSource, language = "ru",
}) {
  const { requirements, findings, counts } = audit;
  const rulesOnly = audit.mode === "rules";
  const mode = rulesOnly ? "Локальные правила" : "Модель и правила SanA1";
  const unreadPages = audit.pdf_origin?.unread || audit.pdf_coverage?.unread || [];
  const external = audit.external_references || [];
  const internal = audit.references || [];
  const linkCount = external.length + internal.length;
  const orderedFindings = ["blocker", "major", "minor"].flatMap(severity => findings.filter(item => item.severity === severity));
  const createsWithGet = source => /^\|\s*REST type\s*\|\s*GET\s*\|$/iu.test(source.quote);
  const demoFinding = demo && !comparison && audit.file === "qr-refund-demo.docx" &&
    orderedFindings.find(item => item.evidence.some(createsWithGet));
  const demoCitation = demoFinding && demoFinding.evidence.find(createsWithGet);
  const cards = new Map();
  const repairButtons = new Map();
  const requirementCards = new Map();
  const setCards = new Map();
  const requirementLabels = new Map(requirements.map(item => [item.id, item.source_id || item.id]));
  const translations = [];
  const kk = {
    "Требует индивидуальной сверки": "Жеке тексеру қажет", "Только без индивидуальной оценки": "Жеке бағасы жоқтарын ғана көрсету",
    "Проверка по правилам. Индивидуальная оценка ИИ не проводилась.": "Талаптар ережелермен тексерілді. ЖИ әр талапты жеке бағалаған жоқ.",
    "В этом отчёте не указан охват индивидуальной оценки ИИ.": "Бұл есепте ЖИ қанша талапты жеке бағалағаны көрсетілмеген.",
    "Требования по этому запросу не найдены.": "Сұрауға сәйкес талап табылмады.",
    "В этом прогоне требования не выделены.": "Осы тексеруде жеке талаптар анықталмады.",
    "Итог": "Қорытынды", "Отдельные требования": "Жеке талаптар", "Набор в целом": "Талаптар жиыны",
    "Паспорт прогона": "Тексеру деректері", "Проверка набора требований": "Талаптар жиынын тексеру",
    "Показать в ТЗ": "ТЗ-дан көрсету", "Файл": "Файл", "Время": "Уақыты", "Режим": "Режім", "Коммит SanA1": "SanA1 коммиті",
    "Можно начинать разработку": "Әзірлеуді бастауға болады", "Ограниченная проверка": "Шектеулі тексеру",
    "Разделы аудита": "Аудит бөлімдері", "Детали": "Толығырақ", "Результат": "Нәтиже", "Правки": "Түзетулер",
    "Сравнение": "Салыстыру", "Файлы": "Файлдар", "Требования": "Талаптар", "Паспорт": "Аудит деректері",
    "Есть блокирующие дефекты": "Жұмысты бөгейтін ақаулар бар", "Нужны уточнения": "Нақтылау керек",
    "Нарушений не выявлено": "Ақау табылмады", "Модель и правила SanA1": "ИИ және SanA1 ережелері",
    "Локальные правила · ограниченный охват": "Кірістірілген ережелер · қамту шектеулі",
    "Техническое задание": "Техникалық тапсырма", "Отчёт этого прогона": "Аудит есебі",
    "Отчёт (.md)": "Есеп (.md)", "Данные (.json)": "Деректер (.json)",
    "Скачать отчёт (.md)": "Есепті жүктеу (.md)", "Скачать данные (.json)": "Деректерді жүктеу (.json)",
    "Документ Word (.docx)": "Word құжаты (.docx)", "Документ Markdown (.md)": "Markdown құжаты (.md)",
    "Приоритет замечаний": "Ақау басымдығы", "Все": "Барлығы", "Блокирующие": "Бөгейтін", "Существенные": "Маңызды",
    "Незначительные": "Ұсақ", "Критерий": "Критерий", "Все критерии": "Барлық критерий",
    "Строка контракта": "Келісімшарт жолы", "Разобрать пример": "Үлгіні талдау",
    "Разобрать замечание": "Ақауды қарау", "Редактировать правку": "Түзетуді өңдеу",
    "Требований": "Талап", "Замечаний": "Ақау", "Блокирующих": "Бөгейтін",
    "Перейти к исправлениям": "Түзетуге өту", "Скачать результат": "Нәтижені жүктеу",
    "Уточнение и правки": "Нақтылау және түзету", "Фильтры и вопросы автору": "Сүзгілер және авторға сұрақтар",
    "Поиск по требованиям": "Талаптардан іздеу", "Сбросить фильтры": "Сүзгілерді тазалау",
    "Ссылки": "Сілтемелер", "Внешние ссылки": "Сыртқы сілтемелер", "Строка в документе": "Құжаттағы жол", "Открыть ссылку": "Сілтемені ашу",
    "Открывается без входа в GitHub": "GitHub жүйесіне кірмей ашылады",
    "Изменения в документе": "Құжатқа енгізілген өзгерістер", "Было": "Бұрын", "Стало": "Кейін",
    "Публичный доступ не подтверждён": "Ашық қолжетімділік расталмады",
    "Проверьте вручную в приватном окне": "Жеке браузер терезесінде тексеріңіз",
    "Проверьте по источнику": "Түпнұсқамен салыстырыңыз", "Критично": "Сындарлы", "Важно": "Маңызды",
    "Замечание": "Ескерту", "Совет": "Кеңес", "Что исправить первым": "Алдымен түзетілетіндер",
    "Отложить": "Кейінге қалдыру", "Вернуть в список": "Тізімге қайтару",
    "Доступ подтверждён": "Қолжетімділігі расталды", "Не удалось проверить доступ": "Қолжетімділігін тексеру мүмкін болмады",
    "Проверка адреса заблокирована": "Мекенжайды тексеруге тыйым салынған", "Получено перенаправление": "Басқа мекенжайға бағыттайды",
  };
  const local = (ru, en, kazakh) => language === "en" ? en : language === "kk" ? (kazakh || kk[ru] || ru) : ru;
  function labelText(element, ru, en) {
    const label = document.createTextNode(local(ru, en));
    element.prepend(label);
    translations.push(() => { label.data = local(ru, en); });
    return element;
  }
  function labelAttribute(element, attribute, ru, en, suffix) {
    const update = () => element.setAttribute(attribute, local(ru, en) + (suffix ? " · " + suffix : ""));
    translations.push(update);
    update();
  }
  const scroller = node("div", "", "audit-scroll");
  const navigation = node("div", "", "audit-navigation");
  navigation.setAttribute("role", "group");
  labelAttribute(navigation, "aria-label", "Разделы аудита", "Audit sections");
  const panels = new Map();
  const sections = [
    ["overview", "Итог", "Summary", null],
    ["findings", "Правки", "Revisions", findings.length],
  ];
  if (comparison) sections.push(["changes", "Сравнение", "Comparison", null]);
  sections.push(["files", "Файлы", "Files", null],
    ["requirements", "Отдельные требования", "Individual requirements", null], ["checks", "Набор в целом", "Whole set", null]);
  let activePanel;
  for (const [key, ru, en, amount] of sections) {
    const panel = node("section", "", "audit-pane");
    panel.id = "audit-pane-" + key;
    panel.tabIndex = -1;
    labelAttribute(panel, "aria-label", ru, en);
    let button;
    if (["overview", "requirements", "checks"].includes(key)) {
      button = labelText(node("button", "", "audit-tab"), ru, en);
      button.type = "button";
      button.setAttribute("aria-controls", panel.id);
      if (amount !== null) button.append(" ", node("span", String(amount), "audit-tab-count"));
      button.addEventListener("click", () => {
        showPanel(key);
        panel.focus();
      });
      navigation.append(button);
    }
    panels.set(key, { panel, button });
  }

  function showPanel(selected) {
    if (selected === activePanel) return;
    activePanel = selected;
    for (const [key, { panel, button }] of panels) {
      panel.hidden = key !== selected;
      button?.setAttribute("aria-pressed", String(key === selected));
    }
    navigation.hidden = !panels.get(selected).button;
    host.closest(".results-panel")?.scrollTo({ top: 0 });
    onPanelChange();
  }

  function panelAction(ru, en, panel, primary = false) {
    const button = labelText(node("button", "", primary ? "button primary" : "button secondary"), ru, en);
    button.type = "button";
    button.addEventListener("click", () => {
      showPanel(panel);
      panels.get(panel).panel.focus();
    });
    return button;
  }

  const header = node("header", "", "audit-summary");
  header.dataset.readiness = audit.readiness;
  const meta = node("div", "", "audit-run-meta");
  const badges = node("div", "", "audit-scope");
  badges.append(labelText(node("span", "", "audit-mode"), rulesOnly ? "Локальные правила · ограниченный охват" : mode,
    rulesOnly ? "Local rules · limited scope" : "AI and local rules"));
  if (unreadPages.length) badges.append(node("span", audit.pdf_origin ? "Текст из неполного PDF" : "PDF прочитан частично",
    "audit-mode audit-mode-limited"));
  const readiness = { blocked: "Blocking findings", clarify: "Clarification needed", ready: "Ready", limited: "Limited review" };
  meta.append(labelText(node("strong", "", "audit-readiness"), labels[audit.readiness], readiness[audit.readiness]), badges);
  header.append(meta);

  const reportDownloads = node("div", "", "audit-actions");
  function reportButton(format) {
    const button = labelText(node("button", "", "button button-compact secondary"),
      format === "md" ? "Отчёт (.md)" : "Данные (.json)", format === "md" ? "Report (.md)" : "Data (.json)");
    button.type = "button";
    labelAttribute(button, "aria-label", format === "md" ? "Скачать отчёт (.md)" : "Скачать данные (.json)",
      format === "md" ? "Download report (.md)" : "Download data (.json)");
    button.addEventListener("click", () => download(format));
    return button;
  }
  reportDownloads.append(reportButton("md"), reportButton("json"));
  header.append(reportButton("md"));
  const documentDownloads = node("div", "", "audit-actions");
  const documentHint = node("p", "", "audit-verdict");
  const documentStatus = node("p", "", "audit-mode-note");
  documentStatus.setAttribute("role", "status");
  documentStatus.hidden = true;
  const queuedFindings = new Set();
  let exportingDocument = false;
  function updateFileActions() {
    documentHint.textContent = queuedFindings.size ? local("Внесите правки и перепроверьте документ перед скачиванием.",
      "Apply the edits and recheck before downloading.")
      : findings.length ? local("В документе могут остаться замечания.", "The document may still contain open findings.")
        : local("Версия документа после последней проверки.", "The version from the last review.");
    for (const button of documentDownloads.children) button.disabled = exportingDocument || queuedFindings.size > 0;
  }
  for (const [format, label] of [["docx", "Word (.docx)"], ["md", "Markdown (.md)"]]) {
    const button = labelText(node("button", "", format === "docx" ? "button primary" : "button secondary"),
      "Документ " + label, label);
    button.type = "button";
    button.addEventListener("click", async () => {
      exportingDocument = true;
      documentStatus.hidden = true;
      updateFileActions();
      try {
        await exportDocument(format);
      } catch (error) {
        documentStatus.textContent = error.message;
        documentStatus.hidden = false;
      } finally {
        exportingDocument = false;
        updateFileActions();
      }
    });
    documentDownloads.append(button);
  }
  updateFileActions();
  const documentFiles = node("section", "", "audit-overview");
  documentFiles.append(labelText(node("h3"), "Техническое задание", "Specification"), documentHint, documentDownloads, documentStatus);
  const reportFiles = node("section", "", "audit-overview");
  reportFiles.append(labelText(node("h3"), "Отчёт этого прогона", "Audit report"), reportDownloads);
  panels.get("files").panel.append(documentFiles, reportFiles);

  const list = node("div", "", "audit-list");
  list.id = "audit-findings-list";
  const priorityControls = node("div", "", "audit-priorities");
  priorityControls.setAttribute("role", "group");
  labelAttribute(priorityControls, "aria-label", "Приоритет замечаний", "Finding priority");
  const priorityNames = { all: "All", blocker: "Blocking", major: "Major", minor: "Minor" };
  const priorityButtons = new Map();
  let selectedPriority = "all";
  for (const [value, label] of Object.entries(priorities)) {
    const count = value === "all" ? findings.length : counts[value];
    if (!count) continue;
    const button = labelText(node("button", "", "audit-priority-filter"), label, priorityNames[value]);
    button.type = "button";
    button.dataset.severity = value;
    button.setAttribute("aria-controls", list.id);
    button.append(" ", node("strong", String(count)));
    button.addEventListener("click", () => {
      selectedPriority = value;
      filter();
    });
    priorityButtons.set(value, button);
    priorityControls.append(button);
  }
  const criteriaLabel = labelText(node("label", "", "audit-criterion"), "Критерий", "Criterion");
  const criterion = node("select");
  const criteria = [...new Set(findings.map(item => item.criterion))].sort((a, b) => a.localeCompare(b, "ru"));
  for (const name of ["", ...criteria]) {
    const option = name ? node("option", name) : labelText(node("option"), "Все критерии", "All criteria");
    option.value = name;
    criterion.append(option);
  }
  criteriaLabel.hidden = criteria.length < 2;
  criteriaLabel.append(criterion);
  const start = node("button", "", "button primary");
  start.type = "button";
  const openSampleSource = labelText(node("button", "", "button secondary"), "Строка контракта", "API contract row");
  openSampleSource.type = "button";
  openSampleSource.hidden = true;
  if (demoCitation) openSampleSource.addEventListener("click", () => openEvidence(demoFinding, demoCitation));
  const controls = node("div", "", "audit-finding-actions");
  controls.append(start, openSampleSource);
  const nextStep = node("p", "", "audit-verdict audit-next-step");
  let nextFinding;
  start.addEventListener("click", () => {
    if (nextFinding) openRepair(nextFinding);
  });
  const shown = node("p", "", "audit-filter-count");
  shown.setAttribute("role", "status");
  const questionActions = node("div", "", "audit-actions");
  const questions = labelText(node("button", "", "button button-compact secondary"), "Вопросы автору (.txt)", "Author questions (.txt)");
  questions.type = "button";
  labelAttribute(questions, "aria-label", "Скачать вопросы по показанным замечаниям (.txt)", "Download questions for visible findings (.txt)");
  questions.addEventListener("click", () => {
    const visible = orderedFindings.filter(item => !cards.get(item.id).hidden);
    download("questions", formatAuditQuestions(visible));
  });
  questionActions.append(questions);
  const empty = node("div", "", "audit-filter-empty");
  const resetFilters = labelText(node("button", "", "button button-compact secondary"), "Сбросить фильтры", "Reset filters");
  resetFilters.type = "button";
  resetFilters.addEventListener("click", () => {
    selectedPriority = "all";
    criterion.value = "";
    filter();
    priorityButtons.get("all").focus();
  });
  empty.append(labelText(node("p", "", "audit-verdict"), "По этим фильтрам нарушений нет.", "No findings match these filters."), resetFilters);
  function filter() {
    for (const [value, button] of priorityButtons) button.setAttribute("aria-pressed", String(value === selectedPriority));
    const visible = orderedFindings.filter(item => {
      const card = cards.get(item.id);
      card.hidden = (selectedPriority !== "all" && card.dataset.severity !== selectedPriority)
        || (Boolean(criterion.value) && card.dataset.criterion !== criterion.value);
      return !card.hidden;
    });
    const available = visible.filter(item => !item.visual_evidence &&
      cards.get(item.id).dataset.queued !== "true" && cards.get(item.id).dataset.deferred !== "true");
    const offerDemo = demoCitation && available.includes(demoFinding);
    nextFinding = offerDemo ? demoFinding : available[0];
    controls.hidden = !nextFinding;
    if (nextFinding) start.textContent = offerDemo ? local("Разобрать пример", "Review the example")
      : local(`Ответить на вопрос ${nextFinding.id}`, `Answer ${nextFinding.id}`);
    openSampleSource.hidden = !offerDemo;
    nextStep.textContent = offerDemo ? local("Контракт использует GET для создания заявки. Согласуйте метод и перепроверьте ТЗ.",
      "The contract uses GET to create a refund request. Confirm the method and recheck the specification.")
      : !nextFinding && visible.some(item => item.visual_evidence) ? local("Сверьте исходный рисунок с таблицей.", "Compare the original diagram with the table.")
        : !nextFinding && visible.length ? local("Правки к показанным замечаниям подготовлены.", "Edits for the visible findings are queued.") : "";
    shown.textContent = visible.length === findings.length || !visible.length ? ""
      : local(`Показано ${visible.length} из ${findings.length}`, `Showing ${visible.length} of ${findings.length}`);
    questions.disabled = !visible.length;
    empty.hidden = visible.length > 0 || !findings.length;
  }
  criterion.addEventListener("change", filter);

  function reveal(card) {
    card.closest(".audit-section")?.setAttribute("open", "");
    card.open = true;
    card.firstElementChild.focus({ preventScroll: true });
    card.scrollIntoView({ block: "nearest" });
  }

  function revealFinding(id) {
    const card = cards.get(id);
    if (!card) return;
    showPanel("findings");
    if (card.hidden) {
      selectedPriority = "all";
      criterion.value = "";
      filter();
    }
    reveal(card);
  }

  function links(ids, activate, label = id => id) {
    const group = node("div", "", "audit-links");
    for (const id of ids) {
      const button = node("button", label(id), "button button-compact secondary");
      button.type = "button";
      button.addEventListener("click", () => activate(id));
      group.append(button);
    }
    return group;
  }

  for (const item of orderedFindings) {
    const card = details("", "audit-card");
    card.dataset.severity = item.severity;
    card.dataset.criterion = item.criterion;
    const levels = { blocker: ["! ", "Критично", "Critical"], major: ["◆ ", "Важно", "Major"],
      minor: ["• ", "Замечание", "Finding"] };
    const [icon, ruSeverity, enSeverity] = item.kind === "advice" ? ["ⓘ ", "Совет", "Advice"] : levels[item.severity];
    if (item.kind === "advice") card.dataset.advice = "true";
    const priority = labelText(node("span", "", "audit-priority"), ruSeverity, enSeverity);
    priority.prepend(item.id + " · " + icon);
    card.firstElementChild.append(priority, node("span", item.explanation));
    if (item.confidence === "low") {
      card.append(labelText(node("p", "", "audit-mode-note"), "Проверьте по источнику", "Verify against the source"));
    }
    card.append(fact(item.criterion, item.engine), evidenceList(item.evidence, source => openEvidence(item, source), labelText, labelAttribute),
      fact("Вопрос автору", item.question), fact("Что исправить", item.next_step));
    if (item.visual_evidence) {
      const { number, event, figure_status, table_status, observed } = item.visual_evidence;
      card.append(fact(`Рисунок ${number} · чтение ИИ`, observed ?? `${event} · ${figure_status}`));
      if (table_status) card.append(fact("Статус в таблице", table_status));
    }
    if (item.requirements.length) {
      const linked = links(item.requirements, revealRequirement, id => requirementLabels.get(id));
      linked.setAttribute("aria-label", "Связанные требования");
      linked.setAttribute("role", "group");
      card.append(linked);
    }
    if (item.visual_evidence) {
      card.append(node("p", "Сверьте рисунок. Для правки обновите исходный файл и загрузите его снова.", "audit-mode-note"));
    } else {
      const repair = node("button", local("Разобрать замечание", "Review finding"), "button primary");
      repair.type = "button";
      repair.addEventListener("click", () => openRepair(item));
      repairButtons.set(item.id, repair);
      card.append(repair);
    }
    const defer = node("button", "", "button button-compact text-button");
    defer.type = "button";
    const updateDefer = () => {
      const deferred = card.dataset.deferred === "true";
      defer.textContent = deferred ? local("Вернуть в список", "Restore") : local("Отложить", "Defer");
      defer.setAttribute("aria-pressed", String(deferred));
    };
    defer.addEventListener("click", () => {
      card.dataset.deferred = String(card.dataset.deferred !== "true");
      updateDefer();
      filter();
    });
    translations.push(updateDefer);
    updateDefer();
    card.append(defer);
    cards.set(item.id, card);
    list.append(card);
  }
  if (!findings.length) {
    list.append(labelText(node("p", "", "audit-verdict"),
      rulesOnly ? "Локальные правила не нашли нарушений в поддерживаемых сценариях." : "Проверка завершена. Нарушения не зафиксированы.",
      rulesOnly ? "Local rules found no issues in the scenarios they cover." : "The audit found no issues."));
  }
  filter();

  const findingsPanel = panels.get("findings").panel;
  const overview = node("section", "", "audit-overview");
  const verdict = node("p", audit.verdict, "audit-verdict");
  verdict.lang = "ru";
  overview.append(node("h3", audit.document), verdict);
  const totals = node("dl", "", "audit-totals");
  for (const [ru, en, value] of [["Требований", "Requirements", requirements.length],
    ["Замечаний", "Findings", findings.length], ["Блокирующих", "Blocking", counts.blocker],
    ["Важно", "Major", counts.major], ["Замечание", "Minor", counts.minor]]) {
    const tally = node("div");
    tally.append(labelText(node("dt"), ru, en), node("dd", String(value)));
    totals.append(tally);
  }
  overview.append(totals);
  if (findings.length) {
    const prioritiesList = node("section", "", "audit-first-actions");
    const first = node("ol");
    for (const item of orderedFindings.slice(0, 3)) {
      const row = node("li");
      const button = node("button", item.id + " · " + item.question, "button text-button");
      button.type = "button";
      button.addEventListener("click", () => revealFinding(item.id));
      row.append(button);
      first.append(row);
    }
    prioritiesList.append(labelText(node("h3"), "Что исправить первым", "Fix these first"), first);
    overview.append(prioritiesList);
  }
  if (unreadPages.length) overview.append(node("p", `Страницы без читаемого текста — ${unreadPages.join(", ")}.`, "audit-mode-note"));
  if (audit.visual_review?.status === "completed") {
    overview.append(node("p", `Переходов на схемах сверено с таблицами — ${audit.visual_review.compared}. Проверьте чтение и остальные рисунки вручную.`, "audit-mode-note"));
  } else if (audit.visual_review?.status === "reviewed") {
    overview.append(node("p", `Изображений передано на проверку — ${audit.visual_review.sent}. По исходнику проверьте возможные расхождения.`, "audit-mode-note"));
  } else if (audit.unreviewed_figures) {
    overview.append(node("p", "Аудит проверил текст. Сверьте схемы и изображения с требованиями вручную.", "audit-mode-note"));
  }
  const nextActions = node("div", "", "audit-finding-actions");
  if (findings.length) nextActions.append(panelAction("Перейти к исправлениям", "Review findings", "findings", true));
  nextActions.append(panelAction("Скачать результат", "Download results", "files", !findings.length));
  overview.append(nextActions);
  panels.get("overview").panel.append(overview);
  if (findings.length) {
    const guide = node("section", "", "audit-overview");
    guide.classList.add("audit-revision-guide");
    guide.append(labelText(node("h3"), "Уточнение и правки", "Resolve findings"), nextStep, controls);
    findingsPanel.append(guide);
    const filters = details("", "audit-section audit-filters");
    labelText(filters.firstElementChild, "Фильтры и вопросы автору", "Filters and author questions");
    filters.append(priorityControls, criteriaLabel, shown, questionActions);
    findingsPanel.append(filters);
  }
  findingsPanel.append(list, empty);

  const searchLabel = labelText(node("label", "", "audit-search"), "Поиск по требованиям", "Search requirements");
  const coverage = assessmentCoverage(requirements);
  const coverageLine = node("p", "", "audit-verdict");
  function updateCoverage() {
    coverageLine.textContent = rulesOnly
      ? local("Проверка по правилам. Индивидуальная оценка ИИ не проводилась.", "This run used local rules. Individual AI assessment was skipped.")
      : coverage.recorded
        ? local(`Индивидуальную оценку ИИ получили ${coverage.reviewed} из ${coverage.total}.`,
          `Individually assessed by AI: ${coverage.reviewed} of ${coverage.total}.`, `ЖИ жеке бағалаған талаптар саны — ${coverage.reviewed} / ${coverage.total}.`)
        : local("В этом отчёте не указан охват индивидуальной оценки ИИ.", "This report does not record individual AI assessment coverage.");
  }
  updateCoverage();
  translations.push(updateCoverage);
  const uncheckedOnly = node("input");
  uncheckedOnly.type = "checkbox";
  const uncheckedFilter = node("label", "", "audit-unchecked-filter");
  uncheckedFilter.append(uncheckedOnly, labelText(node("span"), "Только без индивидуальной оценки", "Show only requirements awaiting assessment"));
  uncheckedFilter.hidden = rulesOnly || !coverage.unchecked;
  const search = node("input");
  search.type = "search";
  labelAttribute(search, "placeholder", "Например, Ф-2, L38 или «порог»", "For example, Ф-2, L38 or a term");
  searchLabel.append(search);
  const searchStatus = node("p", "", "audit-search-status");
  searchStatus.setAttribute("role", "status");
  const inventory = node("div", "", "audit-list");
  for (const item of requirements) {
    const location = [...new Set([item.source_id, item.id, item.source.location].filter(Boolean))].join(" · ");
    const card = details("", "audit-card audit-requirement");
    const cells = tableRow(item.summary) ? tableCells(item.summary).filter(Boolean) : [];
    card.firstElementChild.append(node("span", location, "audit-requirement-meta"),
      node("span", cells.length ? cells.join(" · ") : item.summary));
    const unchecked = item.assessment_status === "unchecked";
    if (!rulesOnly && unchecked) card.firstElementChild.append(
      labelText(node("small", "", "audit-mode-note"), "Требует индивидуальной сверки", "Needs individual assessment"));
    card.append(evidenceList([item.source], source => openEvidence(item, source), labelText, labelAttribute), fact("Оценка", item.assessment));
    if (item.findings.length) {
      card.append(links(item.findings, revealFinding));
    }
    const text = normalizedSearch([location, item.summary, item.source.section, item.source.quote].join(" "));
    requirementCards.set(item.id, { card, text, unchecked });
    inventory.append(card);
  }
  function filterRequirements() {
    const terms = normalizedSearch(search.value).split(/\s+/u).filter(Boolean);
    let count = 0;
    for (const { card, text, unchecked } of requirementCards.values()) {
      card.hidden = (uncheckedOnly.checked && !unchecked) || !terms.every(term => text.includes(term));
      if (!card.hidden) count++;
    }
    searchStatus.textContent = !requirements.length ? local("В этом прогоне требования не выделены.", "No requirements were extracted.")
      : count ? local(`Требований показано: ${count} из ${requirements.length}`, `Showing ${count} of ${requirements.length}`,
        `Көрсетілген талаптар — ${count} / ${requirements.length}`)
        : local("Требования по этому запросу не найдены.", "No requirements match your search.");
  }
  function revealRequirement(id) {
    const entry = requirementCards.get(id);
    if (!entry) return;
    showPanel("requirements");
    if (entry.card.hidden) {
      search.value = "";
      uncheckedOnly.checked = false;
      filterRequirements();
    }
    reveal(entry.card);
  }
  search.addEventListener("input", filterRequirements);
  uncheckedOnly.addEventListener("change", filterRequirements);
  filterRequirements();
  panels.get("requirements").panel.append(coverageLine, searchLabel, uncheckedFilter, searchStatus, inventory);
  const checks = details("", "audit-section");
  labelText(checks.firstElementChild, "Проверка набора требований", "Assessment of the whole set");
  checks.open = true;
  for (const check of audit.checks) {
    const row = details(`${check.criterion} · ${check.status}`, "audit-card");
    row.append(node("p", check.comment, "audit-verdict"),
      evidenceList(check.evidence, source => openEvidence(check, source, true), labelText, labelAttribute));
    setCards.set(check.criterion, row);
    checks.append(row);
  }
  const provenance = details("", "audit-section");
  labelText(provenance.firstElementChild, "Паспорт прогона", "Run details");
  for (const [ru, en, value] of [["Файл", "File", audit.file], ["Время", "Timestamp", audit.generated_at],
    ["Коммит SanA1", "SanA1 commit", audit.version], ["SHA-256", "SHA-256", audit.sha256], ["Режим", "Mode", mode]]) {
    const field = fact("", value);
    labelText(field.firstElementChild, ru, en);
    provenance.append(field);
  }
  for (const stage of audit.passes) provenance.append(fact(stage.stage, stage.model));
  const notices = node("div", "", "audit-notices");
  for (const warning of audit.warnings) notices.append(node("p", warning));
  const passport = panels.get("checks").panel;
  passport.append(notices, checks);
  passport.append(provenance);
  const linkPanel = details("", "audit-section");
  linkPanel.id = "audit-pane-links";
  labelText(linkPanel.firstElementChild, "Ссылки", "Links");
  linkPanel.firstElementChild.append(" · " + linkCount);
  if (linkCount) overview.append(linkPanel);
  if (internal.length) {
    const references = details("", "audit-section");
    labelText(references.firstElementChild, `Внутренние ссылки · ${internal.length}`, `Internal links · ${internal.length}`);
    references.open = true;
    const list = node("div", "", "audit-list");
    for (const link of internal) {
      const row = node("section", "", "audit-card");
      row.append(fact(link.target + " · " + link.label, link.origins.map(source => source.location).join(", ")));
      if (link.declarations.length) {
        row.append(fact("Где объявлен пункт", link.declarations.map(source => source.location).join(", ")));
      }
      const issue = link.status === "missing" && findings.find(item => item.criterion === "Прослеживаемость" &&
        item.evidence.some(ref => link.origins.some(origin => origin.line === ref.line)));
      if (issue) {
        const review = labelText(node("button", "", "button button-compact secondary"), "Разобрать замечание", "Review finding");
        review.type = "button";
        review.addEventListener("click", () => revealFinding(issue.id));
        row.append(review);
      }
      list.append(row);
    }
    references.append(list);
    linkPanel.append(references);
  }
  if (external.length) {
    const list = node("section", "", "audit-overview");
    list.append(labelText(node("h3"), "Внешние ссылки", "External links"));
    const statuses = {
      unchecked: ["Доступ не проверен", "Access not checked"],
      public: ["Доступ подтверждён", "Public access confirmed"],
      unconfirmed: ["Публичный доступ не подтверждён", "Public access could not be confirmed"],
      unavailable: ["Не удалось проверить доступ", "Access could not be checked"],
      blocked: ["Проверка адреса заблокирована", "Address check blocked"],
      redirect: ["Получено перенаправление", "Redirect returned"],
      manual: ["Проверьте вручную в приватном окне", "Check manually in a private window"],
    };
    const verified = new Map((audit.external_link_checks || []).map(check => [check.url, check.status]));
    for (const link of external) {
      const row = node("section", "", "audit-card");
      const address = node("p", link.url, "audit-link-address");
      const outcome = node("p", "", "audit-verdict");
      outcome.setAttribute("role", "status");
      const status = verified.get(link.url) || (link.check === "github" ? "unchecked" : "manual");
      outcome.dataset.linkStatus = status;
      const result = statuses[status] || statuses.unchecked;
      const update = () => { outcome.textContent = local(...result); };
      translations.push(update);
      update();
      row.append(address, node("p", link.origins.join(", "), "audit-requirement-meta"), outcome);
      const actions = node("div", "", "audit-finding-actions");
      if (openLinkSource && Number.isInteger(link.line)) {
        const source = labelText(node("button", "", "button text-button button-compact"), "Строка в документе", "Source line");
        source.type = "button";
        source.addEventListener("click", () => openLinkSource(link.line));
        actions.append(source);
      }
      if (status !== "blocked" && /^https?:\/\//i.test(link.url)) {
        const visit = labelText(node("a", "", "button text-button button-compact"), "Открыть ссылку", "Open link");
        visit.href = link.url;
        visit.target = "_blank";
        visit.rel = "noopener noreferrer";
        actions.append(visit);
      }
      row.append(actions);
      list.append(row);
    }
    linkPanel.append(list);
  }
  renderStructure?.(overview);
  if (modeChanged) panels.get("overview").panel.prepend(node("p", "Для сравнения запустите аудит в прежнем режиме.", "audit-mode-note"));
  if (comparison) {
    const actions = node("div", "", "audit-finding-actions");
    if (findings.length) actions.append(panelAction("Продолжить исправления", "Continue revisions", "findings", true));
    actions.append(panelAction("Скачать результат", "Download results", "files", !findings.length));
    panels.get("changes").panel.append(
      comparisonView(comparison, focusedBefore, confirmedBefore, revealFinding, appliedEdits, labelText), actions);
  }
  for (const { panel } of panels.values()) {
    panel.hidden = true;
    scroller.append(panel);
  }
  showPanel(panels.has(initialPanel) ? initialPanel : comparison ? "changes" : "overview");
  header.append(navigation);
  host.replaceChildren(header, scroller);
  function updateRepairLabel(button, queued) {
    button.textContent = queued ? local("Редактировать правку", "Edit queued revision") : local("Разобрать замечание", "Review finding");
  }
  return {
    revealFinding, revealRequirement, currentPanel: () => activePanel,
    revealSetCheck(criterion) {
      showPanel("checks");
      const card = setCards.get(criterion);
      if (card) reveal(card);
    },
    openPanel(key) {
      showPanel(key);
      panels.get(key).panel.focus();
    },
    setLanguage(next) {
      language = next;
      for (const translate of translations) translate();
      for (const [id, button] of repairButtons) updateRepairLabel(button, queuedFindings.has(id));
      updateFileActions();
      filterRequirements();
      filter();
    },
    markQueued(id, queued) {
      const button = repairButtons.get(id);
      const card = cards.get(id);
      updateRepairLabel(button, queued);
      card.dataset.queued = String(queued);
      if (queued) queuedFindings.add(id);
      else queuedFindings.delete(id);
      updateFileActions();
      filter();
    },
  };
}
