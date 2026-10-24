import { diffWordsWithSpace } from "diff";

export type DiffPart = { value: string; kind: "same" | "added" | "removed" };
export type PromptDiff = {
  parts: DiffPart[];
  addedCharacters: number;
  removedCharacters: number;
  identical: boolean;
  whitespaceOnly: boolean;
  simplified: boolean;
};

function characterCount(value: string): number {
  let count = 0;
  for (const _character of value) count++;
  return count;
}

export function comparePromptText(
  before: string,
  after: string,
  limits: { timeout?: number; maxEditLength?: number; maxLength?: number } = {},
): PromptDiff {
  if (before === after) {
    return {
      parts: [{ value: before, kind: "same" }],
      addedCharacters: 0,
      removedCharacters: 0,
      identical: true,
      whitespaceOnly: false,
      simplified: false,
    };
  }
  const changes =
    before.length + after.length <= (limits.maxLength ?? 500_000)
      ? diffWordsWithSpace(before, after, {
          timeout: limits.timeout ?? 1500,
          maxEditLength: limits.maxEditLength ?? 4000,
        })
      : undefined;
  const parts: DiffPart[] = changes
    ? changes.map((change) => ({
        value: change.value,
        kind: change.added ? "added" : change.removed ? "removed" : "same",
      }))
    : [
        ...(before ? [{ value: before, kind: "removed" as const }] : []),
        ...(after ? [{ value: after, kind: "added" as const }] : []),
      ];
  return {
    parts,
    addedCharacters: parts.reduce(
      (total, part) =>
        total + (part.kind === "added" ? characterCount(part.value) : 0),
      0,
    ),
    removedCharacters: parts.reduce(
      (total, part) =>
        total + (part.kind === "removed" ? characterCount(part.value) : 0),
      0,
    ),
    identical: false,
    whitespaceOnly: before.replace(/\s/gu, "") === after.replace(/\s/gu, ""),
    simplified: !changes,
  };
}
