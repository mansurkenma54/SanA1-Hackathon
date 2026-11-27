import assert from "node:assert/strict";
import test from "node:test";
import { applyRevisionPatches, preferredRevisionPart, revisionParts, revisionPatch } from "../public/audit-repair.js";

const source = (line, quote) => ({ line, end: line, quote });

test("updates one acceptance cell and keeps the other cells and separators intact", () => {
  const row = "| Покупка 31 марта | Провести 1 апреля | Апрельский счётчик |";
  const text = "# ТЗ\n\n" + row;
  const parts = revisionParts(text, source(3, row));
  assert.deepEqual(parts.map(part => part.cell), [1, 2, 3]);
  const patch = revisionPatch(text, parts[2], "Мартовский счётчик");
  assert.equal(applyRevisionPatches(text, [patch], 50000), text.replace("Апрельский", "Мартовский"));
  const literal = revisionPatch(text, parts[2], "Март | факт");
  assert.match(applyRevisionPatches(text, [literal], 50000), /Март \\\| факт/);
  assert.throws(() => revisionPatch(text, parts[2], "Две\nстроки"), /cell/);
});

test("preserves a source ID when two pending changes are applied together", () => {
  const row = "* **Ф-1.** Отображать статус быстро.";
  const method = "HTTP method: GET";
  const text = row + "\n\n" + method;
  const [clause] = revisionParts(text, source(1, row));
  const [api] = revisionParts(text, source(3, method));
  const patches = [revisionPatch(text, clause, "Отображать статус за 2 секунды."), revisionPatch(text, api, "HTTP method: PATCH")];
  assert.equal(applyRevisionPatches(text, patches, 50000),
    "* **Ф-1.** Отображать статус за 2 секунды.\n\nHTTP method: PATCH");
  assert.throws(() => applyRevisionPatches(text, [patches[0], patches[0]], 50000), /overlap/);
  assert.throws(() => applyRevisionPatches(text.replace("быстро", "сразу"), patches, 50000), /overlap/);
  assert.throws(() => applyRevisionPatches(text, patches, 8), /length/);
});

test("retains image references and inserts a new condition as a separate paragraph", () => {
  const paragraph = "Ф-2. Сверить данные ![Схема](attachment:fig-1).";
  const text = paragraph + "\n\nФ-3. Сохранить результат.";
  const [part] = revisionParts(text, source(1, paragraph));
  assert.throws(() => revisionPatch(text, part, "Сохранить данные."), /attachments/);
  assert.deepEqual(revisionParts("Тот же текст\n\nТот же текст", source(2, "Тот же текст")), []);
  assert.equal(applyRevisionPatches(text, [revisionPatch(text, part, "При ошибке вернуть исходное состояние.", true)], 50000),
    paragraph + "\n\nПри ошибке вернуть исходное состояние.\n\nФ-3. Сохранить результат.");
});

test("defaults a transfer limit contradiction to the amount cell and preserves both IDs when harmonizing", () => {
  const row = "| §2.1 | Максимальная сумма на один перевод | 100 000 ₸ |";
  const clause = "§4.3  Лимит на один перевод составляет 50 000 ₸.";
  const text = row + "\n\n" + clause;
  const evidence = [source(1, row), source(3, clause)];
  const parts = evidence.flatMap(ref => revisionParts(text, ref).map(part => ({ ...part, source: ref })));
  const item = { criterion: "Непротиворечивость", question: "Какой лимит действует при этих условиях?", evidence };
  const selected = parts[preferredRevisionPart(parts, item)];
  assert.equal(selected.cell, 3);
  assert.equal(selected.before, "100 000 ₸");
  const patches = [revisionPatch(text, selected, "75 000 ₸"),
    revisionPatch(text, parts.at(-1), "Лимит на один перевод составляет 75 000 ₸.")];
  assert.equal(applyRevisionPatches(text, patches, 50000),
    "| §2.1 | Максимальная сумма на один перевод | 75 000 ₸ |\n\n§4.3  Лимит на один перевод составляет 75 000 ₸.");
});

test("rejects out-of-bounds spans even when they describe empty text", () => {
  const text = "Trade limit is 10 KZT.";
  assert.throws(() => applyRevisionPatches(text, [{ start: -1, end: -1, before: "", after: "x" }], 50000), /overlap/);
  assert.throws(() => applyRevisionPatches(text, [{ start: 25, end: 25, before: "", after: "x" }], 50000), /overlap/);
  assert.throws(() => applyRevisionPatches(text, [{ start: 5, end: 4, before: "", after: "x" }], 50000), /overlap/);
});
