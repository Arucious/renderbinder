import assert from "node:assert/strict";
import test from "node:test";
import { comparePromptText, type PromptDiff } from "../src/promptDiff.ts";

const textFor = (result: PromptDiff, side: "before" | "after") =>
  result.parts
    .filter((part) => part.kind !== (side === "before" ? "added" : "removed"))
    .map((part) => part.value)
    .join("");

test("replacement highlights the changed words and preserves both original texts", () => {
  const before = "A cabin in warm sunlight, photographed on film.";
  const after = "A cabin in cool moonlight, photographed on film.";
  const result = comparePromptText(before, after);
  assert.equal(textFor(result, "before"), before);
  assert.equal(textFor(result, "after"), after);
  for (const word of ["warm", "sunlight"])
    assert.ok(
      result.parts.some(
        (part) => part.kind === "removed" && part.value.includes(word),
      ),
    );
  for (const word of ["cool", "moonlight"])
    assert.ok(
      result.parts.some(
        (part) => part.kind === "added" && part.value.includes(word),
      ),
    );
  assert.equal(result.identical, false);
  assert.equal(result.simplified, false);
});

test("insertion and deletion keep direction and character counts", () => {
  const added = comparePromptText("a cabin", "a red cabin");
  assert.equal(added.addedCharacters, 4);
  assert.equal(added.removedCharacters, 0);
  const removed = comparePromptText("a red cabin", "a cabin");
  assert.equal(removed.removedCharacters, 4);
  assert.equal(removed.addedCharacters, 0);
});

test("identical and empty prompts are handled explicitly", () => {
  assert.ok(comparePromptText("same", "same").identical);
  assert.ok(comparePromptText("", "").identical);
  assert.equal(textFor(comparePromptText("", "a cabin"), "after"), "a cabin");
  assert.equal(textFor(comparePromptText("a cabin", ""), "before"), "a cabin");
});

test("whitespace and line endings are preserved and identified as changes", () => {
  const before = "a  cabin\r\nin snow\n";
  const after = "a cabin\nin snow";
  const result = comparePromptText(before, after);
  assert.ok(result.whitespaceOnly);
  assert.equal(textFor(result, "before"), before);
  assert.equal(textFor(result, "after"), after);
  assert.ok(result.removedCharacters > 0);
});

test("unicode, emoji, punctuation, and prompt weights remain exact", () => {
  const before = "森の小屋 🌙 (snow:1.2), café";
  const after = "森の小屋 ☀️ (snow:1.4); café";
  const result = comparePromptText(before, after);
  assert.equal(textFor(result, "before"), before);
  assert.equal(textFor(result, "after"), after);
  assert.ok(result.addedCharacters > 0 && result.removedCharacters > 0);
  assert.equal(comparePromptText("", "🌙").addedCharacters, 1);
});

test("comparison includes differences beyond the gallery preview limit", () => {
  const prefix = "A detailed photographic scene. ".repeat(60);
  const result = comparePromptText(prefix + "blue scarf", prefix + "red scarf");
  assert.ok(
    result.parts.some(
      (part) => part.kind === "removed" && part.value.includes("blue"),
    ),
  );
  assert.ok(
    result.parts.some(
      (part) => part.kind === "added" && part.value.includes("red"),
    ),
  );
});

test("bounded fallback preserves full text for large or unrelated inputs", () => {
  for (const limits of [{ maxEditLength: 0 }, { maxLength: 1 }]) {
    const result = comparePromptText("a cabin", "a city", limits);
    assert.ok(result.simplified);
    assert.equal(textFor(result, "before"), "a cabin");
    assert.equal(textFor(result, "after"), "a city");
  }
});

test("embedded markup stays literal text", () => {
  const result = comparePromptText(
    '<script>alert("x")</script>',
    '<script>alert("y")</script>',
  );
  assert.equal(textFor(result, "before"), '<script>alert("x")</script>');
  assert.equal(textFor(result, "after"), '<script>alert("y")</script>');
});
