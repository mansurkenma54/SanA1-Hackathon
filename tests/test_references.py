import unittest

from analyzer import analyze


def unresolved(text):
    return [item["values"]["targets"] for item in analyze(text)["findings"]
            if item["code"] == "broken_reference"]


class LocalReferenceTests(unittest.TestCase):
    def test_grouped_english_targets_include_only_undeclared_clauses(self):
        text = ("§1.1 Use the recovery sequence in §5.2, §2.1, and §5.4.\n"
                "| §2.1 | Close the session and record the time. |")
        self.assertEqual(unresolved(text), [["§5.2", "§5.4"]])

    def test_multiple_russian_targets_in_same_clause(self):
        text = "§3.3 Список адресатов указан в пунктах §7.4 и §7.5. Для смены см. §9.1."
        self.assertEqual(unresolved(text), [["§7.4", "§7.5", "§9.1"]])

    def test_external_sources_do_not_contaminate_independent_clauses(self):
        text = ("§1.1 The policy is defined in §2.1 of the user manual; for local handling see §8.4.\n"
                "§1.2 См. §7.4 ГОСТ 34.602-2020.\n"
                "§1.3 ISO 9001 specifies the procedure in §7.4.\n"
                "§1.4 Для договора см. §7.4 и §7.5.\n"
                "§1.5 For the attachment see §7.4 of supplier.pdf.\n"
                "§1.6 The interface is described in §7.4 of the supplier specification.\n"
                "§1.7 Срок указан в пункте §7.4 внешней спецификации.")
        self.assertEqual(unresolved(text), [["§8.4"]])

    def test_ids_and_inline_numbers_are_not_declarations_or_implicit_links(self):
        text = "FIN-1 The ceiling is 5.2 units; see FIN-2.\nFIN-2 Record the posted quantity of 7.4."
        self.assertEqual(unresolved(text), [])

    def test_cyrillic_refs_resolve_marked_source_ids(self):
        text = (
            "* **Ф-1.** Способ расчёта описан в приложении.\n"
            "## §3.1 Срок проверки\n"
            "Ф-2. См. пункт **Ф–1**, §3.1 и Ф-9."
        )
        self.assertEqual(unresolved(text), [["Ф-9"]])
