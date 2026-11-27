import assert from "node:assert/strict";
import test from "node:test";
import { localImageName, wordImageReferences } from "../public/document-view.js";

test("only explicitly loaded local raster references are embedded in Word", () => {
  assert.equal(localImageName("./assets/Step%20one.png"), "Step one.png");
  assert.equal(localImageName("https://example.test/Step%20one.png"), null);
  assert.equal(localImageName("//example.test/Step%20one.png"), null);
  assert.equal(localImageName("invalid%name.png"), null);
  const text = [
    '![A](<assets/Step one.png> "Step one")',
    "![B](assets/Step%20one.png)",
    "![Remote](https://example.test/Step%20one.png)",
    "![Missing](assets/gap.jpg)",
    "```markdown",
    "![Example](assets/Step%20one.png)",
    "```",
  ].join("\n");
  const result = wordImageReferences(text, [{ id: "fig-1", name: "Step one.png" }]);
  assert.equal(result, text.replace(/^.*\n.*\n/, "![A](attachment:fig-1)\n![B](attachment:fig-1)\n"));
});
