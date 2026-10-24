import { useEffect, useState, type FormEvent } from "react";
import { LoaderCircle, RefreshCw } from "lucide-react";
import { api, type SemanticConfig, type SemanticStatus } from "./api";

export function SemanticSettings() {
  const [status, setStatus] = useState<SemanticStatus | null>(null);
  const [config, setConfig] = useState<SemanticConfig | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await api<SemanticStatus>(
          "/semantic",
          "GET",
          undefined,
          controller.signal,
        );
        setStatus(value);
        setConfig((previous) => previous || value.config);
      } catch (e) {
        if (!controller.signal.aborted) setError((e as Error).message);
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 2000);
    };
    poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  const update = (value: Partial<SemanticConfig>) =>
    setConfig((previous) => previous && { ...previous, ...value });
  const save = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      setStatus(await api<SemanticStatus>("/semantic/settings", "PUT", config));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const busy =
    status && ["queued", "loading", "indexing"].includes(status.state);
  return (
    <section className="semantic-settings settings-maintenance">
      <h3>Prompt similarity</h3>
      <p>
        Find related prompts by meaning. Embeddings are computed on CPU and
        cached per unique prompt and model. Text matching works without a model.
      </p>
      {status && config ? (
        <form className="semantic-form" onSubmit={save}>
          <label className="semantic-toggle">
            <input
              type="checkbox"
              checked={config.enabled}
              onChange={(e) => update({ enabled: e.target.checked })}
            />{" "}
            Enable semantic matching
          </label>
          <label>
            Embedding model
            <select
              aria-label="Embedding model"
              value={config.model}
              onChange={(e) => update({ model: e.target.value })}
            >
              {Object.entries(status.presets).map(([id, preset]) => (
                <option value={id} key={id}>
                  {preset.name}
                </option>
              ))}
              <option value="custom">Custom model</option>
            </select>
          </label>
          {config.model !== "custom" ? (
            <p className="muted small-text">
              {status.presets[config.model]?.description}
            </p>
          ) : (
            <>
              <label>
                Model folder or Hugging Face ID
                <input
                  value={config.custom_model}
                  onChange={(e) => update({ custom_model: e.target.value })}
                  placeholder={"C:\\Models\\my-embedding-model or owner/model"}
                  spellCheck={false}
                />
              </label>
              <p className="muted small-text">
                Sentence Transformers compatible text encoders with safetensors
                weights and a fast tokenizer. GGUF files and models requiring
                custom Python code are unsupported. Resource use depends on the
                model you choose.
              </p>
              <label>
                Text prefix
                <input
                  value={config.prefix}
                  onChange={(e) => update({ prefix: e.target.value })}
                  placeholder="Optional, for example query: "
                  spellCheck={false}
                />
                <span>
                  Applied equally to every prompt. Use the model author's
                  similarity instructions.
                </span>
              </label>
              <label>
                Tokens per chunk
                <input
                  type="number"
                  min={128}
                  max={8192}
                  value={config.max_tokens}
                  onChange={(e) =>
                    update({ max_tokens: Number(e.target.value) })
                  }
                />
              </label>
            </>
          )}
          <div className="semantic-fields">
            <label>
              Model revision
              <input
                value={config.revision}
                onChange={(e) => update({ revision: e.target.value })}
                placeholder="main"
                spellCheck={false}
              />
              <span>
                Hugging Face branch, tag, or commit. Ignored for local folders.
              </span>
            </label>
            <label>
              CPU threads
              <input
                type="number"
                min={1}
                max={8}
                value={config.threads}
                onChange={(e) => update({ threads: Number(e.target.value) })}
              />
            </label>
          </div>
          <p className="muted small-text">
            Saving with matching enabled downloads missing model files, then
            builds embeddings in the background. After setup, matching runs
            locally. Long prompts use overlapping chunks. Switching models keeps
            previous caches.
          </p>
          {!status.available && (
            <div className="notice warning">
              <p>
                Install the optional semantic dependencies, then restart the
                gallery:
              </p>
              <code>{status.install_command}</code>
            </div>
          )}
          <div className="semantic-progress" role="status">
            {busy && <LoaderCircle size={14} className="spin" />}
            <span>
              {status.state === "ready"
                ? `${status.presets[status.config.model]?.name || "Custom model"} · Ready · ${status.completed.toLocaleString()} prompts cached`
                : status.state === "indexing"
                  ? `Embedding prompts · ${status.completed.toLocaleString()} / ${status.total.toLocaleString()}`
                  : status.state === "loading"
                    ? "Loading model files. The first download can take several minutes."
                    : status.state === "disabled"
                      ? "Semantic matching is off. Text matching remains available."
                      : status.state === "paused"
                        ? "Embedding indexing paused. Completed prompts remain cached."
                        : status.state === "error"
                          ? "Semantic model could not be loaded or indexed."
                          : "Waiting to build embeddings."}
            </span>
          </div>
          {(error || status.error) && (
            <div className="notice warning" role="alert">
              {error || status.error}
            </div>
          )}
          <div className="maintenance-actions">
            <button
              className="button secondary"
              type="submit"
              disabled={saving || (config.enabled && !status.available)}
            >
              <RefreshCw size={14} />
              {saving
                ? "Saving…"
                : config.enabled
                  ? "Save model & build embeddings"
                  : "Save similarity settings"}
            </button>
            {busy && (
              <button
                type="button"
                className="text-button"
                onClick={async () => {
                  try {
                    setStatus(
                      await api<SemanticStatus>("/semantic/cancel", "POST"),
                    );
                  } catch (e) {
                    setError((e as Error).message);
                  }
                }}
              >
                Pause indexing
              </button>
            )}
          </div>
          {busy && (
            <p className="muted small-text">
              Pausing takes effect after the current download or text chunk
              finishes.
            </p>
          )}
        </form>
      ) : (
        <p role="status">{error || "Loading similarity settings…"}</p>
      )}
    </section>
  );
}
