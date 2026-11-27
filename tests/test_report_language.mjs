import assert from "node:assert/strict";
import test from "node:test";
import { literalReportText, reportTarget } from "../public/report-language.js";

test("report defaults to source language and delegates an undetermined language", () => {
  assert.equal(reportTarget("source", "", "kk"), "kk");
  assert.equal(reportTarget("source", "", "und"), "auto");
  assert.equal(reportTarget("source", "", undefined), "auto");
  assert.equal(reportTarget("en", "", "ru"), "en");
  assert.equal(reportTarget("other", "  Deutsch  ", "en"), "Deutsch");
});

test("displays original quote punctuation and HTML metacharacters as text", () => {
  assert.equal(literalReportText("L2 — \\*\\*GET\\*\\* \\| &lt;name&gt; &amp; tag\\_id"),
    "L2 — **GET** | <name> & tag_id");
});
