import { mountProfiles } from "/spec-profiles.js";
import { downloadWord } from "/word-export.js";
import { strings } from "/strings.js";
import { formattedCopy, renderDocument, pipeRow, tableCells, tableRow } from "/document-view.js";
import { evidenceSelection, renderAudit } from "/audit-view.js";
import { compareAudits } from "/audit-compare.js";
import { applyRevisionPatches, showRevision } from "/audit-repair.js";
import { clearWorkspaceSession, readWorkspaceSession, recoverableAudit, writeWorkspaceSession } from "/workspace-session.js";
import { mountHeroField } from "/hero-field.js";

const select = (id) => document.getElementById(id);
mountHeroField(select("hero-field"));
let spec = select("spec");
const resultBox = select("results");
const allowedFiles = new Set(["txt", "md", "markdown", "docx", "pdf"]);
const draftReplacementInputs = new Set([
  "insertText", "insertReplacementText", "insertFromPaste", "deleteByCut",
  "deleteContentBackward", "deleteContentForward", "deleteWordBackward", "deleteWordForward",
]);
const categories = ["all", "consistency", "testability", "completeness"];
const eventStream = "application/x-ndjson";
const reviewSteps = new Set(["segment", "references", "wording", "compare", "scenarios", "report", "model", "verify"]);
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
const wideWorkspace = matchMedia("(min-width: 1100px)");
const routes = {
  "/": { view: "home", heading: "home-heading", title: "reviewTitle" },
  "/workspace": { view: "review", heading: "review-heading", title: "reviewNav" },
};

function savedLanguage() {
  try {
    const saved = localStorage.getItem("sana1-language");
    return Object.hasOwn(strings, saved) ? saved : "ru";
  }
  catch { return "ru"; }
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const light = theme === "light";
  select("theme-toggle").setAttribute("aria-pressed", String(light));
  select("theme-toggle").textContent = light ? copy().darkTheme : copy().lightTheme;
  document.querySelector('meta[name="theme-color"]').content = light ? "#f4f7f4" : "#090b0a";
}

function newDocumentState() {
  return {
    file: "", notice: "", report: null, filter: "all", query: "", sourceFinding: "",
    hackathonBusy: false, hackathonStatus: "", audit: null, auditBaseline: null, auditHandoff: null, auditController: null,
    auditStages: [], auditStarted: 0, auditUndo: null,
    auditDecisions: new Map(), reportSource: null,
    busy: false, loading: null, controller: null,
    reviewError: "", documentView: "source", media: [], pdfUrl: "", pdfReader: null, undo: [],
    reviewRun: null, clarifications: [],
    reviewedText: "", revision: null, comparison: null, editedLines: new Set(), answers: new Map(),
  };
}

const state = {
  ...newDocumentState(), lang: savedLanguage(), auditDemo: false,
  config: { max_chars: 50000, max_upload: 4 * 1024 * 1024, gemini: null },
  loadAttempt: 0, reviewAttempt: 0,
};
const documentStateKeys = Object.keys(newDocumentState());
let draftWorkspace = null;
let activeCase = null;
let recoveryEnabled = false;
let recoveryStatus = "";
let recoveryTimer;

function tabStorage() {
  try { return window.sessionStorage; }
  catch { return null; }
}

const copy = () => strings[state.lang];
const number = (value) => new Intl.NumberFormat(state.lang).format(value);
const profileGuide = mountProfiles(select("profile-host"), {
  language: () => state.lang,
  getText: () => spec.value,
  applyText: applyStructuralRevision,
});

function element(tag, content = "", className = "") {
  const node = document.createElement(tag);
  if (content !== "") node.textContent = content;
  if (className) node.className = className;
  return node;
}

function addNotice(parent, code) {
  parent.append(element("p", copy().errors[code] || copy().errors.generic, "notice"));
}

async function responseFor(url, options) {
  let response;
  try { response = await fetch(url, options); }
  catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error("network");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const fallback = { 408: "server_timeout", 429: "rate_limited", 504: "server_timeout" }[response.status];
    const failure = new Error(data.error || fallback || "generic");
    failure.status = response.status;
    if (data.error === "clarification_needed" && typeof data.question === "string") failure.question = data.question;
    throw failure;
  }
  return response;
}

async function request(url, options) {
  return (await responseFor(url, options)).json();
}

async function requestEvents(url, options, onStage, onProgress) {
  const response = await responseFor(url, {
    ...options, headers: { ...options.headers, Accept: eventStream },
  });
  if (!response.headers.get("Content-Type")?.startsWith(eventStream)) return response.json();
  if (!response.body) throw new Error("generic");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let report;
  const consume = (line) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "stage") onStage(event);
    if (event.type === "progress") onProgress?.(event);
    if (event.type === "result") report = event.report;
    if (event.type === "error") throw new Error(event.error || "generic");
  };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      const lines = pending.split("\n");
      pending = lines.pop();
      lines.forEach(consume);
      if (done) {
        consume(pending);
        if (!report) throw new Error("stream_interrupted");
        return report;
      }
    }
  } catch (error) {
    await reader.cancel().catch(() => {});
    if (error instanceof TypeError || error instanceof SyntaxError) throw new Error("stream_interrupted");
    throw error;
  } finally {
    reader.releaseLock();
  }
}

function activityText({ key, args }) {
  const message = copy().activity[key];
  return typeof message === "function" ? message(...args.map(number)) : message;
}

function activityLine(entry) {
  const line = element("li");
  line.dataset.status = entry.status;
  const mark = element("span", { active: "›", complete: "✓", error: "!" }[entry.status], "activity-prompt");
  mark.setAttribute("aria-hidden", "true");
  line.append(mark, element("span", activityText(entry), "activity-text"));
  return line;
}

function activityConsole(prefix, onPlayed) {
  const consoleBox = select(prefix + "activity-console");
  const lines = select(prefix + "activity-lines");
  const badge = select(prefix + "activity-state");
  const announcer = prefix === "" ? select("review-announcement") : null;
  let entries = [];
  let playback = Promise.resolve();
  let version = 0;

  function showStatus(status = entries.at(-1)?.status) {
    consoleBox.hidden = !status;
    if (!status) return;
    badge.dataset.status = status;
    badge.textContent = copy().activityStatus[status];
  }

  function render() {
    lines.replaceChildren(...entries.map(activityLine));
    showStatus();
    if (announcer) announcer.textContent = entries.length ? activityText(entries.at(-1)) : "";
  }

  function clear() {
    version++;
    playback = Promise.resolve();
    entries = [];
    consoleBox.open = false;
    render();
  }

  function add(key, { reset = false, status = "active", args = [] } = {}) {
    if (reset) clear();
    const entry = { key, status, args };
    const current = version;
    playback = playback.then(async () => {
      if (current !== version) return;
      const line = activityLine(entry);
      entries.push(entry);
      showStatus("active");
      lines.append(line);
      if (announcer) announcer.textContent = activityText(entry);
      const panel = status === "active" && onPlayed(entry);
      if (panel && panel.getClientRects().length && !reducedMotion.matches && !document.hidden) {
        // Keep streamed stages legible even when several records arrive in one packet.
        await new Promise((resolve) => setTimeout(resolve, 390));
      }
      if (current !== version) return;
      showStatus();
    });
    return playback;
  }

  return { add, clear, render, latest: () => entries.at(-1) };
}

const reviewActivity = activityConsole("", (entry) => advanceOperation(state.reviewRun, entry));
const { add: addActivity, clear: clearActivity } = reviewActivity;

function routing() {
  const current = routes[location.pathname] || routes["/"];
  for (const { view } of Object.values(routes)) {
    const active = view === current.view;
    select(view + "-page").hidden = !active;
    const nav = select("nav-" + view);
    if (active) nav.setAttribute("aria-current", "page");
    else nav.removeAttribute("aria-current");
  }
  document.title = "SanA1 · " + copy()[current.title];
}

function navigate(destination) {
  if (location.pathname + location.search === destination && !location.hash) return;
  history.pushState(null, "", destination);
  syncWorkspaceRoute();
  window.scrollTo(0, 0);
  select(routes[location.pathname].heading).focus({ preventScroll: true });
}

function translate() {
  document.documentElement.lang = state.lang;
  setTheme(document.documentElement.dataset.theme || "dark");
  profileGuide.refresh();
  for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = copy()[node.dataset.i18n];
  select("workflow").setAttribute("aria-label", copy().workflowLabel);
  state.audit?.setLanguage(state.lang);
  for (const node of document.querySelectorAll("[data-placeholder]")) node.placeholder = copy()[node.dataset.placeholder];
  for (const button of document.querySelectorAll("[data-lang]")) {
    button.setAttribute("aria-pressed", String(button.dataset.lang === state.lang));
  }
  document.querySelector(".navigation").setAttribute("aria-label", copy().workspace);
  document.querySelector(".language").setAttribute("aria-label", copy().language);
  routing();
  setWorkspacePane(select("review-page").dataset.pane);
  renderEditor();
  reviewActivity.render();
  renderReport();

}

function renderEditor() {
  renderDocumentView();
  if (state.audit && state.audit.text !== spec.value) {
    state.auditBaseline = state.audit;
    clearAudit();
  }
  renderAuditHandoff();
  const length = Array.from(spec.value).length;
  const hasDocument = Boolean(length || state.file);
  select("review-page").dataset.hasDocument = String(hasDocument);
  select("editor-actions").hidden = !hasDocument;
  const queued = Boolean(state.audit?.edits.size);
  spec.readOnly = queued;
  document.querySelector(".file-row").classList.toggle("file-start", !length && !state.file);
  const readable = spec.value.replace(/!\[([^\]]*)\]\(attachment:fig-\d+\)/g, "$1");
  const words = readable.match(/\p{L}+/gu)?.length || 0;
  select("min-length-tip").hidden = !length || words >= 4;
  select("count").textContent = number(length) + " / " + number(state.config.max_chars);
  const unavailable = queued || state.busy || state.hackathonBusy || state.loading || words < 4 || length > state.config.max_chars;
  select("hackathon-report").disabled = unavailable;
  select("hackathon-report").classList.toggle("primary", !state.audit);
  select("hackathon-report").classList.toggle("secondary", Boolean(state.audit));
  select("demo-load").hidden = hasDocument;
  select("demo-load").disabled = Boolean(state.loading);
  select("demo-load").textContent = activeCase === "official" ? copy().retryOfficial : copy().demoLoad;
  select("workspace-official").hidden = hasDocument || Boolean(activeCase) || Boolean(state.loading);
  select("clear").hidden = !spec.value && !state.file && !state.loading && !state.notice;
  select("file-name").hidden = !state.file;
  select("file-name-text").textContent = state.file;
  select("file-name").title = state.file;
  select("clear").title = copy().clear;
  select("review-method").textContent = queued ? copy().pendingInAudit
    : !length && state.pdfReader ? copy().errors.scanned_document
    : copy().automaticReview;
  const notice = select("editor-notice");
  const unread = state.reportSource?.pdfCoverage?.unread || [];
  const fileNotice = state.notice === "unreviewed_figures" ? "" : state.notice;
  const code = fileNotice || (unread.length ? state.reportSource.text ? "partial_pdf" : length ? "pasted_scan_text" : "scanned_document" : "");
  notice.hidden = !code && !state.loading && length <= state.config.max_chars;
  notice.classList.toggle("is-loading", Boolean(state.loading));
  select("editor-notice-message").textContent = state.loading
    ? copy()[state.loading === "official" ? "loadingOfficial" : state.loading === "file" ? "reading" : "loadingExample"]
    : (code === "official_input_unavailable" ? copy().officialUnavailable : copy().errors[code] || (length > state.config.max_chars ? copy().errors.text_too_long : "")) +
      (code === "partial_pdf" && unread.length ? " " + copy().unreadPages + " — " + unread.map(number).join(", ") + "." : "");
  renderRecovery();
  renderAuditProgress();
  scheduleRecovery();
}

function renderAuditProgress() {
  const run = state.audit;
  const panel = run?.currentPanel();
  const hasDocument = Boolean(spec.value.trim());
  const needsRecheck = Boolean(state.auditBaseline && state.auditBaseline.text !== spec.value);
  const viewingDocument = select("review-page").dataset.pane === "document" && !isSplitWorkspace();
  const step = state.hackathonBusy ? (needsRecheck ? 3 : 1)
    : !run && needsRecheck ? 3 : !run || viewingDocument ? 0
      : panel === "files" ? 4 : panel === "changes" ? 3 : panel === "findings" ? 2 : 1;
  const complete = [hasDocument, Boolean(run || state.auditBaseline), state.auditDecisions.size > 0,
    Boolean(run?.comparison), false];
  const available = [true, Boolean(run || !select("hackathon-report").disabled), Boolean(run),
    Boolean(run?.comparison || run?.edits.size || needsRecheck), Boolean(run)];
  for (const [index, item] of [...select("audit-progress").children].entries()) {
    if (index === step) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
    item.dataset.complete = String(complete[index]);
    const button = item.firstElementChild;
    button.disabled = false;
    button.dataset.locked = String(!available[index]);
    button.firstElementChild.textContent = complete[index] && index !== step ? "✓" : index + 1;
  }
  renderAuditPipeline();
}

const phaseOf = { submit: "upload", read: "read", segment: "segment", requirements: "requirements",
  rules: "requirements", reused: "requirements", consistency: "consistency", figures: "consistency", references: "consistency",
  verified: "consistency", report: "report" };

function renderAuditPipeline() {
  const items = [...select("audit-pipeline").children];
  const event = state.auditStages.at(-1);
  const failure = Object.hasOwn(copy().auditErrors, state.hackathonStatus) || state.hackathonStatus === "hackathonFailed";
  const finished = Boolean(state.audit) && !state.hackathonBusy && !failure;
  const phase = event && (state.hackathonBusy || failure) ? phaseOf[event.stage] : "upload";
  const active = items.findIndex(item => item.dataset.phase === phase);
  for (const [index, item] of items.entries()) {
    const done = finished || index < active;
    item.dataset.state = done ? "complete" : index === active ? (failure ? "error" : "current") : "pending";
    if (index === active && !finished) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
    item.firstElementChild.textContent = done ? "✓" : index === active && failure ? "!" : index + 1;
  }
}

function revealInside(scroller, target) {
  const area = scroller.getBoundingClientRect();
  const bounds = target.getBoundingClientRect();
  if (bounds.top < area.top || bounds.bottom > area.bottom) scroller.scrollTop += bounds.top - area.top;
}

function locateDocumentLine(line) {
  if (!Number.isInteger(line) || line < 1) return;
  setWorkspacePane("document");
  setDocumentView("preview");
  const preview = select("document-preview");
  const target = preview.querySelector('[data-source-line="' + line + '"]');
  if (!target) return;
  preview.querySelector(".source-highlight")?.classList.remove("source-highlight");
  target.classList.add("source-highlight");
  target.tabIndex = -1;
  target.focus({ preventScroll: true });
  target.scrollIntoView({ block: "nearest" });
  return true;
}

function setDocumentView(view) {
  state.documentView = view;
  renderDocumentView();
  scheduleRecovery();
}

let previewSource;
let gutterText;
function renderDocumentView() {
  const preview = select("document-preview");
  const hasText = Boolean(spec.value);
  const pdf = state.pdfReader;
  const pdfVisible = Boolean(pdf && state.documentView === "pdf");
  const visible = hasText && state.documentView === "preview";
  select("reading-tip").hidden = !visible;
  select("document-switch").hidden = !hasText && !pdf;
  select("show-document").hidden = !hasText;
  select("show-source").hidden = !hasText && !pdf;
  select("show-pdf").hidden = !pdf;
  select("attach-images").hidden = !hasText || Boolean(pdf);
  const downloads = select("document-downloads");
  downloads.hidden = !hasText;
  if (!hasText) downloads.open = false;
  select("show-source").setAttribute("aria-pressed", String(!visible && !pdfVisible));
  select("show-document").setAttribute("aria-pressed", String(visible));
  select("show-pdf").setAttribute("aria-pressed", String(pdfVisible));
  select("source-editor").hidden = visible || pdfVisible;
  preview.hidden = !visible;
  select("pdf-reader").hidden = !pdfVisible;
  if (pdfVisible) renderPdfReader(pdf);
  if (!visible && !pdfVisible) {
    const gutter = select("source-lines");
    gutter.hidden = !hasText;
    if (gutterText !== spec.value) {
      gutterText = spec.value;
      gutter.textContent = gutterText.split("\n").map((_, index) => index + 1).join("\n");
    }
    gutter.scrollTop = spec.scrollTop;
  }
  if (!visible) return;
  if (previewSource?.text === spec.value && previewSource.lang === state.lang && previewSource.media === state.media
      && previewSource.audit === state.audit) return;
  preview.replaceChildren(renderDocument(spec.value, state.media, copy(), editDocumentLine));
  markAuditSources(preview);
  previewSource = { text: spec.value, lang: state.lang, media: state.media, audit: state.audit };
}

function markAuditSources(preview) {
  const run = state.audit;
  if (!run || run.text !== spec.value) return;
  const lines = new Map([...preview.querySelectorAll("[data-source-line]")].map(node => [Number(node.dataset.sourceLine), node]));
  for (const finding of run.review.findings) {
    for (const { line } of finding.evidence) {
      const source = lines.get(line);
      if (!source || source.dataset.auditSeverity) continue;
      source.dataset.auditSeverity = finding.severity;
      const marker = element("button", finding.id, "doc-finding");
      marker.type = "button";
      marker.addEventListener("click", () => {
        setWorkspacePane("findings");
        run.revealFinding(finding.id);
      });
      (source.cells?.[0] || source).append(marker);
    }
  }
}

function renderPdfReader(pdf) {
  const t = copy();
  const image = select("pdf-image");
  const current = pdf.pages.get(pdf.page);
  image.hidden = !current;
  if (current && image.getAttribute("src") !== current) image.src = current;
  image.alt = t.page + " " + number(pdf.page);
  select("pdf-number").value = pdf.page;
  select("pdf-number").max = pdf.total;
  select("pdf-count").textContent = " / " + number(pdf.total);
  select("pdf-previous").disabled = pdf.page === 1;
  select("pdf-next").disabled = pdf.page === pdf.total;
  select("pdf-previous").setAttribute("aria-label", t.pdfPrevious);
  select("pdf-next").setAttribute("aria-label", t.pdfNext);
  select("download-pdf").href = state.pdfUrl;
  select("download-pdf").download = state.file;
  select("pdf-original-note").hidden = !state.reportSource || state.reportSource.text === spec.value;
  const status = select("pdf-status");
  status.hidden = Boolean(current);
  status.textContent = current ? "" : pdf.error ? t.pdfUnavailable : t.pdfLoading;
  select("pdf-retry").hidden = !pdf.error;
}

async function showPdfPage(page) {
  const pdf = state.pdfReader;
  if (!pdf) return;
  if (!Number.isInteger(page) || page < 1 || page > pdf.total) {
    renderPdfReader(pdf);
    return;
  }
  pdf.controller?.abort();
  pdf.page = page;
  pdf.error = false;
  renderPdfReader(pdf);
  if (pdf.pages.has(page)) return;
  const controller = new AbortController();
  pdf.controller = controller;
  try {
    const { src } = await request("/api/extract?page=" + page, {
      method: "POST", headers: { "Content-Type": "application/octet-stream", "X-File-Type": "pdf" },
      body: pdf.file, signal: controller.signal,
    });
    if (!src?.startsWith("data:image/jpeg;base64,")) throw Error("invalid_document");
    if (!controller.signal.aborted) pdf.pages.set(page, src);
  } catch {
    if (!controller.signal.aborted) pdf.error = true;
  } finally {
    if (pdf.controller === controller) {
      pdf.controller = null;
      if (pdf === state.pdfReader && state.documentView === "pdf") renderPdfReader(pdf);
    }
  }
}

async function addDocumentImages(files) {
  const status = select("document-format-notice");
  const previous = state.media;
  const attempt = state.loadAttempt;
  const media = [...previous];
  let added = 0;
  let rejected = 0;
  for (const file of files) {
    try {
      const existing = media.findIndex(image => image.name === file.name);
      if (!/^image\/(?:jpeg|png|webp)$/.test(file.type) || file.size > state.config.max_upload ||
          (existing < 0 && media.length >= 8)) throw Error();
      const bitmap = await createImageBitmap(file);
      try {
        if (bitmap.width * bitmap.height > 16_000_000) throw Error();
        const canvas = document.createElement("canvas");
        const scale = Math.min(1, 800 / bitmap.width, 900 / bitmap.height);
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        const context = canvas.getContext("2d", { alpha: false });
        context.fillStyle = "#fff";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        const id = existing < 0 ? "fig-" + (media.length + 1) : media[existing].id;
        const image = { id, name: file.name, src: canvas.toDataURL("image/jpeg", .78) };
        if (existing < 0) media.push(image);
        else media[existing] = image;
        added++;
      } finally { bitmap.close(); }
    } catch { rejected++; }
  }
  if (attempt !== state.loadAttempt || previous !== state.media) return;
  state.media = media;
  status.textContent = copy().imagesAdded(number(added), number(rejected));
  status.hidden = false;
  if (added) setDocumentView("preview");
}

function statePanel(kind, heading, description) {
  const panel = element("div", "", "empty");
  const art = select("document-art").content.firstElementChild.cloneNode(true);
  art.dataset.state = kind;
  const icon = { ready: "upload", clean: "check", error: "alert" }[kind];
  art.querySelector("use").setAttribute("href", "#icon-" + icon);
  panel.append(art, element("h3", heading), element("p", description));
  return panel;
}

const phaseIcons = { read: "document", links: "findings", rules: "scan", meaning: "model", verify: "check", finish: "document", cases: "findings", metrics: "evaluate" };
const eventPhases = {
  requested: "read", rechecking: "read", segment: "read", references: "links", wording: "rules", compare: "rules", scenarios: "rules", report: "rules", verify: "verify",
  model: "meaning", finalize: "finish", eval_start: "read", eval_cases: "cases", eval_metrics: "metrics",
};
let clockTimer = 0;

function tickClocks() {
  const clocks = document.querySelectorAll(".operation-clock");
  for (const clock of clocks) {
    const now = performance.now();
    const seconds = Math.floor((now - Number(clock.dataset.started)) / 1000);
    const value = Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
    if (clock.textContent !== value) clock.textContent = value;
    const panel = clock.closest(".review-loading");
    if (panel && state.reviewRun && !document.hidden && panel.getClientRects().length) {
      paintExcerpt(panel, state.reviewRun, now);
    }
  }
  if (!clocks.length) {
    clearInterval(clockTimer);
    clockTimer = 0;
  }
}

function makeOperation(kind, phases, entry) {
  return { kind, phases, active: phases[0], entry: { key: entry, args: [] }, started: performance.now(), skipModel: false };
}

function advanceOperation(run, entry) {
  if (!run || !(entry.key in eventPhases || entry.key === "modelLimit" || entry.key === "modelFallback")) return;
  if (entry.key === "modelLimit" || entry.key === "modelFallback") run.skipModel = true;
  run.active = eventPhases[entry.key] || run.active;
  run.entry = entry;
  const panel = document.querySelector(".operation[data-kind='" + run.kind + "']");
  if (panel) paintOperation(panel, run);
  return panel;
}

function typeTerminal(target, content, run, excerpt = false) {
  // Reserve the wrapped line height while only the typed prefix is painted.
  target.dataset.measure = content;
  const line = element("span", "", "terminal-line");
  target.replaceChildren(line);
  if (run.paused || reducedMotion.matches || document.hidden || !content) {
    line.textContent = content;
    return;
  }
  const chars = Array.from(content);
  const text = document.createTextNode("");
  const caret = element("span", "", "type-caret");
  line.append(text, caret);
  const start = performance.now() + (excerpt ? 100 : 45);
  const duration = excerpt ? Math.min(1600, 23 * chars.length) : Math.min(325, 16 * chars.length);
  let written = 0;
  function type(now) {
    if (!line.isConnected) return;
    const count = Math.max(0, Math.floor((now - start) * chars.length / duration));
    if (run.paused || reducedMotion.matches || document.hidden || count >= chars.length) {
      line.textContent = content;
      return;
    }
    if (count > written) text.appendData(chars.slice(written, count).join(""));
    written = count;
    requestAnimationFrame(type);
  }
  requestAnimationFrame(type);
}

function paintExcerpt(panel, run, now) {
  const verified = run.evidence?.length && ["report", "model", "verify", "finalize"].includes(run.entry.key);
  const rows = verified ? run.evidence : run.excerpts;
  const box = panel.querySelector(".scan-window");
  box.hidden = !rows?.length;
  if (box.hidden) return;
  const mode = verified ? "evidence" : "source";
  if (mode !== run.excerptMode) {
    run.excerptMode = mode;
    run.excerptIndex = 0;
    run.nextExcerpt = now + 3300;
  } else if (!run.paused && !reducedMotion.matches && now >= run.nextExcerpt && !box.matches(":focus-within")) {
    run.excerptIndex = (run.excerptIndex + 1) % rows.length;
    run.nextExcerpt = now + 3300;
    box.removeAttribute("data-excerpt");
  }
  const ref = rows[run.excerptIndex];
  const key = [mode, run.excerptIndex, ref.line, state.lang].join("-");
  if (box.dataset.excerpt === key) return;
  box.dataset.excerpt = key;
  box.querySelector(".trace-kind").textContent = verified ? copy().ruleEvidence : copy().sourceExcerpt;
  const reference = box.querySelector(".trace-reference");
  reference.textContent = ref.label && ref.label !== "L" + ref.line
    ? ref.label + " · " + copy().line + " " + number(ref.line) : copy().line + " " + number(ref.line);
  reference.dataset.line = ref.line;
  reference.title = copy().showSource + " · " + copy().line + " " + number(ref.line);
  const body = box.querySelector("blockquote");
  const quote = ref.label && ref.quote.startsWith(ref.label) ? ref.quote.slice(ref.label.length).replace(/^[\s|]+/, "") : ref.quote;
  body.querySelector(".sr-only").textContent = quote;
  typeTerminal(body.querySelector(".trace-copy"), quote, run, true);
}

function paintOperation(panel, run) {
  const t = copy();
  const message = panel.querySelector(".operation-message");
  const command = activityText(run.entry);
  message.querySelector(".sr-only").textContent = command;
  typeTerminal(message.querySelector(".typed-command"), command, run);
  panel.querySelector(".operation-symbol use").setAttribute("href", "#icon-" + phaseIcons[run.active]);
  panel.dataset.phase = run.active;
  const index = run.phases.indexOf(run.active);
  for (const [i, row] of [...panel.querySelectorAll(".operation-steps li")].entries()) {
    const key = run.phases[i];
    const status = run.skipModel && key === "meaning" ? "skipped" : i < index ? "done" : i === index ? "current" : "pending";
    row.dataset.status = status;
    if (status === "current") row.setAttribute("aria-current", "step");
    else row.removeAttribute("aria-current");
    row.title = status === "skipped" ? t.phaseSkipped : t.phases[key];
    row.textContent = row.title;
  }
  if (run.kind === "evaluation" && run.completed !== undefined) {
    panel.querySelector(".operation-source").textContent = t.testCount(number(run.completed), number(run.total));
  }
  const measured = panel.querySelector(".operation-measured");
  measured.hidden = !run.localSummary || !["meaning", "verify", "finish"].includes(run.active);
  if (!measured.hidden) measured.textContent = t.rulesMeasured(number(run.localSummary.sections), number(run.localSummary.findings));
  if (run.kind === "review") paintExcerpt(panel, run, performance.now());
}

function operationPanel(run) {
  const t = copy();
  const panel = element("section", "", "operation " + run.kind + "-loading");
  panel.dataset.kind = run.kind;
  const head = element("div", "", "operation-head");
  const icon = controlIcon(phaseIcons[run.active]);
  icon.classList.add("operation-symbol");
  const title = element("div");
  title.append(element("h3", run.kind === "evaluation" ? t.evalLoading : t.checking),
    element("span", run.kind === "evaluation" ? t.suiteTitle : state.file || t.inputLabel, "operation-source"));
  const clock = element("time", "0:00", "operation-clock");
  clock.dataset.started = run.started;
  clock.setAttribute("aria-hidden", "true");
  const controls = element("div", "", "terminal-controls");
  const motion = element("button", "", "motion-toggle");
  motion.type = "button";
  function showMotionState() {
    panel.classList.toggle("motion-paused", Boolean(run.paused));
    motion.title = run.paused ? t.resumeMotion : t.pauseMotion;
    motion.setAttribute("aria-label", motion.title);
    motion.replaceChildren(controlIcon(run.paused ? "play" : "pause"));
  }
  motion.addEventListener("click", () => {
    run.paused = !run.paused;
    run.nextExcerpt = performance.now() + 3300;
    showMotionState();
  });
  showMotionState();
  controls.append(clock, motion);
  head.append(icon, title, controls);
  const display = element("div", "", "operation-display");
  const lamp = element("span", "", "operation-lamp");
  lamp.setAttribute("aria-hidden", "true");
  const message = element("p", "", "operation-message");
  if (run.kind === "evaluation") message.setAttribute("role", "status");
  const typed = element("span", "", "typed-command");
  typed.setAttribute("aria-hidden", "true");
  message.append(element("span", "", "sr-only"), typed);
  display.append(lamp, message);
  const measured = element("p", "", "operation-measured");
  const list = element("ol", "", "operation-steps");
  for (const key of run.phases) {
    const li = element("li");
    list.append(li);
  }
  panel.append(head, display);
  if (run.kind === "review") {
    const scanWindow = element("div", "", "scan-window");
    scanWindow.setAttribute("aria-live", "off");
    const caption = element("div", "", "trace-caption");
    const reference = element("button", "", "trace-reference");
    reference.type = "button";
    reference.addEventListener("click", () => locateDocumentLine(Number(reference.dataset.line)));
    caption.append(element("span", "", "trace-kind"), reference);
    const quote = element("blockquote");
    const visual = element("span", "", "trace-copy");
    visual.setAttribute("aria-hidden", "true");
    quote.append(element("span", "", "sr-only"), visual);
    scanWindow.append(caption, quote);
    panel.append(scanWindow);
  }
  panel.append(list, measured);
  paintOperation(panel, run);
  if (!clockTimer) clockTimer = setInterval(tickClocks, 250);
  return panel;
}

function summary(entries) {
  const holder = element("div", "", "summary");
  for (const [label, value] of entries) {
    const cell = element("div");
    cell.append(element("strong", value), element("span", label));
    holder.append(cell);
  }
  return holder;
}

function sourceSelection(ref) {
  locateDocumentLine(ref.line);
}

function sources(item, compact = false) {
  const { amounts, currency } = item.values;
  const compareAmounts = item.code === "limit_conflict" && Array.isArray(amounts) && amounts.length === item.evidence.length;
  const group = element("div", "", compareAmounts ? "source-group amount-comparison" : "source-group");
  const money = compareAmounts ? amountFormat(amounts, currency) : null;

  for (const [index, ref] of item.evidence.entries()) {
    const source = element("button", "", "source-quote");
    source.type = "button";
    const label = ref.label === ref.id ? copy().line + " " + ref.line : ref.label;
    let quote = ref.quote.startsWith(label) ? ref.quote.slice(label.length).trimStart() : ref.quote;
    if (tableRow(ref.quote)) {
      const cells = tableCells(ref.quote);
      if (cells[0] === label) cells.shift();
      quote = cells.filter(Boolean).join(" · ");
    }
    const title = element("span", "", "source-title");
    title.append(element("strong", label, "source-ref"));
    if (money) title.append(element("strong", money.format(amounts[index]), "source-amount"));
    source.append(title);
    if (!compact || !money) source.append(element("span", quote, "source-copy"));
    const excerpt = ref.quote.startsWith(label) ? ref.quote : label + " " + ref.quote;
    source.setAttribute("aria-label", copy().showSource + ". " + excerpt);
    source.title = copy().showSource;
    source.addEventListener("click", () => {
      state.sourceFinding = item.id;
      select("back-to-finding").hidden = false;
      sourceSelection(ref);
    });
    group.append(source);
  }
  return group;
}

function amountFormat(amounts, currency) {
  return new Intl.NumberFormat(state.lang, {
    style: "currency", currency, currencyDisplay: "narrowSymbol",
    minimumFractionDigits: amounts.some((value) => value.includes(".")) ? 2 : 0, maximumFractionDigits: 2,
  });
}

function controlIcon(icon) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "control-icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(svg.namespaceURI, "use");
  use.setAttribute("href", "#icon-" + icon);
  svg.append(use);
  return svg;
}

function actionButton(label, icon, appearance = "secondary") {
  const button = element("button", "", "button button-compact " + appearance);
  button.type = "button";
  button.append(controlIcon(icon), element("span", label));
  return button;
}

function rememberRevision() {
  if (state.report && !state.revision) state.revision = state.report;
}

function saveRevision() {
  state.undo.push({ text: spec.value, edited: new Set(state.editedLines), report: state.report, decisions: state.clarifications.length });
  rememberRevision();
}

function confirmedChange(item, wording) {
  return { question: authorQuestion(item), source_lines: item.evidence.map(ref => ref.line), wording };
}

function applyStructuralRevision(text, clarification) {
  if (Array.from(text).length > state.config.max_chars || state.busy || state.audit?.edits.size) return false;
  saveRevision();
  if (clarification) state.clarifications.push(clarification);
  spec.value = text;
  state.report = null;
  state.comparison = null;
  state.reviewError = "";
  state.sourceFinding = "";
  state.documentView = "preview";
  renderEditor();
  renderReport();
  return true;
}

function applyDraft(changes, id) {
  const t = copy();
  const lines = spec.value.split("\n");
  const checked = state.reviewedText.split("\n");
  if (changes.some(({ line }) => lines[line - 1] !== checked[line - 1])) return t.repair.editStale;
  for (const { line, text } of changes) lines[line - 1] = text;
  const updated = lines.join("\n");
  if (Array.from(updated).length > state.config.max_chars) return t.errors.text_too_long;
  if (updated === spec.value) return t.repair.editUnchanged;

  saveRevision();
  const item = state.report?.findings.find(entry => entry.id === id);
  if (item) state.clarifications.push(confirmedChange(item, changes.map(change => change.text).join("\n")));
  spec.value = updated;
  for (const { line } of changes) state.editedLines.add(line);
  state.notice = "";
  renderEditor();
  renderReport({ openId: id });
  const summary = [...resultBox.querySelectorAll(".finding")].find((node) => node.dataset.id === id)?.querySelector("summary");
  if (summary) {
    summary.focus({ preventScroll: true });
    revealInside(resultBox, summary);
  }
  return "";
}

function limitChanges(item, amount, confirmedText) {
  const edits = item.values.limit_edits;
  const selected = edits.find((edit) => edit.amount === amount);
  const replacement = selected?.text ?? confirmedText;
  if (!replacement) return [];
  const checked = state.reviewedText.split("\n");
  return edits.filter((edit) => edit.amount !== amount).map((edit) => {
    const original = checked[edit.line - 1];
    const indent = original.length - original.trimStart().length;
    const prefix = Array.from(edit.quote).slice(0, edit.start).join("");
    const suffix = Array.from(edit.quote).slice(edit.end).join("");
    return { line: edit.line, text: original.slice(0, indent) + prefix + replacement + suffix +
      original.slice(indent + edit.quote.length) };
  });
}

function referenceLabel(ref) {
  return ref.label === ref.id ? copy().line + " " + ref.line : ref.label;
}

function authorQuestion(item) {
  const t = copy();
  if (item.code === "limit_conflict" && t.limitQuestion[item.values.period]) return t.limitQuestion[item.values.period];
  if (item.question) return item.question;
  if (item.code === "retry_behavior") return t.retryId + " " + t.retryOutcome;
  if (timingTerms(item).length) return t.timingQuestion;
  return t.rules[item.code][2];
}

function timingTerms(item) {
  return (item.values.terms || []).filter((term) =>
    /^(quickly|fast|soon|as soon as possible|within a reasonable time|быстро|оперативно|мгновенно|как можно скорее)$/i.test(term));
}

function authorPrompt(item, question) {
  const t = copy();
  const r = t.repair;
  const box = element("div", "", "author-prompt");
  const row = element("div", "", "repair-question");
  const copyQuestion = actionButton(r.copy, "copy", "text-button");
  copyQuestion.title = r.copy;
  const status = element("span", "", "repair-status");
  status.setAttribute("role", "status");
  copyQuestion.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(question + "\n" + item.evidence.map(referenceLabel).join(", "));
      status.textContent = r.copied;
    } catch { status.textContent = r.copyFailed; }
  });
  const questionText = element("div");
  const prompt = element("p", question);
  questionText.append(element("strong", r.question), prompt);
  row.append(questionText, copyQuestion);
  box.append(row, status);
  return box;
}

function timeLimit(value, russian) {
  const match = value.match(/^(\d+(?:[.,]\d+)?)\s*(\p{L}+)$/u);
  if (!match || Number(match[1].replace(",", ".")) <= 0) return "";
  const units = [
    [/^(ms|milliseconds?|мс|миллисекунд[ауы]?)$/i, "millisecond", "миллисекунды", "миллисекунд"],
    [/^(s|sec|seconds?|с|сек|секунд[ауы]?)$/i, "second", "секунды", "секунд"],
    [/^(min|minutes?|мин|минут[ауы]?)$/i, "minute", "минуты", "минут"],
    [/^(h|hr|hours?|ч|час(?:а|ов)?)$/i, "hour", "часа", "часов"],
  ];
  const unit = units.find(([pattern]) => pattern.test(match[2]));
  if (!unit) return "";
  const valueText = match[1].replace(russian ? "." : ",", russian ? "," : ".");
  const one = Number(match[1].replace(",", ".")) === 1;
  return valueText + " " + (russian ? unit[one ? 2 : 3] : unit[1] + (one ? "" : "s"));
}

function guidedAnswer(item, draft, source, cell) {
  const t = copy();
  const russian = /[а-яё]/i.test(source);
  const prefix = !cell && (source.match(/^\s*(?:(?:§\s*)?\d+(?:\.\d+)*\.?|[A-Z]+-\d+)\s+/u)?.[0] || "");
  if (draft.manual || item.code === "semantic_conflict" || needsFullTimingClause(item, source)) {
    const value = (draft.free || "").trim().replace(/\s+/g, " ");
    if (!value || /^(yes|no|да|нет|ok|ок|approved|согласовано)[.!\s]*$/iu.test(value)) throw Error(correctionCopy().insufficient);
    return prefix && !value.startsWith(prefix.trim()) ? prefix + value : value;
  }
  if (["broken_reference", "duplicate_clause", "open_decision"].includes(item.code)) {
    const ref = item.evidence.find(entry => entry.line === draft.line);
    const token = item.values.targets?.[0] || item.values.markers?.[0] || ref.label;
    const value = (draft.replacement || "").trim();
    if (!value || (item.code === "duplicate_clause" && !/^(?:§\s*\d+(?:\.\d+)*|\d+(?:\.\d+)+|[A-Z]{1,5}-\d+)$/.test(value))) throw Error(t.replacement[item.code]);
    const i = source.indexOf(token);
    if (i < 0) throw Error(t.repair.editStale);
    return source.slice(0,i) + value + source.slice(i + token.length);
  }
  const value = (draft.first || "").trim().replace(/[.!?]+$/, "");
  const event = (draft.second || "").trim().replace(/[.!?]+$/, "");
  const terms = timingTerms(item);
  if (!value || !event) throw Error(terms.length ? t.needDetails : item.code === "retry_behavior" ? t.needRetry : t.needDecision);
  let clause = source.trimEnd().replace(/[.!?]+$/, "");
  if (item.code === "retry_behavior") {
    clause += russian ? ". При повторе используется " + value + ". " + event : ". The retry uses " + value + ". " + event;
  } else if (terms.length) {
    const duration = timeLimit(value, russian);
    if (!duration) throw Error(t.needDetails);
    for (const term of terms) clause = clause.replace(new RegExp("(?<![\\p{L}])" + term + "(?![\\p{L}])", "giu"), "");
    clause = clause.replace(/[ \t]+/g, " ").trimEnd() + (russian ? " в течение " + duration + " после " : " within " + duration + " after ") + event;
  } else {
    clause = (prefix || "") + (russian ? "Если " : "When ") + value + ", " + event;
  }
  return clause + ".";
}

function needsFullTimingClause(item, source) {
  const clause = source.replace(/^\s*(?:§\s*)?\d+(?:\.\d+)*\.?\s+/, "");
  return timingTerms(item).length > 0 && /[.!?]\s+\p{L}/u.test(clause);
}

function correctionCopy() {
  return state.lang === "ru" ? {
    all: "Все замечания", start: "Разобрать замечания", find: "Поиск и фильтры", next: "Следующее замечание", steps: ["Проблема", "Ответ", "Правка"], stepLabel: "Шаги исправления",
    answer: "Ответить на вопрос", back: "Назад", preview: "Посмотреть правку", apply: "Применить правку",
    assist: "Предложить с ИИ", thinking: "Агент готовит формулировку…", aiError: "Агент недоступен. Можно проверить свою формулировку или попробовать ещё раз.",
    manual: "Ответить своими словами", guided: "Ответить по шагам", free: "Ваш ответ", freeHint: "Укажите, при каком условии и что именно должно произойти.",
    before: "Сейчас в ТЗ", after: "Новая формулировка", appendix: "Новый абзац после строки", cell: "Ячейка для исправления", column: "Столбец",
    custom: "Другая сумма", amount: "Согласованная сумма", invalidAmount: "Введите положительную сумму, до двух знаков после запятой.",
    insufficient: "Уточните действие или условие: одного «да» или «нет» недостаточно для нового требования.",
    image: "Сохраните ссылки на рисунки при редактировании.", details: "Рекомендация и приёмочный тест",
    amendment: "Проверить свою формулировку", unavailable: "Проверьте документ повторно, чтобы получить актуальные замечания.",
    aiDraft: "Предложение ИИ", moreDetail: "Агенту не хватает данных. Дополните ответ согласованным условием, значением или действием.",
    keepId: "Сохраните номер исходного пункта в начале формулировки."
  } : {
    all: "All findings", start: "Review findings step by step", find: "Search and filters", next: "Next finding", steps: ["Issue", "Answer", "Revision"], stepLabel: "Correction steps",
    answer: "Answer the question", back: "Back", preview: "Preview revision", apply: "Apply revision",
    assist: "Draft with AI", thinking: "The agent is drafting the wording…", aiError: "The agent is unavailable. You can preview your own wording or try again.",
    manual: "Answer in my own words", guided: "Use guided answer", free: "Your answer", freeHint: "Describe the condition and what should happen.",
    before: "Current specification", after: "Proposed wording", appendix: "New paragraph after line", cell: "Cell to correct", column: "Column",
    custom: "Another amount", amount: "Agreed amount", invalidAmount: "Enter a positive amount with up to two decimal places.",
    insufficient: "Include an action or condition. A yes or no alone cannot define the requirement.",
    image: "Keep the image references when editing.", details: "Recommendation and acceptance test",
    amendment: "Preview my wording", unavailable: "Recheck the document to get the latest findings.",
    aiDraft: "AI suggestion", moreDetail: "The agent needs more detail. Add the agreed condition, value or action to your answer.",
    keepId: "Keep the original clause number at the start of the wording."
  };
}

// Keep the untouched cells, whitespace and delimiters exactly as supplied.
function editableCells(line) {
  if (!tableRow(line)) return [];
  const delimiter = pipeRow(line) ? /(?<!\\)\|/g : /\t/g;
  const bounds = [-1, ...Array.from(line.matchAll(delimiter), (match) => match.index), line.length];
  return bounds.slice(1).flatMap((end, index) => {
    const start = bounds[index] + 1;
    const raw = line.slice(start, end);
    if (!raw.trim() && (index === 0 || end === line.length)) return [];
    const text = raw.trim();
    const offset = start + raw.length - raw.trimStart().length;
    return [{ from: offset, to: offset + text.length, text }];
  });
}

function additionSite(item, lines) {
  let after = Math.max(...item.evidence.map(ref => ref.line));
  const anchor = lines[after - 1] || "";
  const heading = anchor.match(/^\s*(#{1,6})\s+/);
  if (heading) {
    while (after < lines.length) {
      const next = lines[after].match(/^\s*(#{1,6})\s+/);
      if (next && next[1].length <= heading[1].length) break;
      after++;
    }
  } else if (tableRow(anchor)) {
    while (after < lines.length && tableRow(lines[after])) after++;
  }
  return after;
}

function repairForm(item, draft, go) {
  const t = copy(), c = correctionCopy();
  const form = element("form", "", "repair-panel wizard-form");
  const fields = element("div", "", "repair-fields");
  const status = element("p", "", "repair-status");
  status.setAttribute("role", "status");
  const lines = state.reviewedText.split("\n");
  const isHeading = ref => /^\s*#{1,6}\s/.test(lines[ref.line - 1]);
  const addition = ["missing_scenario", "acceptance_gap"].includes(item.code)
    || item.evidence.every(isHeading);
  const refs = item.evidence.filter(ref => !state.editedLines.has(ref.line)
    && (addition || !isHeading(ref)));
  if (!refs.length) { form.append(element("p", c.unavailable)); return form; }
  if (!refs.some(ref => ref.line === draft.line)) draft.line = refs[0].line;
  const ref = refs.find(entry => entry.line === draft.line);
  const raw = lines[ref.line - 1] || "";
  const amount = Boolean(item.values.limit_edits?.length && !draft.manual && !addition);
  const cells = !amount && !addition ? editableCells(raw) : [];
  if (cells.length && !cells[draft.column]) {
    const signals = [...(item.values.terms || []), ...(item.values.targets || []), ...(item.values.markers || [])];
    if (item.code === "duplicate_clause") signals.push(ref.label);
    const match = cells.findIndex(cell => signals.some(term => cell.text.includes(term)));
    draft.column = match < 0 ? cells.reduce((best, cell, i) => cell.text.length > cells[best].text.length ? i : best, 0) : match;
  }
  const cell = cells[draft.column];
  const source = cell ? cell.text.replace(/\\\|/g, "|") : raw;
  function field(label, control) {
    const wrapper = element("label", label);
    wrapper.append(control);
    fields.append(wrapper);
    return wrapper;
  }
  function input(key, label, multiline = false) {
    const control = element(multiline ? "textarea" : "input");
    if (multiline) control.rows = 3;
    control.maxLength = multiline ? 1500 : 800;
    control.value = draft[key] || "";
    control.required = true;
    control.addEventListener("input", () => { draft[key] = control.value; status.textContent = ""; });
    field(label, control);
    return control;
  }
  if (!addition && !amount && refs.length > 1) {
    const select = element("select", "", "repair-clause-picker");
    for (const entry of refs) select.add(new Option(referenceLabel(entry), String(entry.line)));
    select.value = String(ref.line);
    select.onchange = () => { draft.line = Number(select.value); draft.column = null; draft.free = ""; draft.followUp = ""; go(2, ".repair-clause-picker"); };
    field(t.repair.clause, select);
  }
  if (cells.length) {
    const select = element("select", "", "repair-cell-picker");
    cells.forEach((v,i) => select.add(new Option(c.column + " " + (i + 1) + " · " + v.text.slice(0,45), String(i))));
    select.value = String(draft.column);
    select.onchange = () => { draft.column = Number(select.value); draft.free = ""; draft.followUp = ""; go(2, ".repair-cell-picker"); };
    field(c.cell, select);
  }
  const requiresWording = addition || item.code === "semantic_conflict" || needsFullTimingClause(item, source);
  const free = !amount && (requiresWording || draft.manual);
  let followUp;
  if (amount) {
    const format = amountFormat(item.values.amounts, item.values.currency);
    const select = element("select");
    select.required = true;
    select.add(new Option(t.repair.chooseLimit, ""));
    item.values.amounts.forEach(value => select.add(new Option(format.format(value), value)));
    select.add(new Option(c.custom, "custom"));
    select.value = draft.amount || "";
    field(t.repair.confirmedLimit, select);
    const custom = input("customAmount", c.amount + " (" + item.values.currency + ")");
    custom.inputMode = "decimal";
    const sync = () => { custom.required = select.value === "custom"; custom.parentElement.hidden = !custom.required; };
    select.onchange = () => { draft.amount = select.value; sync(); };
    sync();
  } else if (free) {
    const answer = input("free", c.free, true);
    answer.placeholder = c.freeHint;
    followUp = element("p", draft.followUp || "", "agent-follow-up");
    followUp.id = "follow-up-" + item.id;
    followUp.setAttribute("role", "status");
    answer.setAttribute("aria-describedby", followUp.id);
    fields.prepend(followUp);
  } else if (["broken_reference", "duplicate_clause", "open_decision"].includes(item.code)) {
    input("replacement", t.replacement[item.code]);
  } else {
    const time = timingTerms(item).length > 0;
    const retry = item.code === "retry_behavior";
    input("first", time ? t.duration : retry ? t.retryId : t.condition);
    input("second", time ? t.trigger : retry ? t.retryOutcome : t.behavior);
  }
  const actions = element("div", "", "wizard-actions");
  const canDraft = free && state.config.gemini && !state.auditDemo;
  const prepare = actionButton(canDraft ? c.amendment : c.preview, "edit", canDraft ? "secondary" : "primary");
  prepare.type = "submit";
  prepare.dataset.action = "preview";
  function plan(wording, assisted = false) {
    if (addition) {
      const after = additionSite(item, lines);
      draft.plan = { kind: "addition", line: after, wording, assisted };
    } else {
      const prefix = !cell && raw.match(/^\s*(?:(?:§\s*)?\d+(?:\.\d+)*\.?|[A-Z]+-\d+)\s+/u)?.[0];
      if (assisted && prefix && !wording.startsWith(prefix.trim())) wording = prefix + wording;
      draft.plan = { kind:"replace", line:ref.line, before:source, raw, cell, wording, assisted };
    }
    go(3);
  }
  form.addEventListener("submit", event => {
    event.preventDefault();
    try {
      if (amount) {
        const value = (draft.customAmount || "").trim().replace(/[\s\u00a0\u202f]/g, "").replace(",", ".");
        const custom = draft.amount === "custom";
        if (custom && (!/^\d{1,12}(?:\.\d{1,2})?$/.test(value) || Number(value) <= 0)) throw Error(c.invalidAmount);
        const edits = custom ? limitChanges(item,value,value) : limitChanges(item,draft.amount);
        if (!edits.length) throw Error(t.repair.editUnchanged);
        draft.plan = { kind:"amount", edits };
        go(3);
      } else if (addition) {
        const wording = draft.free.trim().replace(/\s+/g, " ");
        if (/^(yes|no|да|нет|ok|ок|approved|согласовано)[.!\s]*$/iu.test(wording)) throw Error(c.insufficient);
        plan(wording);
      } else plan(guidedAnswer(item,draft,source,Boolean(cell)));
    } catch (err) { status.textContent = err.message; }
  });
  if (canDraft) {
    const assist = actionButton(c.assist, "model", "primary");
    assist.dataset.action = "assist";
    assist.addEventListener("click", async () => {
      if (!form.reportValidity() || assist.disabled) return;
      const answer = draft.free.trim();
      assist.disabled = true;
      assist.setAttribute("aria-busy", "true");
      status.textContent = c.thinking;
      try {
        const result = await request("/api/correction/propose", { method:"POST", headers:{"Content-Type":"application/json"},
          body: JSON.stringify({ text: state.reviewedText, locale:state.lang, code:item.code, line:ref.line, quote:ref.quote,
            question:authorQuestion(item), answer, ...(cell ? {target:cell.text} : {}) }) });
        if (!form.isConnected || draft.free.trim() !== answer || !form.closest(".finding")?.open) return;
        if (typeof result.wording !== "string" || !result.wording.trim()) throw Error();
        plan(result.wording.trim(), true);
      } catch (error) {
        if (form.isConnected && draft.free.trim() === answer) {
          if (error.message === "clarification_needed") {
            draft.followUp = error.question || c.moreDetail;
            followUp.textContent = draft.followUp;
            status.textContent = "";
            fields.querySelector("textarea")?.focus({ preventScroll: true });
          } else status.textContent = c.aiError;
        }
      } finally {
        assist.disabled = false;
        assist.removeAttribute("aria-busy");
        if (status.textContent === c.thinking) status.textContent = "";
      }
    });
    actions.append(assist);
  }
  actions.append(prepare);
  if (!requiresWording) {
    const toggle = actionButton(draft.manual ? c.guided : c.manual, "edit", "text-button");
    toggle.onclick = () => { draft.manual = !draft.manual; go(2); };
    actions.append(toggle);
  }
  form.append(fields, actions, status);
  return form;
}

function card(item) {
  const t = copy();
  const title = t.rules[item.code][0];
  const detail = element("details", "", "finding");
  detail.dataset.id = item.id;
  const heading = element("summary");
  const identity = element("span", "", "finding-identity");
  const context = element("small", [...new Set(item.evidence.map(referenceLabel))].join(" · "));
  if (item.evidence.some((ref) => state.editedLines.has(ref.line))) context.append(element("em", t.editedClause));
  identity.append(element("strong", title), context);
  heading.append(identity, element("span", t[item.severity], "severity " + item.severity));
  detail.append(heading);
  return detail;
}

function findingBody(item) {
  const t = copy(), c = correctionCopy();
  const body = element("div", "", "finding-body correction-wizard");
  const draft = state.answers.get(item.id) || { line:item.evidence[0].line, step:1 };
  state.answers.set(item.id,draft);
  const progress = element("ol", "", "wizard-steps");
  progress.setAttribute("aria-label", c.stepLabel);
  const content = element("section", "", "wizard-stage");
  content.tabIndex = -1;
  body.append(progress, content);
  const [, description, , acceptance] = t.rules[item.code];
  const lines = state.reviewedText.split("\n");
  const edited = item.evidence.some(ref => state.editedLines.has(ref.line))
    || item.values.limit_edits?.some(edit => state.editedLines.has(edit.line));
  if (edited) {
    body.replaceChildren(element("strong", t.repair.edited, "edited-note"));
    return body;
  }
  function go(step, focus = true) {
    draft.step = step;
    body.dataset.stage = String(step);
    progress.replaceChildren(...c.steps.map((name, i) => {
      const li = element("li", (i+1) + " " + name);
      if (i + 1 === step) li.setAttribute("aria-current", "step");
      if (i + 1 < step) li.className = "completed";
      return li;
    }));
    content.setAttribute("aria-label", c.steps[step - 1]);
    content.replaceChildren();
    if (step === 1) {
      content.append(element("p", item.explanation || description, "issue-description"), sources(item));
      const help = element("details", "", "wizard-advice");
      const recommendation = item.recommendation || t.repair.hints[item.code];
      help.append(element("summary", c.details));
      if (recommendation) help.append(element("p", recommendation));
      if (item.acceptance_test || acceptance) help.append(element("strong", t.acceptance), element("p", item.acceptance_test || acceptance));
      if (recommendation || acceptance || item.acceptance_test) content.append(help);
      const start = actionButton(c.answer,"question","primary");
      start.dataset.action = "answer";
      start.onclick = () => go(2);
      content.append(start);
    } else {
      const back = element("button", "← " + c.back, "button button-compact text-button");
      back.type = "button";
      back.dataset.action = "back";
      back.onclick = () => go(step - 1);
      content.append(back);
      if (step === 2) {
        content.append(authorPrompt(item,authorQuestion(item)), repairForm(item,draft,go));
      } else {
        const plan = draft.plan;
        const form = element("form", "", "wizard-preview");
        const status = element("p", "", "repair-status");
        status.setAttribute("role","status");
        let wording;
        if (plan.kind === "amount") {
          const diff = element("div", "", "wizard-diff");
          for (const edit of plan.edits) {
            const block = element("div");
            const original = lines[edit.line - 1];
            const before = editableCells(original);
            const after = editableCells(edit.text);
            const column = before.findIndex((cell, i) => after[i] && cell.text !== after[i].text);
            const evidence = item.evidence.find(entry => entry.line === edit.line);
            const label = evidence ? referenceLabel(evidence) : t.line + " " + number(edit.line);
            block.append(element("strong", column < 0 ? label : label + " · " + c.column + " " + (column + 1)),
              element("small", c.before), element("del",column < 0 ? original : before[column].text),
              element("small",c.after), element("ins",column < 0 ? edit.text : after[column].text));
            diff.append(block);
          }
          form.append(diff);
        } else {
          if (plan.kind === "replace") form.append(element("small",c.before), element("blockquote",plan.before));
          else form.append(element("p",c.appendix + " " + number(plan.line)));
          const label = element("label",plan.assisted ? c.aiDraft : c.after);
          wording = element("textarea","","wizard-wording");
          wording.rows = 3;
          wording.required = true;
          wording.value = plan.wording;
          wording.addEventListener("input",() => { plan.wording = wording.value; status.textContent = ""; });
          label.append(wording);
          form.append(label);
        }
        const confirm = actionButton(c.apply,"check","primary");
        confirm.type = "submit";
        confirm.dataset.action = "apply";
        form.append(confirm,status);
        form.addEventListener("submit",event => {
          event.preventDefault();
          if (plan.kind === "amount") {
            status.textContent = applyDraft(plan.edits,item.id);
            return;
          }
          const text = wording.value.trim().replace(/\s+/g," ");
          if (!text || /\{\{[^}]*\}\}/.test(text)) { status.textContent = text ? t.repair.finishTemplate : t.repair.editEmpty; return; }
          if (plan.kind === "addition") {
            const current = spec.value.split("\n");
            if (current.length !== lines.length || item.evidence.some(ref => current[ref.line-1] !== lines[ref.line-1])) {
              status.textContent = t.repair.editStale;
              return;
            }
            current.splice(plan.line,0,"",text,"");
            if (!applyStructuralRevision(current.join("\n"),confirmedChange(item,text))) status.textContent = t.errors.text_too_long;
            else select("results-heading").focus({preventScroll:true});
          } else {
            const prefix = !plan.cell && item.code !== "duplicate_clause" &&
              plan.before.match(/^\s*((?:§\s*)?\d+(?:\.\d+)*\.?|[A-Z]+-\d+)\s+/u)?.[1];
            if (prefix && !text.startsWith(prefix + " ")) { status.textContent = c.keepId; return; }
            const markers = s => s.match(/!\[[^\]]*\]\(attachment:fig-\d+\)/g) || [];
            if (JSON.stringify(markers(plan.before)) !== JSON.stringify(markers(text))) { status.textContent = c.image; return; }
            const cellText = pipeRow(plan.raw) ? text.replace(/\|/g,"\\|") : text.replace(/\t/g," ");
            const updated = plan.cell ? plan.raw.slice(0,plan.cell.from) + cellText + plan.raw.slice(plan.cell.to) : text;
            status.textContent = applyDraft([{line:plan.line,text:updated}],item.id);
          }
        });
        content.append(form);
      }
    }
    if (focus) {
      const target = typeof focus === "string" ? content.querySelector(focus) : content;
      (target || content).focus({preventScroll:true});
      revealInside(resultBox, progress);
    }
  }
  go(draft.step === 3 && draft.plan ? 3 : draft.step === 2 ? 2 : 1, false);
  return body;
}

function compareReports(previous, current) {
  const describe = (item) => ({ code: item.code, references: item.evidence.map(({ label, id, line, quote }) =>
    ({ section: label === id ? null : label, line, quote })) });
  const key = (item) => JSON.stringify([item.code, item.references.map((ref) =>
    ref.section ? ["section", ref.section] : ["quote", ref.quote]).sort()]);
  const remaining = previous.findings.map(describe);
  const still = [], added = [];
  for (const item of current.findings.map(describe)) {
    const id = key(item);
    const index = remaining.findIndex((old) => key(old) === id);
    if (index < 0) added.push(item);
    else {
      remaining.splice(index, 1);
      still.push(item);
    }
  }
  return { before: previous.findings.length, after: current.findings.length,
    changedEngine: previous.engine !== current.engine, gone: remaining, still, added };
}

function comparisonFinding(item) {
  const t = copy();
  const refs = item.references.map(ref => ref.section || t.line + " " + number(ref.line));
  return t.rules[item.code][0] + " · " + refs.join(", ");
}

function comparisonList(comparison) {
  const t = copy();
  const group = element("details", "", "comparison-list");
  group.append(element("summary", t.changeList));
  for (const kind of ["gone", "still", "added"]) {
    const entries = comparison[kind];
    if (!entries.length) continue;
    const section = element("div", "", "comparison-group");
    section.append(element("strong", t[kind] + " · " + number(entries.length)));
    const list = element("ul");
    for (const item of entries) list.append(element("li", comparisonFinding(item)));
    section.append(list);
    group.append(section);
  }
  group.append(element("p", t.compareHint, "coverage"));
  return group;
}

function downloadQuestions() {
  const t = copy();
  const parts = state.report.findings.map((item) => [
    t.rules[item.code][0], ...item.evidence.map((ref) => referenceLabel(ref) + " — " + ref.quote),
    authorQuestion(item), t.adviceTitle + " — " + (item.recommendation || t.repair.hints[item.code]),
  ].join("\n"));
  downloadFile(t.questionsTitle + "\n\n" + parts.join("\n\n") + "\n", "text/plain;charset=utf-8", "sana1-author-questions.txt");
}

function renderAuditState() {
  const t = copy();
  const status = state.hackathonStatus;
  const failed = status === "hackathonFailed" || Object.hasOwn(t.auditErrors, status);
  const stopped = status === "auditStopped";
  const changed = !state.audit && state.auditBaseline && state.auditBaseline.text !== spec.value;
  const kind = state.hackathonBusy ? "running" : failed ? "failed" : stopped ? "stopped" : changed ? "changed"
    : state.audit && state.auditStages.length ? "complete" : "";
  const message = kind === "changed" ? t.auditChangeNotice : t.auditErrors[status] || t[status] || "";
  const announcement = select("audit-announcement");
  const spoken = kind === "running" ? auditEventText(state.auditStages.at(-1)) || message : message;
  if (announcement.textContent !== spoken) announcement.textContent = spoken;
  const panel = select("audit-state");
  panel.hidden = !kind;
  if (!kind) return false;
  panel.dataset.kind = kind;
  panel.classList.toggle("has-report", Boolean(state.audit) && !state.hackathonBusy);
  select("audit-state-title").textContent = {
    running: t.auditWorking, failed: t.auditFailedTitle, stopped: t.auditStopped, changed: t.auditChangedTitle, complete: "",
  }[kind];
  select("hackathon-status").textContent = stopped ? t.auditCanRetry : message;
  select("hackathon-status").hidden = kind === "running" || kind === "complete";
  const consoleLog = select("audit-console");
  const log = select("audit-log");
  log.hidden = !state.auditStages.length || kind === "changed";
  if (kind === "running") log.open = true;
  if (log.dataset.state === "running" && kind !== "running") log.open = false;
  log.dataset.state = kind;
  select("audit-elapsed").hidden = kind !== "running";
  if (!log.hidden) {
    consoleLog.replaceChildren(...state.auditStages.map((event, index) => {
      const done = kind === "complete" || index < state.auditStages.length - 1;
      const elapsed = [Math.floor(event.seconds / 60), event.seconds % 60].map(value => String(value).padStart(2, "0")).join(":");
      return element("li", `[${elapsed}] ${done ? "✓" : "›"} ${auditEventText(event)}`, done ? "is-done" : "");
    }));
    renderAuditElapsed();
  }
  select("audit-state-stop").hidden = !state.hackathonBusy;
  select("audit-state-retry").hidden = state.hackathonBusy || kind === "complete";
  select("audit-state-retry").disabled = select("hackathon-report").disabled;
  return true;
}

function auditEventText(event) {
  if (!event) return "";
  const text = copy().auditStages[event.stage];
  return typeof text === "function" ? text(event, number) : text;
}

function renderAuditElapsed() {
  select("audit-elapsed").textContent = copy().auditElapsed(number(Math.floor((Date.now() - state.auditStarted) / 1000)));
}

function focusAuditResults() {
  const heading = select("results-heading");
  if (isSplitWorkspace()) {
    select("findings-pane").scrollTop = 0;
    heading.scrollIntoView({ block: "nearest" });
  } else window.scrollTo(0, 0);
  heading.focus({ preventScroll: true });
}

function renderReport({ reveal = false, openId = "" } = {}) {
  const t = copy();
  const result = state.report;
  // Reuse the export control, including its in-flight and error handling.
  const word = select("download-word");
  if (word.parentNode !== select("download-options")) select("download-options").prepend(word);
  word.textContent = t.downloadWord;
  select("pending-revision")?.remove();
  resultBox.replaceChildren();
  const hasAuditState = renderAuditState();
  const hasAudit = Boolean(state.audit) && !state.hackathonBusy;
  const fallback = select("audit-fallback");
  fallback.hidden = !hasAudit || !state.audit.review.ai_unavailable;
  fallback.textContent = fallback.hidden ? "" : t.auditFallback;
  select("revision-undo").hidden = state.hackathonBusy || !state.auditUndo || state.auditUndo.after !== spec.value;
  const hasReview = Boolean(state.busy || result || state.revision || state.reviewError);
  const showResults = hasAudit || hasAuditState || hasReview;
  const workspace = select("review-page");
  workspace.dataset.hasResults = String(showResults);
  select("workspace-bar").hidden = select("findings-pane").hidden = !showResults;
  setWorkspacePane(showResults ? workspace.dataset.pane : "document");
  renderRepairQueue(hasAudit ? state.audit : null);
  select("audit-results").hidden = !hasAudit;
  if (hasAudit || hasAuditState) {
    resultBox.hidden = true;
    select("download-toggle").hidden = select("export-error").hidden = select("result-count").hidden = true;
    select("back-to-finding").hidden = true;
    setDownloadsOpen(false);
    select("results-heading").textContent = t.auditHeading;
    select("jump-count").textContent = hasAudit ? number(state.audit.review.findings.length) : "";
    return;
  }
  resultBox.hidden = !hasReview;
  select("results-heading").textContent = t.resultTitle;
  select("jump-count").textContent = result ? number(result.findings.length) : "";
  select("back-to-finding").hidden = !state.sourceFinding || !result;
  resultBox.classList.toggle("results-arriving", reveal && Boolean(result));
  resultBox.setAttribute("aria-busy", String(state.busy));
  select("export-error").hidden = true;
  select("download-toggle").hidden = state.busy || (!result && !state.revision);
  if (select("download-toggle").hidden) setDownloadsOpen(false);
  select("export").hidden = !result || Boolean(state.revision);
  select("download-questions").hidden = !result?.findings.length || Boolean(state.revision);
  select("download-text").hidden = select("download-formatted").hidden = !state.comparison || Boolean(state.revision);
  select("result-count").hidden = !result;
  if (state.busy) {
    resultBox.append(operationPanel(state.reviewRun));
    return;
  }
  if (!result) {
    if (hasReview) {
      const panel = element("div", "", "revision-banner");
      const body = element("div");
      body.append(element("strong", state.reviewError ? t.reviewError : t.repair.draftTitle),
        element("p", state.reviewError ? t.errors[state.reviewError] : t.repair.draftEmpty));
      panel.append(body);
      const retry = actionButton(state.revision ? t.repair.recheck : t.run, "scan", "primary");
      retry.disabled = select("hackathon-report").disabled;
      retry.addEventListener("click", () => review());
      panel.append(retry);
      if (state.undo.length) panel.append(undoButton());
      resultBox.append(panel);
      if (state.revision) profileGuide.renderReport(resultBox);
    }
    return;
  }
  if (state.reviewError) addNotice(resultBox, state.reviewError);
  if (state.revision) {
    const banner = element("div", "", "revision-banner");
    banner.id = "pending-revision";
    const body = element("div");
    body.setAttribute("role", "status");
    body.append(element("strong", t.repair.draftTitle), element("p", t.repair.draftBody(number(state.editedLines.size))));
    const recheck = actionButton(t.repair.recheck, "scan", "primary");
    recheck.addEventListener("click", () => review());
    banner.append(body, recheck);
    if (state.undo.length) banner.append(undoButton());
    resultBox.after(banner);
  }
  if (state.comparison && !state.revision) {
    const c = state.comparison;
    const banner = element("div", "", "revision-banner final-review");
    const body = element("div");
    const title = element("h3", t.repair.finalTitle);
    title.tabIndex = -1;
    body.append(title, element("p", t.repair.finalBody(number(c.before), number(c.after))));
    if (c.gone.length) {
      const resolved = element("p", "", "resolved-finding");
      resolved.append(controlIcon("check"), element("span", t.gone + " · " + comparisonFinding(c.gone[0])));
      body.append(resolved);
    }
    if (c.changedEngine) body.append(element("p", t.repair.engineChanged));
    word.textContent = t.saveRevisedWord;
    banner.append(body, word);
    if (c.still.length || c.added.length || c.gone.length > 1) banner.append(comparisonList(c));
    if (c.clarifications?.length) {
      const history = element("details", "", "comparison-list");
      history.append(element("summary", t.appliedClarifications + " · " + number(c.clarifications.length)));
      for (const decision of c.clarifications) {
        const row = element("div", "", "comparison-group");
        row.append(element("strong", decision.question), element("p", decision.wording));
        history.append(row);
      }
      banner.append(history);
    }
    resultBox.append(banner);
    if (reveal && document.activeElement === document.body && banner.getClientRects().length) {
      title.focus({ preventScroll: true });
    }
  }
  select("result-count").textContent = number(result.findings.length);
  for (const warning of result.warnings || []) addNotice(resultBox, warning);
  profileGuide.renderReport(resultBox);
  if (!result.findings.length) {
    if (!state.comparison) resultBox.append(statePanel("clean", t.clean, t.cleanBody));
    resultBox.append(reportDetails(result));
    return;
  }
  renderFindings(result.findings, openId);
  if (!state.revision) resultBox.append(reportDetails(result));
}

function undoButton() {
  const undo = actionButton(copy().undoEdit, "edit", "text-button");
  undo.addEventListener("click", () => {
    const previous = state.undo.pop();
    if (!previous) return;
    state.clarifications.length = previous.decisions;
    spec.value = previous.text;
    state.reviewError = "";
    state.editedLines = previous.edited;
    if ("report" in previous) state.report = previous.report;
    if (spec.value === state.reviewedText) {
      state.report = state.revision || state.report;
      state.revision = null;
    }
    renderEditor();
    renderReport();
  });
  return undo;
}

let selectedFinding;
function renderFindings(findings, openId) {
  const t = copy();
  const c = correctionCopy();
  const available = categories.filter((key) => key === "all" || findings.some((item) => item.category === key));
  const toolbar = element("div", "", "finding-tools");
  const search = element("input");
  search.type = "search";
  search.placeholder = t.findText;
  search.setAttribute("aria-label", t.findText);
  search.value = state.query;
  const count = element("output");
  const field = element("div", "", "finding-search");
  field.append(search, count);
  const filters = element("div", "", "filters");
  for (const category of available) {
    const button = element("button", t[category], "filter");
    button.type = "button";
    button.dataset.category = category;
    button.addEventListener("click", () => {
      state.filter = category;
      update();
    });
    filters.append(button);
  }
  const start = actionButton(c.start, "edit", "primary");
  if (findings.length > 1) {
    const options = element("details", "", "finding-search-options");
    options.open = Boolean(state.query) || state.filter !== "all";
    options.append(element("summary", c.find), field);
    if (available.length > 2) options.append(filters);
    toolbar.append(start, options);
  }
  const list = element("div", "", "findings-list");
  const normalize = (s) => s.normalize("NFKC").toLocaleLowerCase(state.lang).replace(/\s+/g, " ").trim();
  const rows = findings.map((item) => {
    const node = card(item);
    list.append(node);
    const text = normalize([t.rules[item.code][0], t[item.category], t[item.severity], item.explanation,
      authorQuestion(item), ...item.evidence.flatMap((ref) => [referenceLabel(ref), ref.quote])].join(" "));
    return { node, item, id: item.id, category: item.category, text };
  });
  const caseNav = element("div", "", "finding-navigation");
  start.addEventListener("click", () => {
    const first = rows.find(row => !row.node.hidden && !row.item.evidence.some(ref => state.editedLines.has(ref.line)));
    if (first) choose(first.id);
  });
  const back = actionButton(c.all, "findings", "back-to-findings");
  const position = element("span", "", "finding-position");
  const next = element("button", c.next + " →", "button button-compact next-finding");
  next.type = "button";
  next.addEventListener("click", () => { if (next.dataset.id) choose(next.dataset.id); });
  caseNav.append(back, position, next);
  let current = openId || (selectedFinding?.report === state.report ? selectedFinding.id : findings.length === 1 ? findings[0].id : "");
  function choose(id, focus = true) {
    current = id;
    selectedFinding = { id, report: state.report };
    update();
    if (focus && id) {
      rows.find((row) => row.id === id)?.node.querySelector("summary").focus({ preventScroll: true });
      revealInside(resultBox, caseNav);
    }
  }
  for (const row of rows) row.node.querySelector("summary").addEventListener("click", (event) => {
    event.preventDefault();
    if (current !== row.id) choose(row.id);
    else back.click();
  });
  back.addEventListener("click", () => {
    const previous = rows.find((row) => row.id === current);
    choose("", false);
    const summary = previous?.node.querySelector("summary");
    if (summary && !previous.node.hidden) {
      summary.focus({ preventScroll: true });
      revealInside(resultBox, summary);
    }
  });
  const empty = element("div", "", "search-empty");
  const reset = actionButton(t.resetFilters, "clear", "text-button");
  empty.append(element("strong", t.noMatches), reset);
  function update() {
    const terms = normalize(state.query).split(" ").filter(Boolean);
    let shown = 0;
    toolbar.hidden = Boolean(current);
    caseNav.hidden = !current;
    list.toggleAttribute("data-detail", Boolean(current));
    const matches = (row) => (state.filter === "all" || state.filter === row.category) && terms.every((term) => row.text.includes(term));
    if (current) {
      const filtered = rows.filter(matches);
      const index = filtered.findIndex((row) => current === row.id);
      position.textContent = index >= 0 ? t.shown(number(index + 1), number(filtered.length)) : "";
      next.hidden = index < 0 || index + 1 >= filtered.length;
      next.dataset.id = filtered[index + 1]?.id || "";
    }
    for (const row of rows) {
      if (row.id === current && row.node.childElementCount === 1) row.node.append(findingBody(row.item));
      row.node.open = row.id === current;
      row.node.hidden = current ? row.id !== current : !matches(row);
      if (!row.node.hidden) shown++;
    }
    for (const button of filters.children) button.setAttribute("aria-pressed", String(button.dataset.category === state.filter));
    start.disabled = !rows.some(row => !row.node.hidden && !row.item.evidence.some(ref => state.editedLines.has(ref.line)));
    count.textContent = t.shown(number(shown), number(findings.length));
    empty.hidden = shown > 0;
  }
  search.addEventListener("input", () => { state.query = search.value; update(); });
  reset.addEventListener("click", () => {
    search.value = state.query = "";
    state.filter = "all";
    update();
    search.focus();
  });
  update();
  resultBox.append(toolbar, caseNav, list, empty);
}

function reportDetails(result) {
  const t = copy();
  const details = element("details", "", "report-details");
  details.append(element("summary", t.reportDetails));
  const metrics = [t.sections + " · " + number(result.statistics.sections)];
  for (const [key, label] of [["high", t.highPriority], ["medium", t.mediumPriority]]) {
    const count = result.findings.filter((item) => item.severity === key).length;
    if (count) metrics.push(label + " · " + number(count));
  }
  details.append(element("p", metrics.join("   /   ")));
  if (result.verification) {
    const {verified_quotes, excluded_findings} = result.verification;
    details.append(element("p", t.verifiedReceipt(number(verified_quotes), excluded_findings && number(excluded_findings))));
  }
  details.append(element("p", result.engine === "gemini" ? t.combinedCoverage : t.localCoverage));
  return details;
}

function setDownloadsOpen(open) {
  select("download-options").hidden = !open;
  select("download-toggle").setAttribute("aria-expanded", String(open));
}

function cancelReview() {
  state.reviewAttempt++;
  state.controller?.abort();
  state.controller = null;
  state.busy = false;
  state.report = null;
  state.reviewError = "";
  state.reviewRun = null;
  state.filter = "all";
  state.query = "";
  state.sourceFinding = "";
}

function cancelAudit(status = "") {
  const controller = state.auditController;
  state.auditController = null;
  state.hackathonBusy = false;
  state.hackathonStatus = status;
  controller?.abort();
}

function replaceDocument(text, fileName = "", media = [], pdf = null, view = "preview") {
  select("workflow-message").textContent = "";
  if (!state.auditDemo) setRecoveryEnabled(false);
  state.reportSource = null;
  state.auditBaseline = null;
  state.auditHandoff = null;
  state.auditUndo = null;
  state.auditStages = [];
  state.auditDecisions.clear();
  clearAudit();
  cancelAudit();
  cancelReview();
  setWorkspacePane("document");
  previewSource = null;
  select("document-preview").replaceChildren();
  select("document-preview").scrollTop = 0;
  document.querySelector(".editor-panel .panel-body").scrollTop = 0;
  if (state.pdfUrl) URL.revokeObjectURL(state.pdfUrl);
  state.pdfReader?.controller?.abort();
  state.pdfReader = null;
  select("document-format-notice").hidden = true;
  state.pdfUrl = pdf ? URL.createObjectURL(pdf.slice(0, pdf.size, "application/pdf")) : "";
  state.media = media;
  state.undo = [];
  state.clarifications = [];
  state.documentView = text ? view : "source";
  state.revision = null;
  state.comparison = null;
  state.editedLines.clear();
  state.answers.clear();
  // A new textarea keeps native undo within this document.
  const editor = spec.cloneNode();
  spec.replaceWith(editor);
  spec = editor;
  bindSourceEditorEvents(editor);
  spec.value = text;
  spec.setSelectionRange(0, 0);
  spec.scrollTop = 0;
  state.file = fileName;
  renderEditor();
  renderReport();
}

function startEditorDraft(text, caret = 0) {
  state.loadAttempt++;
  state.loading = null;
  state.notice = "";
  clearActivity();
  replaceDocument(text, "", [], null, "source");
  spec.setSelectionRange(caret, caret);
  spec.focus({ preventScroll: true });
}

async function review() {
  if (select("hackathon-report").disabled) return;
  clearAudit();
  state.auditBaseline = null;
  state.hackathonStatus = "";
  setDocumentView("preview");
  const revision = state.revision;
  const priorReport = state.report;
  cancelReview();
  state.comparison = null;
  const id = state.reviewAttempt;
  const controller = new AbortController();
  state.controller = controller;
  state.busy = true;
  if (!["partial_pdf", "preview_partial"].includes(state.notice)) state.notice = "";
  const payload = {
    text: spec.value, locale: state.lang,
    mode: state.config.gemini === false || state.auditDemo ? "local" : "gemini",
  };
  state.reviewRun = makeOperation("review", payload.mode === "gemini" ? ["read", "links", "rules", "meaning", "verify", "finish"] : ["read", "links", "rules", "verify", "finish"],
    revision ? "rechecking" : "requested");
  const sourceLines = payload.text.split("\n");
  state.reviewRun.excerpts = sourceLines.map((text, i) => ({ line: i + 1, quote: text.trim().slice(0, 160) }))
    .filter(({quote}) => quote && !quote.startsWith("#") && !quote.includes("](attachment:") && !/^[|:\s-]+$/.test(quote)).slice(0, 12);
  addActivity(revision ? "rechecking" : "requested", { reset: reviewActivity.latest()?.key !== "fileReady" });
  renderEditor();
  renderReport();
  resultBox.scrollTop = 0;
  setWorkspacePane("findings");
  if (location.pathname === "/workspace") focusAuditResults();
  try {
    const options = { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload), signal: controller.signal };
    const onStage = (event) => {
      if (id === state.reviewAttempt && reviewSteps.has(event.step)) {
        if (event.step === "report" && Array.isArray(event.evidence)) {
          state.reviewRun.evidence = event.evidence.filter((ref) => typeof ref?.quote === "string" && ref.quote.length
            && Number.isInteger(ref.line) && sourceLines[ref.line - 1]?.includes(ref.quote)).slice(0, 8);
        }
        if (event.step === "model" && Number.isInteger(event.sections) && Number.isInteger(event.findings)) {
          state.reviewRun.localSummary = { sections: event.sections, findings: event.findings };
        }
        addActivity(event.step, { args: event.step === "compare" ? [event.count] : [] });
      }
    };
    const url = payload.mode === "gemini" ? "/api/analyze/gemini" : "/api/analyze";
    let report;
    try { report = await requestEvents(url, options, onStage); }
    catch (error) {
      if (id !== state.reviewAttempt) return;
      const limited = error.message === "rate_limited";
      const interrupted = error.message === "network" || error.message === "stream_interrupted";
      if (payload.mode !== "gemini" || !(limited || error.status >= 500 || interrupted)) throw error;
      addActivity(limited ? "modelLimit" : "modelFallback");
      report = await requestEvents("/api/analyze", { ...options, body: JSON.stringify({ ...payload, mode: "local" }) }, onStage);
      report.warnings = [limited ? "rate_limited" : "gemini_unavailable", ...report.warnings];
    }
    if (id !== state.reviewAttempt) return;
    if (!Array.isArray(report?.findings) || !Number.isInteger(report.statistics?.sections)) throw new Error("generic");
    state.reviewRun.skipModel = payload.mode === "gemini" && report.engine !== "gemini";
    addActivity("finalize");
    await addActivity("reviewReady", { status: "complete", args: [report.findings.length, report.statistics.sections] });
    if (id === state.reviewAttempt) {
      state.report = report;
      state.reviewedText = payload.text;
      if (revision) state.comparison = { ...compareReports(revision, report), clarifications: state.clarifications };
      state.clarifications = [];
      state.revision = null;
      state.editedLines.clear();
      state.undo = [];
      state.answers.clear();
    }
  } catch (error) {
    if (id === state.reviewAttempt && error.name !== "AbortError") {
      await addActivity("reviewFailed", { status: "error" });
      if (id === state.reviewAttempt) {
        state.reviewError = copy().errors[error.message] ? error.message : "generic";
        if (revision) state.report = priorReport;
      }
    }
  } finally {
    if (id === state.reviewAttempt) {
      state.controller = null;
      state.busy = false;
      renderEditor();
      renderReport({ reveal: true });
    }
  }
}

async function upload(file) {
  if (!file) return;
  setWorkspacePane("document");
  const attempt = ++state.loadAttempt;
  const extension = file.name.includes(".") ? file.name.split(".").pop().toLowerCase() : "";
  state.loading = null;
  state.notice = "";
  if (!allowedFiles.has(extension) || file.size > state.config.max_upload || !file.size) {
    state.notice = !allowedFiles.has(extension) ? "unsupported_file" : !file.size ? "empty_file" : "file_too_large";
    if (!state.busy) addActivity("fileFailed", { reset: true, status: "error" });
    renderEditor();
    return;
  }
  state.loading = "file";
  if (state.busy) {
    cancelReview();
    renderReport();
  }
  addActivity("fileRead", { reset: true });
  renderEditor();
  try {
    const parsed = await request(extension === "pdf" ? "/api/extract?view=pdf" : "/api/extract", {
      method: "POST", headers: { "Content-Type": "application/octet-stream",
        "X-File-Type": extension === "markdown" ? "md" : extension },
      body: file,
    });
    if (attempt !== state.loadAttempt) return;
    await addActivity("fileReady", { status: "complete", args: [Array.from(parsed.text).length] });
    if (attempt !== state.loadAttempt) return;
    state.notice = parsed.warnings[0] || "";
    replaceDocument(parsed.text, file.name, parsed.media || [], extension === "pdf" ? file : null);
    state.reportSource = { text: spec.value, file, pdfCoverage: parsed.pdf_coverage };
    if (parsed.pdf_coverage?.total) {
      state.pdfReader = { file, total: parsed.pdf_coverage.total, page: 1, error: false,
        pages: new Map(parsed.media.map(({ page, src }) => [page, src])) };
      setDocumentView("pdf");
      if (!state.pdfReader.pages.has(1)) showPdfPage(1);
    }
    if (location.pathname === "/workspace") select(state.pdfReader ? "show-pdf" : "show-document").focus({ preventScroll: true });
  } catch (error) {
    if (attempt === state.loadAttempt) {
      state.notice = error.message || "generic";
      await addActivity("fileFailed", { status: "error" });
    }
  } finally {
    if (attempt === state.loadAttempt) {
      state.loading = null;
      renderEditor();
      renderReport();
    }
  }
}

function clearAudit() {
  if (!state.audit) return;
  state.audit.cancelTranslation?.();
  state.audit = null;
  state.hackathonStatus = "";
  select("audit-results").replaceChildren();
}

function auditDecisionKey(run, item) {
  return JSON.stringify([run.review.sha256, run.review.mode, item.id, item.question,
    item.evidence.map(({ line, end }) => [line, end])]);
}

function renderAuditHandoff() {
  const handoff = state.auditHandoff;
  const t = copy();
  const baseline = state.auditBaseline || handoff?.run;
  const changed = Boolean(baseline && baseline.text !== spec.value);
  select("hackathon-report-label").textContent = changed ? t.auditRunAgain : t.hackathonReport;
  select("audit-handoff").hidden = !handoff;
  if (!handoff) return;
  const { run, item, sourceStatus, setCheck } = handoff;
  const finding = Boolean(item.question);
  const decision = finding && state.auditDecisions.get(auditDecisionKey(run, item));
  const title = setCheck ? item.criterion : finding ? item.id + " · " + t.auditDecision : item.source_id || item.id;
  select("audit-handoff-title").textContent = title;
  select("audit-handoff-question").textContent = setCheck ? item.comment : finding ? item.question : item.summary;
  const answer = select("audit-handoff-answer");
  answer.textContent = decision?.answer || "";
  answer.hidden = !decision;
  const back = select("audit-handoff-return");
  back.hidden = state.audit !== run;
  back.textContent = setCheck ? t.returnSetCheck : finding ? t.auditReturn : t.auditReturnRequirement;
  const status = select("audit-handoff-status");
  const rechecked = state.audit && state.audit.text === spec.value;
  status.textContent = changed ? (rechecked ? "" : t.auditSourceChanged) : (t[sourceStatus] || "");
  status.hidden = !status.textContent;
}

function renderRepairQueue(run) {
  const queue = select("repair-queue");
  const edits = run?.edits;
  queue.hidden = !edits?.size;
  if (queue.hidden) return;
  const changeCount = [...edits.values()].reduce((count, { changes }) => count + changes.length, 0);
  select("repair-queue-title").textContent = copy().pendingRevisions(number(changeCount));
  select("repair-queue-status").textContent = "";
  select("repair-queue-list").replaceChildren(...[...edits].map(([id, { item, changes }]) => {
    const row = element("li");
    const label = element("span", id + " · " + changes.map(({ patch }) => patch.after.trim()).join(" · "));
    label.title = label.textContent;
    const edit = element("button", copy().editPassage, "button button-compact secondary");
    edit.type = "button";
    edit.setAttribute("aria-label", copy().editPassage + " " + id);
    edit.onclick = () => openAuditRepair(run, item);
    const remove = element("button", copy().removeRevision, "button button-compact text-button");
    remove.type = "button";
    remove.setAttribute("aria-label", copy().removeRevision + " " + id);
    remove.onclick = () => {
      edits.delete(id);
      run.markQueued(id, false);
      renderEditor();
      renderRepairQueue(run);
      if (edits.size) select("apply-audit-queue").focus();
      else run.revealFinding(id);
    };
    row.append(label, edit, remove);
    return row;
  }));
}

function writeRevision(text) {
  spec.value = text;
  spec.dispatchEvent(new Event("input"));
  setDocumentView("preview");
}

function editDocumentLine(line) {
  if (state.audit?.edits.size) {
    setWorkspacePane("findings");
    select("apply-audit-queue").focus();
    return;
  }
  const original = spec.value;
  const quote = original.split("\n")[line - 1]?.trim();
  if (!quote) return;
  showRevision(select("revision-dialog"), {
    documentText: original, sources: [{ line, end: line, quote, location: "L" + line }],
    language: state.lang,
    submit(patch) {
      if (spec.value !== original) throw Error("stale");
      writeRevision(applyRevisionPatches(original, [patch], state.config.max_chars));
      locateDocumentLine(line);
    },
  });
}

function openAuditRepair(run, item) {
  showRevision(select("revision-dialog"), {
    documentText: run.text, item, sources: item.evidence, language: state.lang,
    existing: run.edits.get(item.id),
    suggest: state.config.gemini === true ? async (part, answer) => {
      const line = run.text.slice(0, part.start).split("\n").length;
      const result = await request("/api/correction/propose", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: run.text, locale: "ru", code: "semantic_conflict", line,
          quote: part.source.quote, target: part.before, question: item.question, answer }),
      });
      return result.wording;
    } : null,
    submit(changes) {
      if (state.audit !== run || spec.value !== run.text) throw Error("stale");
      const otherPatches = [...run.edits].filter(([id]) => id !== item.id)
        .flatMap(([, edit]) => edit.changes.map(({ patch }) => patch));
      applyRevisionPatches(run.text, [...otherPatches, ...changes.map(({ patch }) => patch)], state.config.max_chars);
      run.edits.set(item.id, { changes, item });
      run.markQueued(item.id, true);
      renderEditor();
      renderRepairQueue(run);
    },
  });
}

function applyAuditQueue() {
  const run = state.audit;
  if (!run?.edits.size || spec.value !== run.text) return;
  let updated;
  try {
    const patches = [...run.edits.values()].flatMap(({ changes }) => changes.map(({ patch }) => patch));
    updated = applyRevisionPatches(run.text, patches, state.config.max_chars);
  } catch {
    select("repair-queue-status").textContent = copy().applyRevisionError;
    return;
  }
  for (const { item, changes } of run.edits.values()) {
    const revisions = changes.map(({ patch, answer, location }) => ({ before: patch.before, after: patch.after, answer, location }));
    const answer = [...new Set(revisions.map(item => item.answer))].join("\n");
    state.auditDecisions.set(auditDecisionKey(run, item), {
      finding_id: item.id, source_sha256: run.review.sha256, source_mode: run.review.mode,
      question: item.question, answer, requirements: item.requirements, evidence: item.evidence,
      revision: { before: revisions[0].before, after: revisions[0].after }, revisions,
    });
    state.auditHandoff = { run, item };
  }
  run.edits.clear();
  state.auditUndo = { before: run.text, after: updated, sha: run.review.sha256 };
  writeRevision(updated);
  runAudit();
}

function openAuditEvidence(run, item, source, setCheck = false) {
  const selection = evidenceSelection(spec.value, source);
  state.auditHandoff = { run, item, setCheck, sourceStatus: selection ? "auditSourceSelected" : "auditSourceUnmatched" };
  renderAuditHandoff();
  if (selection && locateDocumentLine(spec.value.slice(0, selection[0]).split("\n").length)) return;
  setWorkspacePane("document");
  setDocumentView("source");
  spec.focus();
  spec.setSelectionRange(...(selection || [0, 0]));
  if (selection) {
    const [first] = selection;
    const style = getComputedStyle(spec);
    const meter = element("div", "", "audit-text-meter");
    meter.style.width = spec.clientWidth + "px";
    meter.style.font = style.font;
    meter.style.padding = style.padding;
    meter.style.letterSpacing = style.letterSpacing;
    meter.style.tabSize = style.tabSize;
    const marker = element("span", spec.value.slice(first, first + 1));
    meter.append(spec.value.slice(0, first), marker, spec.value.slice(first + 1));
    spec.parentElement.append(meter);
    spec.scrollTop = Math.max(0, marker.offsetTop - spec.clientHeight / 3);
    meter.remove();
  }
}

function mountAudit(run, before, focusedBefore) {
  const { review: audit, markdown, comparison, confirmed, modeChanged } = run;
  state.audit?.cancelTranslation?.();
  const appliedEdits = new Map([...state.auditDecisions.values()]
    .filter(entry => entry.source_sha256 === before?.sha256 && entry.source_mode === before.mode)
    .map(entry => [entry.finding_id, entry.revisions || [entry.revision]]));
  const methods = renderAudit(select("audit-results"), audit, {
    demo: state.auditDemo,
    language: state.lang,
    renderStructure: panel => profileGuide.renderReport(panel),
    openLinkSource: line => locateDocumentLine(line),
    initialPanel: run.panel,
    reportLanguage: {
      markdown, saved: run.savedLanguage, restored: run.restored,
      official: audit.sha256 === "e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381",
      translate: (language, signal) => request("/api/analyze/gemini?operation=translate-report", {
        method: "POST", headers: { "Content-Type": "application/json" }, signal,
        body: JSON.stringify({ review: audit, language }),
      }),
      download(result) {
        const filename = audit.mode === "rules" ? "sana1-rules-review" : "sana1-requirements-review";
        const suffix = result.language === "ru" ? "" : "-" + result.language.replace(/[^\p{L}\p{N}-]+/gu, "-").slice(0, 60);
        downloadFile(result.markdown, "text/markdown;charset=utf-8", filename + suffix + ".md");
      },
    },
    comparison,
    modeChanged,
    focusedBefore,
    confirmedBefore: confirmed,
    appliedEdits,
    onPanelChange() {
      if (state.audit === run) {
        renderAuditProgress();
        scheduleRecovery();
      }
    },
    async exportDocument(format) {
      if (format === "md") {
        downloadFile(run.text, "text/markdown;charset=utf-8", "SanA1-specification.md");
        return;
      }
      try { await downloadWord(run.text, state.media, state.lang); }
      catch (error) { throw new Error(copy().errors[error.message] || copy().errors.generic); }
    },
    download(format, questions) {
      const filename = audit.mode === "rules" ? "sana1-rules-review" : "sana1-requirements-review";
      if (format === "questions") {
        downloadFile(questions, "text/plain;charset=utf-8", "sana1-author-questions.txt");
      } else if (format === "md") {
        downloadFile(markdown, "text/markdown;charset=utf-8", filename + ".md");
      } else {
        const decisions = [...state.auditDecisions.values()];
        const data = { ...audit };
        if (decisions.length) data.author_decisions = decisions;
        if (comparison) data.revision_comparison = { ...comparison, confirmed_before_ids: [...confirmed] };
        downloadFile(JSON.stringify(data, null, 2) + "\n", "application/json", filename + ".json");
      }
    },
    openRepair: item => openAuditRepair(run, item),
    openEvidence: (item, source, setCheck) => openAuditEvidence(run, item, source, setCheck),
  });
  Object.assign(run, methods);
  for (const id of run.edits.keys()) run.markQueued(id, true);
  state.audit = run;
}

function renderRecovery() {
  select("session-recovery").hidden = state.auditDemo || (!recoveryEnabled && !spec.value.trim());
  select("session-enabled").checked = recoveryEnabled;
  select("session-pdf-note").hidden = !recoveryEnabled || !/\.pdf$/iu.test(state.file);
  const status = select("session-status");
  status.hidden = !recoveryStatus;
  const message = recoveryStatus ? copy()[recoveryStatus] : "";
  if (status.textContent !== message) status.textContent = message;
}

function setRecoveryEnabled(enabled) {
  recoveryEnabled = enabled;
  recoveryStatus = "";
  if (enabled) {
    saveRecovery();
  } else {
    clearTimeout(recoveryTimer);
    clearWorkspaceSession(tabStorage());
    renderRecovery();
  }
}

function saveRecovery() {
  clearTimeout(recoveryTimer);
  if (!recoveryEnabled || state.auditDemo) return;
  const current = state.audit;
  const baseline = state.auditBaseline;
  const pdfOrigin = state.reportSource?.text && state.reportSource.pdfCoverage?.unread.length
    ? state.reportSource.pdfCoverage : undefined;
  recoveryStatus = writeWorkspaceSession(tabStorage(), {
    text: spec.value, file: state.file, pdfOrigin,
    media: state.media.filter(image => image.id), view: state.documentView,
    pane: select("review-page").dataset.pane, layout: select("review-page").dataset.layout,
    baseline: baseline && { text: baseline.text, review: baseline.review, recheckToken: baseline.recheckToken },
    audit: current && { review: current.review, markdown: current.markdown, recheckToken: current.recheckToken, compare: Boolean(current.comparison),
      modeChanged: current.modeChanged, panel: current.currentPanel(), reportLanguage: current.languageSnapshot(), confirmed: [...current.confirmed],
      edits: [...current.edits].map(([id, { changes }]) => [id, changes]) },
    decisions: [...state.auditDecisions], undo: state.auditUndo,
  });
  if (recoveryStatus === "sessionUnavailable") recoveryEnabled = false;
  renderRecovery();
}

function scheduleRecovery() {
  if (!recoveryEnabled || state.auditDemo) return;
  clearTimeout(recoveryTimer);
  recoveryTimer = setTimeout(saveRecovery, 180);
}

function restoredMedia(value) {
  if (!Array.isArray(value)) return [];
  return value.filter(item => /^fig-\d+$/u.test(item?.id) &&
    /^data:image\/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/u.test(item.src)).slice(0, 8);
}

function restoredEdits(entries, review, text) {
  const edits = new Map();
  if (!Array.isArray(entries)) return edits;
  for (const [id, changes] of entries) {
    const item = review.findings.find(finding => finding.id === id);
    if (!item || !Array.isArray(changes) || !changes.length) continue;
    const valid = changes.every(({ patch, answer, wording, location }) =>
      typeof answer === "string" && typeof wording === "string" && typeof location === "string" &&
      Number.isInteger(patch?.start) && Number.isInteger(patch.end) && patch.start >= 0 &&
      patch.end >= patch.start && patch.end <= text.length &&
      typeof patch.before === "string" && typeof patch.after === "string");
    if (valid) edits.set(id, { item, changes });
  }
  applyRevisionPatches(text, [...edits.values()].flatMap(({ changes }) => changes.map(({ patch }) => patch)), state.config.max_chars);
  return edits;
}

function restoreRecovery() {
  const storage = tabStorage();
  const saved = readWorkspaceSession(storage);
  if (!saved) {
    clearWorkspaceSession(storage);
    return;
  }
  recoveryEnabled = true;
  recoveryStatus = saved.text ? "sessionRestored" : "sessionSaved";
  spec.value = saved.text;
  state.file = saved.text && typeof saved.file === "string" ? saved.file : "";
  state.media = restoredMedia(saved.media);
  state.documentView = saved.text && saved.view !== "source" ? "preview" : "source";
  if (Array.isArray(saved.pdfOrigin?.unread) && saved.pdfOrigin.unread.length && Number.isInteger(saved.pdfOrigin.total) &&
      saved.pdfOrigin.unread.length < saved.pdfOrigin.total && saved.pdfOrigin.total <= 40 &&
      saved.pdfOrigin.unread.every(page => Number.isInteger(page) && page > 0 && page <= saved.pdfOrigin.total) &&
      new Set(saved.pdfOrigin.unread).size === saved.pdfOrigin.unread.length) {
    state.reportSource = { text: saved.text, pdfCoverage: saved.pdfOrigin };
  }
  select("review-page").dataset.layout = saved.layout === "focus" ? "focus" : "split";
  setWorkspacePane(saved.pane === "findings" ? "findings" : "document");
  try {
    if (typeof saved.baseline?.text === "string" && recoverableAudit(saved.baseline.review)) state.auditBaseline = saved.baseline;
    if (typeof saved.undo?.before === "string" && typeof saved.undo.sha === "string" && saved.undo.after === saved.text) {
      state.auditUndo = saved.undo;
    }
    if (Array.isArray(saved.decisions)) {
      state.auditDecisions = new Map(saved.decisions.filter(entry => Array.isArray(entry) &&
        typeof entry[0] === "string" && typeof entry[1]?.source_sha256 === "string"));
    }
    const audit = saved.audit;
    if (!saved.text || !recoverableAudit(audit?.review) || typeof audit.markdown !== "string") return;
    const { review, markdown } = audit;
    const before = state.auditBaseline?.review;
    const comparison = audit.compare && before?.mode === review.mode ? compareAudits(before, review) : null;
    const confirmed = new Set(comparison?.needs_review.filter(item => audit.confirmed?.includes(item.id)).map(item => item.id));
    const edits = restoredEdits(audit.edits, review, saved.text);
    mountAudit({ review, markdown, recheckToken: audit.recheckToken, comparison, confirmed, edits, panel: audit.panel,
      modeChanged: Boolean(audit.modeChanged), text: saved.text, savedLanguage: audit.reportLanguage, restored: true }, before);
    state.hackathonStatus = review.mode === "rules" ? "rulesAuditReady" : "hackathonReady";
  } catch {
    state.audit = state.auditBaseline = null;
    state.auditDecisions.clear();
    recoveryStatus = "sessionDraftOnly";
  }
}

async function runAudit() {
  if (select("hackathon-report").disabled) return;
  select("workflow-message").textContent = "";
  const text = spec.value;
  const loadAttempt = state.loadAttempt;
  const source = state.reportSource;
  const original = source?.text === text ? source.file : null;
  const filename = original?.name || (state.file ? state.file.replace(/\.[^.]+$/u, "") + ".md" : "requirements.md");
  const pdfOrigin = !original && source?.text && source.pdfCoverage?.unread.length ? source.pdfCoverage : null;
  const imageIds = new Set([...text.matchAll(/!\[[^\]]+\]\(attachment:(fig-\d+)\)/g)].map(match => match[1]));
  const figures = !original ? state.media.filter(item => imageIds.has(item.id)).slice(0, 4) : [];
  const recheckToken = !original && state.auditBaseline?.text !== text ? state.auditBaseline?.recheckToken : null;
  const structured = pdfOrigin || figures.length || recheckToken;
  const body = structured ? JSON.stringify({ text, filename, pdf_origin: pdfOrigin, figures, recheck_token: recheckToken })
    : original || new Blob([text], { type: "application/octet-stream" });
  const headers = { "Content-Type": structured ? "application/json" : "application/octet-stream" };
  if (!structured) headers["X-File-Name"] = encodeURIComponent(filename);
  const controller = new AbortController();
  state.auditController = controller;
  state.hackathonBusy = true;
  state.auditStages = [{ stage: "submit", seconds: 0 }];
  state.auditStarted = Date.now();
  state.hackathonStatus = "hackathonRunning";
  renderEditor();
  setWorkspacePane("findings");
  renderReport();
  if (location.pathname === "/workspace") focusAuditResults();
  const elapsedTimer = setInterval(() => {
    if (state.auditController === controller) renderAuditElapsed();
    else clearInterval(elapsedTimer);
  }, 1000);
  try {
    const endpoint = "/api/analyze/gemini?operation=report&fallback=rules";
    const options = { method: "POST", signal: controller.signal, headers, body };
    const progress = event => {
      if (state.auditController !== controller || !Object.hasOwn(copy().auditStages, event.stage)) return;
      state.auditStages.push({ ...event, seconds: Math.floor((Date.now() - state.auditStarted) / 1000) });
      renderAuditPipeline();
      renderAuditState();
    };
    let response;
    try {
      response = await requestEvents(endpoint, options, progress);
    } catch (error) {
      if (controller.signal.aborted || !([429, 503, 504].includes(error.status) || error.message === "stream_interrupted")) throw error;
      response = await requestEvents("/api/analyze?operation=report&fallback=rules&provider_unavailable=1", options, progress);
    }
    const { review: audit, markdown, recheck_token: nextToken } = response;
    if (state.auditController !== controller) return;
    if (state.loadAttempt === loadAttempt && spec.value === text) {
      if (audit?.schema_version !== 1 || (audit.mode !== "gemini" && !(audit.mode === "rules" && audit.ai_unavailable))
          || typeof markdown !== "string") {
        throw new Error("hackathonFailed");
      }
      const handoff = state.auditHandoff;
      const previous = state.auditBaseline || handoff?.run;
      const before = previous?.review;
      const revised = before && previous.text !== text && before.sha256 !== audit.sha256;
      const modeChanged = Boolean(revised && (before.mode !== audit.mode ||
        (before.provider && audit.provider && before.provider !== audit.provider)));
      const comparison = revised && !modeChanged ? compareAudits(before, audit) : null;
      const priorRun = state.audit;
      const confirmed = new Set();
      if (comparison && priorRun?.comparison?.before_sha256 === comparison.before_sha256 &&
          priorRun.comparison.after_sha256 === comparison.after_sha256) {
        for (const { id } of comparison.needs_review) {
          if (priorRun.confirmed.has(id)) confirmed.add(id);
        }
      }
      const run = { review: audit, markdown, recheckToken: nextToken, text, comparison, confirmed, modeChanged, edits: new Map() };
      mountAudit(run, before, handoff?.item.id);
      if (revised) state.auditHandoff = null;
      state.hackathonStatus = audit.mode === "rules" ? "rulesAuditReady" : "hackathonReady";
    } else {
      state.hackathonStatus = "";
    }
  } catch (error) {
    if (state.auditController !== controller) return;
    const message = Object.hasOwn(copy().auditErrors, error.message) ? error.message : "hackathonFailed";
    state.hackathonStatus = state.loadAttempt === loadAttempt && spec.value === text ? message : "";
  } finally {
    clearInterval(elapsedTimer);
    if (state.auditController === controller) {
      state.auditController = null;
      state.hackathonBusy = false;
      renderEditor();
      renderReport();
    }
  }
}

function syncWorkspaceRoute() {
  const params = new URLSearchParams(location.search);
  const nextCase = location.pathname !== "/workspace" ? null
    : params.get("case") === "official" ? "official" : params.get("demo") === "audit" ? "training" : null;
  routing();
  if (select("revision-dialog").open) select("revision-dialog").close();
  if (nextCase === activeCase) {
    renderEditor();
    return;
  }
  const enteringCase = nextCase && !activeCase;
  if (enteringCase) saveRecovery();
  state.audit?.cancelTranslation?.();

  state.loadAttempt++;
  state.reviewAttempt++;
  if (state.hackathonBusy) state.hackathonStatus = "";
  state.controller?.abort();
  state.auditController?.abort();
  state.controller = state.auditController = null;
  state.busy = state.hackathonBusy = false;
  state.loading = null;
  state.reviewRun = null;
  const auditResults = select("audit-results");
  if (enteringCase) {
    draftWorkspace = {
      state: Object.fromEntries(documentStateKeys.map(key => [key, state[key]])),
      value: spec.value, selection: [spec.selectionStart, spec.selectionEnd],
      pane: select("review-page").dataset.pane, layout: select("review-page").dataset.layout, auditNodes: [...auditResults.childNodes],
    };
  }
  const draft = nextCase ? null : draftWorkspace;
  Object.assign(state, draft?.state || newDocumentState());
  state.audit?.setLanguage(state.lang);
  activeCase = nextCase;
  state.auditDemo = Boolean(nextCase);
  select("review-page").classList.toggle("is-demo", Boolean(nextCase));
  select("demo-tools").hidden = !nextCase;
  const caseLabel = select("case-label");
  caseLabel.dataset.i18n = nextCase === "official" ? "officialCase" : "demoLabel";
  caseLabel.textContent = copy()[caseLabel.dataset.i18n];
  select("official-source").hidden = nextCase !== "official";
  select("workflow-message").textContent = "";
  spec.value = draft?.value || "";
  spec.setSelectionRange(...(draft?.selection || [0, 0]));
  spec.scrollTop = 0;
  previewSource = null;
  select("review-page").dataset.layout = draft?.layout || "split";
  select("document-preview").replaceChildren();
  auditResults.replaceChildren(...(draft?.auditNodes || []));
  auditResults.scrollTop = 0;
  setWorkspacePane(draft?.pane || "document");
  clearActivity();
  renderEditor();
  renderReport();
  if (nextCase) openAuditDemo();
  else draftWorkspace = null;
}

async function openAuditDemo() {
  const attempt = ++state.loadAttempt;
  const official = activeCase === "official";
  state.loading = official ? "official" : "example";
  state.notice = "";
  renderEditor();
  try {
    const response = await responseFor(official ? "/api/official-input" : "/qr-refund-demo.docx");
    const content = await response.blob();
    if (attempt !== state.loadAttempt) return;
    await upload(new File([content], official ? "requirements.md" : "qr-refund-demo.docx", { type: content.type }));
  } catch (error) {
    if (attempt === state.loadAttempt) state.notice = official ? "official_input_unavailable" : error.message || "generic";
  } finally {
    if (attempt === state.loadAttempt) {
      state.loading = null;
      renderEditor();
    }
  }
}

function exportReport() {
  if (!state.report || state.revision) return;
  const t = copy();
  const findings = state.report.findings.map((item) => {
    const [title, description, , acceptanceTest] = t.rules[item.code];
    return { ...item, title, description: item.explanation || description, clarification: authorQuestion(item),
      recommendation: item.recommendation || t.repair.hints[item.code], acceptance_test: item.acceptance_test || acceptanceTest || null };
  });
  const json = JSON.stringify({ ...state.report, findings, locale: state.lang,
    ...(state.comparison && { comparison: state.comparison }) }, null, 2);
  downloadFile(json + "\n", "application/json", "sana1-review.json");
}

function downloadFile(content, type, name) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = element("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 3000);
}

document.querySelectorAll("[data-lang]").forEach((button) => button.addEventListener("click", () => {
  state.lang = button.dataset.lang;
  try { localStorage.setItem("sana1-language", state.lang); } catch {}
  translate();
}));
try { setTheme(localStorage.getItem("sana1-theme") === "light" ? "light" : "dark"); }
catch { setTheme("dark"); }
select("theme-toggle").addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  setTheme(theme);
  try { localStorage.setItem("sana1-theme", theme); } catch {}
});
for (const link of document.querySelectorAll("a[data-route]")) {
  link.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.shiftKey || event.metaKey || event.altKey) return;
    event.preventDefault();
    navigate(link.pathname + link.search);
  });
}
window.addEventListener("popstate", syncWorkspaceRoute);
select("demo-load").addEventListener("click", openAuditDemo);
function setWorkspacePane(pane) {
  select("review-page").dataset.pane = pane;
  const split = isSplitWorkspace();
  select("split-view").setAttribute("aria-pressed", String(split));
  for (const button of select("workspace-jumps").querySelectorAll("[data-jump]")) {
    button.setAttribute("aria-pressed", String(!split && button.dataset.jump === (pane === "document" ? "input-heading" : "results-heading")));
  }
  renderAuditProgress();
  scheduleRecovery();
}
function isSplitWorkspace() {
  const { layout, hasResults } = select("review-page").dataset;
  return wideWorkspace.matches && hasResults === "true" && layout === "split";
}
wideWorkspace.addEventListener("change", () => setWorkspacePane(select("review-page").dataset.pane));
select("split-view").addEventListener("click", () => {
  select("review-page").dataset.layout = "split";
  setWorkspacePane(select("review-page").dataset.pane);
  window.scrollTo(0, 0);
});
for (const button of select("workspace-jumps").querySelectorAll("[data-jump]")) {
  button.addEventListener("click", () => {
    if (wideWorkspace.matches) select("review-page").dataset.layout = "focus";
    setWorkspacePane(button.dataset.jump === "input-heading" ? "document" : "findings");
    window.scrollTo(0, 0);
    select(button.dataset.jump).focus({ preventScroll: true });
  });
}
select("audit-progress").addEventListener("click", event => {
  const button = event.target.closest("[data-step]");
  if (!button || button.disabled) return;
  const { step } = button.dataset;
  const run = state.audit;
  const message = select("workflow-message");
  message.textContent = "";
  if (step === "document") {
    if (isSplitWorkspace()) select("review-page").dataset.layout = "focus";
    setWorkspacePane("document");
    const target = spec.value.trim() ? select("input-heading") : select("pick-file");
    target.scrollIntoView({ block: "nearest" });
    target.focus({ preventScroll: true });
  } else if (state.hackathonBusy) {
    message.textContent = copy().auditWorking;
    setWorkspacePane("findings");
    focusAuditResults();
  } else if (step === "changes" && run?.edits.size) {
    setWorkspacePane("findings");
    select("apply-audit-queue").focus();
  } else if (run && (step !== "changes" || run.comparison)) {
    setWorkspacePane("findings");
    run.openPanel(step);
  } else {
    message.textContent = !spec.value.trim() ? copy().stepNeedsDocument
      : run ? copy().stepNeedsChanges : copy().stepNeedsAudit;
    if (!spec.value.trim()) select("pick-file").focus();
    else if (!run && !select("hackathon-report").disabled) select("hackathon-report").focus();
  }
});
select("audit-handoff-return").addEventListener("click", () => {
  const handoff = state.auditHandoff;
  if (!handoff || handoff.run !== state.audit) return;
  setWorkspacePane("findings");
  if (handoff.setCheck) handoff.run.revealSetCheck(handoff.item.criterion);
  else if (handoff.item.question) handoff.run.revealFinding(handoff.item.id);
  else handoff.run.revealRequirement(handoff.item.id);
});
select("back-to-finding").addEventListener("click", () => {
  setWorkspacePane("findings");
  const finding = [...resultBox.querySelectorAll(".finding:not([hidden])")].find((node) => node.dataset.id === state.sourceFinding);
  if (finding) finding.open = true;
  const target = finding?.querySelector("summary") || select("results-heading");
  target.focus({ preventScroll: true });
  if (finding) revealInside(resultBox, target);
});
select("show-document").addEventListener("click", () => setDocumentView("preview"));
select("show-source").addEventListener("click", () => { setDocumentView("source"); spec.focus({ preventScroll: true }); });
select("show-pdf").addEventListener("click", () => setDocumentView("pdf"));
select("pdf-previous").addEventListener("click", () => showPdfPage(state.pdfReader.page - 1));
select("pdf-next").addEventListener("click", () => showPdfPage(state.pdfReader.page + 1));
select("pdf-retry").addEventListener("click", () => showPdfPage(state.pdfReader.page));
select("pdf-jump").addEventListener("submit", (event) => {
  event.preventDefault();
  showPdfPage(select("pdf-number").valueAsNumber);
});
select("attach-images").addEventListener("click", () => select("image-files").click());
select("image-files").addEventListener("change", (event) => {
  addDocumentImages([...event.currentTarget.files]);
  event.currentTarget.value = "";
});
function bindSourceEditorEvents(editor) {
  editor.addEventListener("scroll", () => { select("source-lines").scrollTop = editor.scrollTop; }, { passive: true });
  let wholeDocumentEdit = null;
  editor.addEventListener("beforeinput", event => {
    const type = event.inputType;
    wholeDocumentEdit = draftReplacementInputs.has(type) && !event.isComposing && !editor.readOnly && editor.value &&
      editor.selectionStart === 0 && editor.selectionEnd === editor.value.length ? { type, text: editor.value } : null;
  });
  editor.addEventListener("input", event => {
    if (editor !== spec) return;
    const previous = wholeDocumentEdit;
    wholeDocumentEdit = null;
    if (previous && previous.type === event.inputType && previous.text !== spec.value) {
      startEditorDraft(spec.value, spec.selectionStart);
      return;
    }
    state.undo = [];
    state.clarifications = [];
    state.loadAttempt++;
    state.loading = null;
    state.notice = "";
    cancelAudit();
    if (state.auditHandoff) state.auditHandoff.sourceStatus = "";
    rememberRevision();
    state.comparison = null;
    cancelReview();
    if (state.revision && spec.value === state.reviewedText) {
      state.report = state.revision;
      state.revision = null;
      state.editedLines.clear();
    }
    clearActivity();
    renderEditor();
    renderReport();
  });
}
bindSourceEditorEvents(spec);
select("pick-file").addEventListener("click", () => select("file").click());
select("file").addEventListener("change", (event) => {
  upload(event.target.files[0]);
  event.target.value = "";
});
const dropZone = document.querySelector(".editor-panel .panel-body");
dropZone.addEventListener("dragover", (event) => {
  if (!event.dataTransfer.types.includes("Files")) return;
  event.preventDefault();
  dropZone.classList.add("dragging");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
dropZone.addEventListener("drop", (event) => {
  if (!event.dataTransfer.files.length) return;
  event.preventDefault();
  dropZone.classList.remove("dragging");
  upload(event.dataTransfer.files[0]);
});
select("clear").addEventListener("click", () => startEditorDraft(""));
select("session-enabled").addEventListener("change", event => {
  setRecoveryEnabled(event.currentTarget.checked);
});
select("audit-results").addEventListener("click", scheduleRecovery);
window.addEventListener("pagehide", saveRecovery);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") saveRecovery();
});
document.querySelector(".skip-link").addEventListener("click", (event) => {
  event.preventDefault();
  select("main").focus();
});
select("hackathon-report").addEventListener("click", () => runAudit());
select("apply-audit-queue").addEventListener("click", applyAuditQueue);
select("undo-audit-revision").addEventListener("click", () => {
  const undo = state.auditUndo;
  if (!undo || undo.after !== spec.value || state.hackathonBusy) return;
  state.auditUndo = null;
  for (const [key, decision] of state.auditDecisions) {
    if (decision.source_sha256 === undo.sha) state.auditDecisions.delete(key);
  }
  writeRevision(undo.before);
  runAudit();
});
select("audit-state-stop").addEventListener("click", () => {
  cancelAudit("auditStopped");
  renderEditor();
  renderReport();
  select("audit-state-retry").focus();
});
select("audit-state-retry").addEventListener("click", () => runAudit());
select("download-toggle").addEventListener("click", () => setDownloadsOpen(select("download-options").hidden));
select("download-options").addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setDownloadsOpen(false);
    select("download-toggle").focus();
  }
});
select("export").addEventListener("click", exportReport);
select("docx-copy").addEventListener("click", async event => {
  const button = event.currentTarget;
  const status = select("document-format-notice");
  button.disabled = true;
  status.hidden = true;
  try { await downloadWord(spec.value, state.media, state.lang); }
  catch (error) {
    status.textContent = copy().errors[error.message] || copy().errors.generic;
    status.hidden = false;
  } finally { button.disabled = false; }
});
select("markdown-copy").addEventListener("click", () => downloadFile(spec.value, "text/markdown;charset=utf-8", "SanA1-specification.md"));
select("download-word").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  const errorBox = select("export-error");
  errorBox.hidden = true;
  try { await downloadWord(spec.value, state.media, state.lang); }
  catch (error) {
    errorBox.textContent = copy().errors[error.message] || copy().errors.generic;
    errorBox.hidden = false;
  } finally { button.disabled = false; }
});
select("download-questions").addEventListener("click", downloadQuestions);
select("download-text").addEventListener("click", () => downloadFile(state.reviewedText, "text/plain;charset=utf-8", "sana1-updated-spec.txt"));
select("download-formatted").addEventListener("click", () => downloadFile(formattedCopy(state.reviewedText, state.media, copy(), state.lang),
  "text/html;charset=utf-8", "sana1-updated-spec.html"));

if (location.pathname === "/" && (location.hash === "#review" || location.hash === "#evaluation")) {
  history.replaceState(null, "", "/workspace");
}
restoreRecovery();
translate();
request("/api/config").then((config) => {
  state.config = config;
  renderEditor();
}).catch(() => {
  state.config.gemini = false;
  renderEditor();
});
syncWorkspaceRoute();
