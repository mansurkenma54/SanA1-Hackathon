"""Fixed audit headings and labels shared by the English and Kazakh reports."""

# Templates use the renderer's placeholders. All source-specific prose still
# follows the model translation path with its citation and quantity checks.
_CAPTIONS = {
    "Отчёт о проверке требований": ("Requirements review", "Талаптарды тексеру есебі"),
    "Паспорт прогона": ("Run details", "Тексеру деректері"),
    "Документ": ("Document", "Құжат"),
    "Исходный файл": ("Source file", "Бастапқы файл"),
    "⟦0⟧ исходного файла": ("Source file ⟦0⟧", "Бастапқы файлдың ⟦0⟧ мәні"),
    "Дата и время": ("Date and time", "Күні мен уақыты"),
    "Версия ⟦0⟧ (Git)": ("⟦0⟧ version (Git)", "⟦0⟧ нұсқасы (Git)"),
    "Режим": ("Review mode", "Тексеру режимі"),
    "Модель и правила ⟦0⟧": ("Model and ⟦0⟧ rules", "Модель және ⟦0⟧ ережелері"),
    "Локальные правила ⟦0⟧": ("⟦0⟧ local rules", "⟦0⟧ жергілікті ережелері"),
    "Проверка требований, часть ⟦0⟧": ("Requirements review, part ⟦0⟧", "Талаптарды тексеру, ⟦0⟧-бөлік"),
    "Повторная проверка пунктов и цитат, часть ⟦0⟧": ("Rechecking clauses and quotes, part ⟦0⟧", "Тармақтар мен дәйексөздерді қайта тексеру, ⟦0⟧-бөлік"),
    "Записей модели исключено после проверки": ("Model entries excluded after verification", "Тексеруден кейін алынып тасталған модель жазбалары"),
    "Требований с индивидуальной оценкой ИИ": ("Requirements individually reviewed by AI", "ЖИ жеке тексерген талаптар"),
    "⟦0⟧ из ⟦1⟧": ("⟦0⟧ of ⟦1⟧", "Тексерілгені ⟦0⟧, барлығы ⟦1⟧"),
    "Требуют индивидуальной сверки": ("Require individual verification", "Жеке тексеруді қажет етеді"),
    "Ограничения и проверка доказательств": ("Limitations and evidence checks", "Шектеулер және дәйексөздерді тексеру"),
    "Выделенные требования": ("Extracted requirements", "Құжаттан анықталған талаптар"),
    "⟦0⟧ отчёта": ("Report ⟦0⟧", "Есептегі ⟦0⟧"),
    "⟦0⟧ в источнике": ("Source ⟦0⟧", "Түпнұсқадағы ⟦0⟧"),
    "Краткая формулировка": ("Requirement summary", "Талаптың қысқаша мазмұны"),
    "Источник": ("Source", "Дереккөз"),
    "Без номера": ("Unnumbered", "Нөмірі көрсетілмеген"),
    "Проверка каждого требования": ("Individual requirement reviews", "Әр талапты жеке тексеру"),
    "Оценка": ("Assessment", "Баға"),
    "Связанные нарушения": ("Related findings", "Қатысты ескертулер"),
    "Проверка набора требований": ("Specification assessment", "Талаптар жиынын бағалау"),
    "Критерий": ("Criterion", "Өлшемшарт"),
    "Результат": ("Result", "Нәтиже"),
    "Основание": ("Evidence", "Негіздеме"),
    "Однозначность": ("Clarity", "Бірмәнділік"),
    "Проверяемость": ("Verifiability", "Тексеру мүмкіндігі"),
    "Единичность": ("Singularity", "Талаптың даралығы"),
    "Реализуемость": ("Feasibility", "Іске асыру мүмкіндігі"),
    "Непротиворечивость": ("Consistency", "Өзара үйлесімділік"),
    "Полнота": ("Completeness", "Толықтық"),
    "Прослеживаемость": ("Traceability", "Талаптың шығу тегін қадағалау"),
    "Ограничения реализации": ("Implementation constraints", "Іске асыру шектеулері"),
    "Признаки проблемы не обнаружены": ("No issue identified", "Мәселе анықталған жоқ"),
    "Есть проблема": ("Issue identified", "Мәселе анықталды"),
    "Недостаточно сведений": ("Insufficient information", "Мәлімет жеткіліксіз"),
    "Внутренние ссылки": ("Internal references", "Ішкі сілтемелер"),
    "Внешние ссылки": ("External references", "Сыртқы сілтемелер"),
    "Найденные нарушения": ("Findings", "Анықталған мәселелер"),
    "Приоритет": ("Priority", "Басымдық"),
    "Блокирует работу": ("Blocker", "Жұмысты бастауға кедергі"),
    "Существенный": ("Major", "Елеулі"),
    "Низкий": ("Low", "Төмен"),
    "Обнаружено": ("Found by", "Анықтаған"),
    "Нарушение": ("Issue", "Мәселе"),
    "Требования": ("Requirements", "Талаптар"),
    "Вопрос автору": ("Question for the author", "Авторға сұрақ"),
    "Что уточнить или исправить": ("What to clarify or correct", "Нені нақтылау немесе түзету керек"),
    "Уверенность": ("Confidence", "Сенімділік"),
    "Вопросы автору ТЗ": ("Questions for the author", "Техникалық тапсырма авторына сұрақтар"),
    "Места в ТЗ": ("Source locations", "Құжаттағы тиісті тұстар"),
    "Сводка и готовность к разработке": ("Summary and readiness for development", "Қорытынды және әзірлеуге дайындық"),
    "Требований": ("Requirements", "Талаптар саны"),
    "Нарушений": ("Findings", "Анықталған мәселелер саны"),
    "Блокирующих": ("Blockers", "Жұмысты бөгейтін мәселелер"),
    "⟦0⟧, существенных": ("⟦0⟧, major", "⟦0⟧, елеулі мәселелер"),
    "⟦0⟧, низкого приоритета": ("⟦0⟧, low priority", "⟦0⟧, басымдығы төмен мәселелер"),
    "Критичные дефекты": ("Critical issues", "Шешуші мәселелер"),
    "не зафиксированы": ("none recorded", "анықталған жоқ"),
    "Первые шаги": ("Next steps", "Алдымен не істеу керек"),
}


def report_terms(language):
    """Return the fixed captions for the default script of a supported language."""
    base, *subtags = language.lower().split("-")
    if base not in {"en", "kk"}:
        return {}
    script = next((tag for tag in subtags if len(tag) == 4 and tag.isalpha()), None)
    if script and script != {"en": "latn", "kk": "cyrl"}[base]:
        return {}
    column = 0 if base == "en" else 1
    return {source: targets[column] for source, targets in _CAPTIONS.items()}
