import { useEffect, useState } from "react";
import { GitCompareArrows, LoaderCircle, Settings2 } from "lucide-react";
import {
  api,
  media,
  similarResource,
  scopeLabel,
  type ImageItem,
  type SimilarPrompts as Results,
} from "./api";

export function SimilarPrompts({
  source,
  onCompare,
  onSettings,
}: {
  source: ImageItem;
  onCompare: (item: ImageItem) => void;
  onSettings: () => void;
}) {
  const [mode, setMode] = useState("hybrid");
  const [result, setResult] = useState<Results | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setLoading(true);
    setError("");
    setResult(null);
    api<Results>(
      `${similarResource(source)}?mode=${mode}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        setResult(value);
        setLoading(false);
        if (
          ["queued", "loading", "indexing", "idle"].includes(
            value.semantic.state,
          )
        )
          timer = setTimeout(() => setRevision((n) => n + 1), 2500);
      })
      .catch((e) => {
        if (!controller.signal.aborted) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [source.id, source.prompt_id, mode, revision]);
  return (
    <div className="similar-prompts-body">
      <p className="similar-source">{source.positive}</p>
      {source.scope && source.scope !== "positive" && (
        <p className="prompt-scope-label">
          {scopeLabel(source.scope)} · Matching the same prompt type across
          sources.
        </p>
      )}
      <div className="similar-toolbar">
        <label>
          Match by
          <select
            aria-label="Match by"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="hybrid">Meaning & text</option>
            <option value="semantic">Meaning</option>
            <option value="text">Text</option>
          </select>
        </label>
        <button className="text-button" onClick={onSettings}>
          <Settings2 size={14} />
          Model settings
        </button>
      </div>
      {result && (
        <>
          <p className="muted small-text">
            {result.method === "text"
              ? "Ranked by text similarity."
              : result.method === "semantic"
                ? "Ranked by semantic similarity."
                : "Ranked by semantic and text similarity."}{" "}
            Scores rank relatedness; they are not percentages of identical text.
            Results cover all sources.
          </p>
          {mode !== "text" && result.method === "text" && (
            <div className="notice">
              {result.semantic.state === "disabled"
                ? "Enable a model in Settings for semantic matches."
                : result.semantic.state === "error"
                  ? "The semantic model needs attention in Settings. Text matches are available."
                  : result.semantic.state === "paused"
                    ? "Semantic indexing is paused. Text matches are available."
                    : "Semantic embeddings are being prepared. Text matches are available now."}
            </div>
          )}
          <p className="similar-count">
            {result.total} related {result.total === 1 ? "prompt" : "prompts"}{" "}
            across {result.compared} other unique prompts
            {result.total > result.items.length
              ? ` · showing top ${result.items.length}`
              : ""}
          </p>
          {result.source_sampled && (
            <p className="notice">
              Text scoring sampled this unusually long prompt. Semantic chunking
              reads the complete prompt.
            </p>
          )}
        </>
      )}
      {loading && !result && (
        <p className="prompt-load-status" role="status">
          <LoaderCircle size={14} className="spin" />
          Finding similar prompts…
        </p>
      )}
      {error && (
        <div className="notice warning" role="alert">
          {error}
          <button
            className="text-button"
            onClick={() => setRevision((n) => n + 1)}
          >
            Retry
          </button>
        </div>
      )}
      <div className="similar-results">
        {result?.items.map((item) => (
          <article
            key={item.positive_hash || item.id}
            className="similar-result"
          >
            <img
              src={media(item.id)}
              alt="Example using this prompt"
              loading="lazy"
            />
            <div>
              <div className="similar-result-heading">
                <strong>
                  {item.scope && item.scope !== "positive"
                    ? `${scopeLabel(item.scope)} · `
                    : ""}
                  {item.image_count || 1}{" "}
                  {(item.image_count || 1) === 1 ? "image" : "images"}
                </strong>
                <span>Score {item.similarity.toFixed(2)}</span>
              </div>
              <p>{item.positive}</p>
              <div className="similar-result-tools">
                <small>
                  Text {item.text_similarity.toFixed(2)}
                  {item.semantic_similarity !== null
                    ? ` · Meaning ${item.semantic_similarity.toFixed(2)}`
                    : ""}
                  {item.sampled ? " · Text sampled" : ""}
                </small>
                <button
                  className="button secondary"
                  onClick={() => onCompare(item)}
                >
                  <GitCompareArrows size={14} />
                  Compare variation
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>
      {result && !result.items.length && (
        <p className="similar-empty">
          {mode === "semantic" && result.method === "text"
            ? "Semantic matches will appear when the selected model finishes indexing."
            : "No close matches found. Try a different matching mode or model."}
        </p>
      )}
    </div>
  );
}
