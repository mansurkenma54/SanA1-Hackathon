import assert from "node:assert/strict";
import { test } from "node:test";
import { clearWorkspaceSession, readWorkspaceSession, recoverableAudit, writeWorkspaceSession } from "../public/workspace-session.js";

function storage(limit = Number.MAX_SAFE_INTEGER) {
  const values = new Map();
  return {
    getItem: key => values.get(key),
    setItem(key, data) {
      if (data.length > limit) throw new DOMException("Exceeded", "QuotaExceededError");
      values.set(key, data);
    },
    removeItem: key => values.delete(key),
    corrupt(data) { values.set(values.keys().next().value, data); },
  };
}

test("the tab snapshot keeps an audit and both pending changes until explicitly cleared", () => {
  const tab = storage();
  assert.equal(readWorkspaceSession(tab), null);
  const snapshot = { text: "Лимит 7000\nЛимит 5000", audit: { edits: [["Д-01", [
    { patch: { start: 6, end: 10, before: "7000", after: "9000" }, answer: "Лимит 9000" },
    { patch: { start: 17, end: 21, before: "5000", after: "9000" }, answer: "Лимит 9000" },
  ]]] } };
  assert.equal(writeWorkspaceSession(tab, snapshot), "sessionSaved");
  assert.deepEqual(readWorkspaceSession(tab), { ...snapshot, version: 1 });
  clearWorkspaceSession(tab);
  assert.equal(readWorkspaceSession(tab), null);
});

test("quota fallback keeps the most recent draft and describes what fit", () => {
  const compact = storage(150);
  assert.equal(writeWorkspaceSession(compact, { text: "Черновик", audit: { mode: "rules" },
    media: [{ src: "x".repeat(200) }] }), "sessionTextOnly");
  assert.deepEqual(readWorkspaceSession(compact).audit, { mode: "rules" });
  assert.equal(writeWorkspaceSession(compact, { text: "Новая версия", audit: { markdown: "a".repeat(200) } }), "sessionDraftOnly");
  assert.deepEqual(readWorkspaceSession(compact), { version: 1, text: "Новая версия" });
  assert.equal(writeWorkspaceSession(compact, { text: "x".repeat(200) }), "sessionUnavailable");
  assert.equal(readWorkspaceSession(compact), null);
});

test("malformed or disabled storage cannot recover an invalid report", () => {
  const tab = storage();
  writeWorkspaceSession(tab, { text: "ТЗ" });
  tab.corrupt("{invalid-json");
  assert.equal(readWorkspaceSession(tab), null);
  assert.equal(readWorkspaceSession(null), null);
  assert.equal(recoverableAudit({ schema_version: 1, mode: "rules", findings: [null] }), false);
});
