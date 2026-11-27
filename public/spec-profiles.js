// These are focused authoring guides. The linked editions define the complete standards.
const profiles = {
  generic: { en: "General review", ru: "Обычная проверка", topics: [] },
  iso: {
    en: "International · ISO/IEC/IEEE 29148:2018", ru: "Международный · ISO/IEC/IEEE 29148:2018",
    scope: { en: "Requirements for systems and software.", ru: "Требования к системам и программному обеспечению." },
    url: "https://www.iso.org/standard/72089.html", topics: ["purpose", "users", "functions", "constraints", "verification"],
  },
  kz: {
    en: "Kazakhstan · ST RK 34.015-2002", ru: "Казахстан · СТ РК 34.015-2002",
    scope: { en: "Technical assignment for an automated system in Kazakhstan.", ru: "Техническое задание на автоматизированную систему в Казахстане." },
    url: "https://new-shop.ksm.kz/catalog/document/898/", topics: ["purpose", "object", "functions", "stages", "acceptance"],
  },
  gost: {
    en: "Interstate · GOST 34.602-2020", ru: "Межгосударственный · ГОСТ 34.602-2020",
    scope: { en: "Technical assignment for creating or upgrading an automated system.", ru: "Техническое задание на создание или модернизацию автоматизированной системы." },
    url: "https://protect.gost.ru/gost/details/5876f733-ee91-431a-8cb6-9e02ea2436ac",
    topics: ["overview", "purpose", "object", "functions", "stages", "procedure", "acceptance", "readiness", "documentation", "sources"],
  },
};

const standardDetails = {
  iso: {
    title: { en: "Systems and software engineering — Life cycle processes — Requirements engineering", ru: "Systems and software engineering — Life cycle processes — Requirements engineering" },
    status: { en: "Second edition, published in 2018 and confirmed by ISO in 2024.", ru: "Второе издание опубликовано в 2018 году и подтверждено ISO в 2024 году." },
    coverage: { en: "SanA1 searches for five drafting topics. Full conformity also requires review of applicable processes and information items throughout the life cycle.", ru: "SanA1 ищет пять тем в проекте ТЗ. Для оценки соответствия также проверяют применимые процессы и информационные материалы на протяжении жизненного цикла." },
    publisher: "ISO",
  },
  kz: {
    title: { en: "Information technology. Standards for automated systems. Technical assignment for creating an automated system (translated title)", ru: "Информационная технология. Комплекс стандартов на автоматизированные системы. Техническое задание на создание автоматизированной системы" },
    status: { en: "National standard in force in Kazakhstan since 1 January 2004.", ru: "Национальный стандарт Республики Казахстан. Действует с 1 января 2004 года." },
    coverage: { en: "SanA1 searches for five drafting topics. Verification of all content and formatting requirements needs the full official edition.", ru: "SanA1 ищет пять тем в проекте ТЗ. Все требования к содержанию и оформлению сверяют с полным официальным изданием." },
    publisher: "КазСтандарт",
  },
  gost: {
    title: { en: "Information technology. Set of standards for automated systems. Technical assignment for developing of automated system", ru: "Информационные технологии. Комплекс стандартов на автоматизированные системы. Техническое задание на создание автоматизированной системы" },
    status: { en: "Adopted by the Interstate Council in 2020. In force in Russia since 1 January 2022. KazStandard lists it as not introduced in Kazakhstan.", ru: "Принят МГС в 2020 году. В России действует с 1 января 2022 года. Статус в каталоге Казахстана — «Принят в МГС (не введен)»." },
    coverage: { en: "SanA1 looks for headings and text for the ten sections in clause 4.1. Sections may be in annexes under 4.2. Check the substance, formatting and approvals against the official edition with applicable corrections.", ru: "SanA1 ищет заголовки и текст десяти разделов из п. 4.1. По п. 4.2 разделы могут оформляться приложениями. Содержание, оформление и согласование сверяют с официальным изданием с учётом поправок." },
    publisher: "Росстандарт",
  },
};

const topics = {
  overview: {
    en: ["Project particulars", "What is the system called, who commissioned it, and what are the agreed dates and funding arrangements?"],
    ru: ["Общие сведения о проекте", "Как называется система, кто заказчик, какие сроки и порядок финансирования согласованы?"],
    title: /^(project particulars|general (?:information|details)|общие сведения)/i,
  },
  procedure: {
    en: ["Development procedure", "How will development be organized, reviewed and approved?"],
    ru: ["Порядок разработки", "Как будут организованы разработка системы, рассмотрение результатов и их согласование?"],
    title: /^(development procedure|system development process|порядок разработки)/i,
  },
  readiness: {
    en: ["Preparing the site for commissioning", "What changes to the site, personnel or data must be ready before the system goes into service?"],
    ru: ["Подготовка объекта к вводу системы", "Какие работы с объектом, персоналом и данными нужно завершить до ввода системы в действие?"],
    title: /^(preparing the site|commissioning readiness|site preparation|подготовка объекта|требования к .{0,38}работ по подготовке)/i,
  },
  sources: {
    en: ["Development sources", "Which approved documents or materials provided the basis for designing the system?"],
    ru: ["Источники разработки", "Какие утверждённые документы и материалы использованы при разработке системы?"],
    title: /^(development sources|design sources|sources for development|источники разработки)/i,
  },
  purpose: {
    en: ["Purpose and scope", "What outcome must the project achieve, and which processes are in scope?"],
    ru: ["Цель и границы проекта", "Какой результат должен дать проект и какие процессы в него входят?"],
    title: /^(scope|purpose|objectives?|project goals?|goals?|область применения|назначение|цель|цели|границы проекта)/i,
    evidence: /(?:the (?:aim|purpose|goal) (?:is|of)|in scope (?:are|is)|цель проекта\s*[—–:-]|система предназначена для)/i,
  },
  users: {
    en: ["Users and stakeholders", "Who needs this system, and which outcome does each role need?"],
    ru: ["Пользователи и заинтересованные стороны", "Кому нужна система и какой результат ожидает каждая роль?"],
    title: /^(users?|stakeholders?|user roles?|заинтересованные стороны|пользователи|роли пользователей)/i,
    evidence: /(?:target users (?:are|include)|целевые пользователи\s*[—–:-]|роль пользователя\s*[—–:-])/i,
  },
  functions: {
    en: ["Functional requirements", "Which action must the system perform, under what conditions, and with what result?"],
    ru: ["Функциональные требования", "Какое действие должна выполнить система, при каких условиях и с каким результатом?"],
    title: /^(functional requirements|system requirements|system functions|функциональные требования|требования к (?:автоматизированной )?системе|функции системы)/i,
    evidence: /(?:the (?:system|application|app|service) (?:shall|must|displays?|records?|sends?)|(?:система|приложение|сервис) (?:долж[а-я]*|отображает|записывает|отправляет))/i,
  },
  constraints: {
    en: ["Operating constraints", "Which operating conditions, dependencies or limits must the design respect?"],
    ru: ["Ограничения и условия эксплуатации", "Какие условия эксплуатации, зависимости или ограничения должна учитывать разработка?"],
    title: /^(operating constraints|constraints|operating environment|limitations|ограничения|условия эксплуатации)/i,
    evidence: /(?:must operate (?:within|under)|предельная нагрузка\s*[—–:-]|работает при температуре)/i,
  },
  verification: {
    en: ["Requirement verification", "How will the team verify a named requirement and what result counts as a pass?"],
    ru: ["Проверка требований", "Как команда проверит конкретное требование и какой результат подтвердит его выполнение?"],
    title: /^(requirement verification|verification|acceptance (?:tests?|criteria)|проверка требований|верификация|критерии при[её]мки|при[её]мочные испытания)/i,
    evidence: /(?:test passes (?:when|if)|pass criterion|тест (?:считается пройденным|пройден, если))/i,
  },
  object: {
    en: ["Process to automate", "Which existing process is being automated, where is it used, and what inputs does it receive?"],
    ru: ["Объект автоматизации", "Какой существующий процесс автоматизируют, где он выполняется и какие данные получает?"],
    title: /^(process to automate|automation (?:target|object)|current process|объект[а-я ]*автоматизации|характеристик[а-я ]+объект|текущий процесс)/i,
    evidence: /(?:currently processed (?:by|in)|объектом автоматизации является|сейчас процесс выполняется)/i,
  },
  stages: {
    en: ["Delivery stages", "What work will each stage deliver and how will the team know it is complete?"],
    ru: ["Этапы и результаты работ", "Какой результат команда передаст на каждом этапе и как подтвердит его завершение?"],
    title: /^(delivery stages|work stages|milestones|delivery plan|состав и содержание работ|этапы|план работ)/i,
    evidence: /(?:milestone \d|этап \d+\s*[:.—–-])/i,
  },
  acceptance: {
    en: ["System acceptance", "Who accepts the system, which tests will be run, and which record confirms the decision?"],
    ru: ["Порядок приёмки системы", "Кто принимает систему, какие испытания проводятся и каким документом фиксируется решение?"],
    title: /^(system acceptance|acceptance procedure|acceptance (?:plan|criteria)|порядок (?:контроля и )?при[её]мки|при[её]мка|критерии при[её]мки)/i,
    evidence: /(?:acceptance is signed|при[её]мк[ау] проводит|акт при[её]мки подписыва)/i,
  },
  documentation: {
    en: ["Documentation to deliver", "Which manuals, specifications or instructions must be delivered, to whom and in what format?"],
    ru: ["Требования к документации", "Какие руководства, описания или инструкции нужно передать, кому и в каком формате?"],
    title: /^(documentation to deliver|documentation requirements|documentation|требования к документ(?:ации|ированию)|комплект документации|документация)/i,
    evidence: /(?:deliver (?:a |the )?user manual|переда[её]т руководство пользователя)/i,
  },
};

const labels = {
  en: { format: "Standard", optional: "Structural check", basic: "None · general review only", detail: "Edition, sources and coverage", kzStatus: "Kazakhstan registry", brief: "Selected topics only", gostBrief: "Section structure · Kazakhstan: not introduced", sources: "Sources", topics: "Topics checked", structure: "Structural check", remaining: "Topics to clarify",
    found: "Text found for all selected topics.", hint: "SanA1 looks for these topics in the text. Choose one to add the author’s answer.",
    topic: "Topic", apply: "Add answer to specification", shorter: "Shorten the answer to fit the document limit." },
  ru: { format: "Стандарт", optional: "Структурная проверка", basic: "Без стандарта · только общая проверка", detail: "Редакция, источники и охват", kzStatus: "Каталог Казахстана", brief: "Проверка отдельных тем", gostBrief: "Структура разделов · В Казахстане не введён", sources: "Источники", topics: "Проверяемые темы", structure: "Структурная проверка", remaining: "Темы для уточнения",
    found: "По всем выбранным темам найден текст.", hint: "SanA1 ищет эти темы в тексте. Выберите тему и добавьте ответ автора.",
    topic: "Тема", apply: "Внести ответ в ТЗ", shorter: "Сократите ответ, чтобы поместиться в допустимый объём ТЗ." },
};

// §4.1 lists the ten sections. §§4.3–4.12 give the content of each section.
const gostClauses = { overview: "4.3", purpose: "4.4", object: "4.5", functions: "4.6", stages: "4.7",
  procedure: "4.8", acceptance: "4.9", readiness: "4.10", documentation: "4.11", sources: "4.12" };
const gostTopics = {
  purpose: { en: ["System objectives and intended use", "What will the system be used for and which measurable outcomes should improve?"],
    ru: ["Цели и назначение системы", "Для каких процессов создаётся система и какие показатели должны измениться?"] },
  functions: { en: ["Requirements for the automated system", "Which system-wide, functional and supporting requirements apply?"],
    ru: ["Требования к автоматизированной системе", "Какие требования предъявляют к системе в целом, её функциям и видам обеспечения?"] },
  stages: { en: ["Work to create the system", "What work is planned, in which stages and with which deliverables?"],
    ru: ["Состав и содержание работ", "Какие работы запланированы по созданию системы, каковы этапы и результаты?"] },
};

function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text) item.textContent = text;
  if (className) item.className = className;
  return item;
}

const placeholder = /^(?:[-–—.\s]*|tbd|to be (?:confirmed|determined)|не определено|уточнить|будет уточнено)$/i;
const stripNumber = (s) => s.trim().replace(/^(?:#{1,6}\s+|§?\d+(?:\.\d+)*[.)]?\s+)+/, "").replace(/\*\*/g, "")
  .replace(/^(?:приложение|annex|appendix)\s+[a-zа-я\d]+[.)\s:—-]+/iu, "");

function headingTopic(line) {
  const label = stripNumber(line).split(/[:：]/, 1)[0].trim();
  if (label.length > 190 || /[.!?;]$|\.{2,}\s*\d+$/.test(label)) return undefined;
  for (const [key, topic] of Object.entries(gostTopics)) {
    if ([topic.en[0], topic.ru[0]].some((title) => label.toLowerCase() === title.toLowerCase())) return key;
  }
  return Object.keys(topics).find((key) => topics[key].title.test(label));
}

function locateTopic(lines, key, headingRequired) {
  const topic = topics[key];
  let insertion = -1;
  for (const [index, line] of lines.entries()) {
    if (headingTopic(line) !== key) continue;
    insertion = index;
    const inline = line.match(/[:：]\s*(.+)$/)?.[1];
    if (inline && !placeholder.test(inline.trim())) return null;
    for (let next = index + 1; next < lines.length; next++) {
      const content = lines[next].trim();
      const heading = /^(#{1,6})\s/.exec(content);
      if (headingTopic(content) || (heading && heading[1].length <= (/^#+/.exec(line.trim())?.[0].length || 6))) break;
      if (heading) continue;
      if (!placeholder.test(content) && /\p{L}|\d/u.test(content)) return null;
    }
  }
  if (!headingRequired && topic.evidence && lines.some((line) => topic.evidence.test(line))) return null;
  return { key, insertion };
}

export function mountProfiles(container, { language, getText, applyText }) {
  const field = node("select");
  field.id = "spec-profile";
  const label = node("label");
  label.htmlFor = field.id;
  const note = node("div", "", "profile-note");
  const details = node("details", "", "standard-info");
  const chooser = node("div", "", "profile-chooser");
  chooser.append(label, field, note);
  chooser.classList.add("profile-options");
  container.append(chooser);
  let active = "generic";
  const reportAnchor = document.createComment("profile");
  let report;
  let snapshot;
  let selected;
  const drafts = new Map();
  const translatedLabels = lang => lang === "kk" ? {
    ...labels.ru, format: "ТЗ құрылымы", basic: "Қалыпты ТЗ", detail: "Стандарт ауқымы мен дереккөздері",
    structure: "Құрылымды тексеру", remaining: "Толықтыру керек", topics: "Тексерілген бөлімдер",
    topic: "Толықтыратын бөлім", apply: "Құжатқа қосу",
  } : labels[lang];

  function refresh() {
    const lang = language();
    const catalogLang = lang === "kk" ? "ru" : lang;
    const t = translatedLabels(lang);
    label.textContent = t.format;
    field.replaceChildren(new Option(t.basic, "generic"),
      ...["iso", "kz", "gost"].map(key => new Option(profiles[key][catalogLang], key)));
    field.value = active;
    const profile = profiles[active];
    note.hidden = !profile.url;
    note.replaceChildren();
    if (profile.url) {
      const meta = standardDetails[active];
      const info = node("div", "", "standard-content");
      const refs = node("div", "", "standard-sources");
      const sources = [[meta.publisher, profile.url]];
      if (active === "gost") sources.push([t.kzStatus, "https://new-shop.ksm.kz/catalog/document/73214/"]);
      for (const [name, url] of sources) {
        const link = node("a", name);
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        refs.append(link);
      }
      info.append(node("strong", meta.title[catalogLang]), node("p", meta.status[catalogLang]), node("p", profile.scope[catalogLang]),
        node("p", meta.coverage[catalogLang]), refs);
      details.replaceChildren(node("summary", t.detail), info);
      note.append(node("span", active === "gost" ? t.gostBrief : t.brief), details);
    }
    if (reportAnchor.isConnected) renderReport(reportAnchor.parentNode);
  }

  function renderReport(parent) {
    const wasOpen = report?.open || false;
    report?.remove();
    report = undefined;
    parent.append(reportAnchor);
    const profile = profiles[active];
    if (!profile.topics.length) return;
    const text = getText();
    if (snapshot !== text) {
      drafts.clear();
      selected = undefined;
      snapshot = text;
    }
    const lines = text.split(/\r?\n/);
    const missing = profile.topics.map((key) => locateTopic(lines, key, active === "gost")).filter(Boolean);
    const t = translatedLabels(language());
    const lang = language() === "kk" ? "ru" : language();
    const topicCopy = (key, locale) => (active === "gost" && gostTopics[key] ? gostTopics[key] : topics[key])[locale];
    const reference = (key) => active === "gost" ? "§ " + gostClauses[key] + " · " : "";
    report = node("details", "", "profile-report report-details");
    report.open = wasOpen;
    report.append(node("summary", t.structure + " · " + t.remaining + " · " + missing.length));
    report.append(node("p", standardDetails[active].coverage[lang]));
    const inventory = node("details", "", "standard-inventory");
    inventory.append(node("summary", t.topics + " · " + profile.topics.length));
    const list = node("ul");
    for (const key of profile.topics) {
      list.append(node("li", reference(key) + topicCopy(key, lang)[0]));
    }
    inventory.append(list);
    report.append(inventory);
    parent.append(report);
    if (!missing.length) {
      report.append(node("p", t.found));
      return;
    }
    report.append(node("p", t.hint));
    const form = node("form", "", "profile-form repair-fields");
    const chooseLabel = node("label", t.topic);
    const choose = node("select");
    for (const { key } of missing) {
      choose.add(new Option(reference(key) + topicCopy(key, lang)[0], key));
    }
    if (missing.some(({ key }) => key === selected)) choose.value = selected;
    chooseLabel.append(choose);
    const answerLabel = node("label");
    const question = node("span");
    const answer = node("textarea");
    answer.rows = 3;
    answer.required = true;
    answerLabel.append(question, answer);
    const save = node("button", t.apply, "button button-compact primary");
    save.type = "submit";
    function syncQuestion() {
      selected = choose.value;
      question.textContent = topicCopy(selected, lang)[1];
      answer.value = drafts.get(selected) || "";
      answer.setCustomValidity("");
      save.disabled = !answer.value.trim();
    }
    choose.addEventListener("change", syncQuestion);
    answer.addEventListener("input", () => {
      drafts.set(choose.value, answer.value);
      answer.setCustomValidity("");
      save.disabled = !answer.value.trim();
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!answer.value.trim()) return;
      if (text !== getText()) { renderReport(parent); return; }
      const { key, insertion } = missing.find((entry) => entry.key === choose.value);
      const sectionText = answer.value.trim();
      const updated = [...lines];
      if (insertion >= 0) {
        const heading = updated[insertion];
        const inline = heading.match(/^(.+?[:：]\s*)(\S.*)$/);
        let next = insertion + 1;
        while (next < updated.length && !updated[next].trim()) next++;
        if (inline && placeholder.test(inline[2].trim())) updated[insertion] = inline[1] + sectionText;
        else if (next < updated.length && placeholder.test(updated[next].trim())) updated[next] = sectionText;
        else updated.splice(insertion + 1, 0, sectionText);
      }
      else {
        const russianWords = text.match(/[а-яё]{2,}/gi)?.length || 0;
        const englishWords = text.match(/[a-z]{2,}/gi)?.length || 0;
        const documentLanguage = russianWords === englishWords ? lang : russianWords > englishWords ? "ru" : "en";
        updated.push("", "## " + topicCopy(key, documentLanguage)[0], sectionText);
      }
      const result = updated.join(text.includes("\r\n") ? "\r\n" : "\n");
      if (applyText(result, { question: question.textContent, source_lines: insertion >= 0 ? [insertion + 1] : [], wording: sectionText }) === false) {
        answer.setCustomValidity(t.shorter);
        answer.reportValidity();
      }
    });
    syncQuestion();
    form.append(chooseLabel, answerLabel, save);
    report.append(form);
  }

  field.addEventListener("change", () => {
    active = field.value;
    selected = undefined;
    drafts.clear();
    details.open = false;
    refresh();
  });
  refresh();
  return { refresh, renderReport };
}
