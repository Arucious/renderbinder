import { comparePromptText } from "./promptDiff";

self.onmessage = (event: MessageEvent<{ before: string; after: string }>) => {
  try {
    self.postMessage({
      result: comparePromptText(event.data.before, event.data.after),
    });
  } catch {
    self.postMessage({
      error:
        "The prompt comparison could not be calculated. Close this dialog and try again.",
    });
  }
};
