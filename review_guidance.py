"""Localized finding titles, author questions and acceptance guidance."""

GUIDANCE = {
    "en": {
        "broken_reference": {
            "title": "Reference to a missing clause", "description": "An explicit reference points to a clause absent from this text.",
            "question": "Which clause defines this behavior?", "recommendation": "Confirm the target with the author, correct the reference or add the missing clause.",
            "acceptance_test": "Follow the reference and verify that the target covers this scenario."
        },
        "duplicate_clause": {
            "title": "Clause number reused", "description": "Multiple source lines declare the same clause identifier.",
            "question": "Which clause should keep this identifier?", "recommendation": "Give the other clause a unique number and update any references to it.",
            "acceptance_test": "Resolve each reference to exactly one clause."
        },
        "open_decision": {
            "title": "Unconfirmed requirement", "description": "The requirement still contains a decision placeholder.",
            "question": "What agreed value or behavior should replace this placeholder?", "recommendation": "Enter the author's decision and its unit or condition in the original clause.",
            "acceptance_test": "Check that the agreed value is present and can be tested."
        },
        "limit_conflict": {
            "title": "Conflicting monetary limits",
            "description": "The same operation and scope have different limits.",
            "question": "Which limit applies under these conditions?",
            "recommendation": "When the author confirms an amount, use it in clauses with the same limit and scope. If the scopes differ, spell out the difference in each clause.",
            "acceptance_test": "Check the approved limit exactly and then check an amount one minor currency unit above it."
        },
        "vague_requirement": {
            "title": "Unmeasurable requirement",
            "description": "The wording leaves the expected behavior open to interpretation.",
            "question": "What observable value or condition defines success?",
            "recommendation": "Replace vague terms with an agreed threshold, unit, and the event that starts the measurement.",
            "acceptance_test": "After the threshold or condition is confirmed, check one case on each side of it."
        },
        "retry_behavior": {
            "title": "Retry behavior is incomplete",
            "description": "The request is retried after a missing response. The text does not fully describe how repeat attempts are recognized and applied only once.",
            "question": "How does the system recognize a retry of the original transaction?",
            "recommendation": "Specify the identifier reused on retry, how duplicate debits are prevented, and the result returned after a retry.",
            "acceptance_test": "After the first attempt succeeds and its response is lost, retry the same operation and verify a single financial effect."
        },
        "acceptance_gap": {
            "title": "Missing acceptance criteria",
            "description": "",
            "question": "What observable result would prove this requirement is met?",
            "recommendation": "Add the starting conditions, the action, and the observable outcome.",
            "acceptance_test": ""
        },
        "semantic_conflict": {
            "title": "Possible conflicting requirements",
            "description": "",
            "question": "What behavior applies in the stated conditions?",
            "recommendation": "State which requirement applies and spell out any conditions that change it.",
            "acceptance_test": ""
        },
        "missing_scenario": {
            "title": "Possible missing scenario",
            "description": "",
            "question": "What should the system do in this scenario?",
            "recommendation": "Describe what triggers the scenario, what the system does, and what the user sees.",
            "acceptance_test": ""
        }
    },
    "ru": {
        "broken_reference": {
            "title": "Ссылка на отсутствующий пункт", "description": "В тексте есть явная ссылка на пункт, который в документе не объявлен.",
            "question": "Какой пункт описывает это поведение?", "recommendation": "Уточните у автора адрес ссылки, исправьте её или добавьте недостающий пункт.",
            "acceptance_test": "Перейдите по ссылке и проверьте, что пункт описывает нужный сценарий."
        },
        "duplicate_clause": {
            "title": "Номер пункта повторяется", "description": "Один номер присвоен нескольким строкам документа.",
            "question": "За каким пунктом закрепить этот номер?", "recommendation": "Назначьте другому пункту уникальный номер и проверьте ссылки на него.",
            "acceptance_test": "Каждая ссылка должна однозначно указывать на один пункт."
        },
        "open_decision": {
            "title": "Требование ждёт решения", "description": "В требовании осталась пометка о несогласованном решении.",
            "question": "Какое значение или поведение согласовал автор?", "recommendation": "Замените пометку решением автора и укажите единицу измерения или условие.",
            "acceptance_test": "Убедитесь, что согласованное значение указано и его можно проверить."
        },
        "limit_conflict": {
            "title": "Противоречие в денежных лимитах",
            "description": "Для одной операции при одинаковых условиях указаны разные лимиты.",
            "question": "Какой лимит действует при этих условиях?",
            "recommendation": "После согласования суммы обновите пункты с одинаковыми условиями. Если условия разные, укажите их явно в каждом пункте.",
            "acceptance_test": "Проверьте операцию на утверждённом лимите и на одну минимальную единицу валюты выше."
        },
        "vague_requirement": {
            "title": "Непроверяемое требование",
            "description": "Из формулировки нельзя однозначно определить ожидаемое поведение.",
            "question": "Какое наблюдаемое значение или условие означает успех?",
            "recommendation": "Согласуйте измеримое значение, единицу измерения и событие, с которого начинается отсчёт.",
            "acceptance_test": "После согласования значения проверьте по одному случаю с каждой стороны границы."
        },
        "retry_behavior": {
            "title": "Не описан безопасный повтор",
            "description": "Запрос повторяется после потери ответа. В ТЗ не полностью описано, как распознать повтор и выполнить финансовую операцию один раз.",
            "question": "Как система определяет, что это повтор исходной операции?",
            "recommendation": "Укажите, какой идентификатор используется при повторе, как исключается двойное списание и какой ответ возвращается.",
            "acceptance_test": "Первый запрос выполнен, но ответ потерян. Повторите ту же операцию и убедитесь, что списание произошло один раз."
        },
        "acceptance_gap": {
            "title": "Не хватает критериев приёмки",
            "description": "",
            "question": "По какому наблюдаемому результату можно подтвердить выполнение требования?",
            "recommendation": "Опишите исходные условия, действие и результат, который можно проверить.",
            "acceptance_test": ""
        },
        "semantic_conflict": {
            "title": "Возможное противоречие",
            "description": "",
            "question": "Какое поведение ожидается при указанных условиях?",
            "recommendation": "Уточните, какое требование действует, и опишите условия, при которых оно меняется.",
            "acceptance_test": ""
        },
        "missing_scenario": {
            "title": "Возможно пропущен сценарий",
            "description": "",
            "question": "Что система должна сделать в этом сценарии?",
            "recommendation": "Укажите, когда возникает сценарий, что делает система и какой результат видит пользователь.",
            "acceptance_test": ""
        }
    }
}
