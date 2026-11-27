import assert from "node:assert/strict";
import test from "node:test";
import { compareAudits } from "../public/audit-compare.js";
import { evidenceSelection } from "../public/audit-view.js";

function finding(id, quotes, question = "Какой срок применяется?") {
  return { id, criterion: "Непротиворечивость", question,
    evidence: quotes.map((quote, index) => ({ quote, line: 2 + index })) };
}

test("matches a finding after renumbering and reordering of its evidence", () => {
  const oldFinding = finding("Д-03", ["В течение 10 секунд.", "До 30 секунд."]);
  const newFinding = finding("Д-01", ["До 30 секунд.", "В течение  10 секунд."]);
  const result = compareAudits({ sha256: "a", findings: [oldFinding] },
    { sha256: "b", findings: [newFinding] });
  assert.deepEqual(result, { before_sha256: "a", after_sha256: "b",
    repeated: [{ before_id: "Д-03", after_id: "Д-01" }], needs_review: [], unmatched_after: [] });
});

test("keeps different questions against the same evidence separate", () => {
  const quotes = ["Лимит 10 секунд в рабочий день."];
  const oldFinding = finding("Д-01", quotes);
  const newFinding = finding("Д-01", quotes, "Как определяется рабочий день?");
  const result = compareAudits({ findings: [oldFinding] }, { findings: [newFinding] });
  assert.deepEqual(result.repeated, []);
  assert.deepEqual(result.needs_review, [oldFinding]);
  assert.deepEqual(result.unmatched_after, ["Д-01"]);
});

test("routes ambiguous duplicates to manual review", () => {
  const first = finding("Д-01", ["Применяется срок 10 секунд."]);
  const second = { ...first, id: "Д-02" };
  const result = compareAudits({ findings: [first, second] }, { findings: [first] });
  assert.deepEqual(result.repeated, []);
  assert.deepEqual(result.needs_review, [first, second]);
  assert.deepEqual(result.unmatched_after, ["Д-01"]);
});

test("does not match identical quotations from different clauses or sections", () => {
  const oldFinding = finding("Д-01", ["Отправить уведомление."]);
  const origin = { ...oldFinding.evidence[0], source_id: "Ф-2", section: "Перевод" };
  const before = { findings: [{ ...oldFinding, evidence: [origin] }] };
  for (const changed of [{ section: "Возврат" }, { source_id: "Ф-3" }]) {
    const after = { findings: [{ ...oldFinding, evidence: [{ ...origin, ...changed }] }] };
    const result = compareAudits(before, after);
    assert.deepEqual(result.repeated, []);
    assert.deepEqual(result.needs_review, before.findings);
  }
  const moved = { findings: [{ ...oldFinding, evidence: [{ ...origin, line: 42 }] }] };
  assert.deepEqual(compareAudits(before, moved).repeated, [{ before_id: "Д-01", after_id: "Д-01" }]);
});

test("retains evidence of a prior finding even when the new audit is clean", () => {
  const previous = finding("Д-01", ["Нужно отправить после 30 секунд."]);
  const result = compareAudits({ sha256: "before", findings: [previous] }, { sha256: "after", findings: [] });
  assert.deepEqual(result.needs_review, [previous]);
  assert.deepEqual(result.unmatched_after, []);
});

test("selects the cited occurrence of a repeated quotation", () => {
  const quote = "Порог 10 ₸.";
  const text = ["🧾 " + quote, "", "Правило: " + quote].join("\n");
  const start = text.lastIndexOf(quote);
  assert.deepEqual(evidenceSelection(text, { line: 3, end: 3, quote }), [start, start + quote.length]);
  assert.equal(evidenceSelection(text, { line: 2, end: 2, quote }), null);
});

test("uses a unique quotation when extraction shifted its line number", () => {
  const text = "\n\nУсловие\nдля операции";
  const quote = "Условие\nдля операции";
  assert.deepEqual(evidenceSelection(text, { line: 1, end: 2, quote }), [2, text.length]);
});
