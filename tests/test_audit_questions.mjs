import assert from "node:assert/strict";
import test from "node:test";
import { formatAuditQuestions } from "../public/audit-view.js";

test("formats a compact author question sheet with traceable findings and blank answers", () => {
  const result = formatAuditQuestions([{
    id: "Д-01", priority: "Блокирующий", question: "Какой лимит применяется?", requirements: ["REQ-001", "REQ-007"],
    evidence: [{ location: "L8", quote: "Текст первого пункта" }, { location: "L8", quote: "Другая цитата" },
      { location: "стр. 2 · L35", quote: "Текст второго пункта" }],
    explanation: "Внутреннее пояснение", answer: "Сохранённый ответ",
  }, {
    id: "Д-02", priority: "Существенный", question: "Что происходит при повторе?", requirements: [], evidence: [],
  }]);
  assert.equal(result, [
    "Вопросы автору ТЗ", "",
    "Д-01 · Блокирующий", "Требования — REQ-001, REQ-007", "Места в ТЗ — L8, стр. 2 · L35",
    "Какой лимит применяется?", "Ответ — ____________________", "",
    "Д-02 · Существенный", "Что происходит при повторе?", "Ответ — ____________________", "",
  ].join("\n"));
});

test("no matching findings produce no question sheet", () => {
  assert.equal(formatAuditQuestions([]), "");
});
