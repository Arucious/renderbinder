export type Prompt = {
  node_id: string;
  class_type: string;
  title: string;
  input: string;
  text: string;
  role: string;
  used: boolean | null;
  confidence: string;
};
export type Metadata = {
  positive: string;
  negative: string;
  negative_status?: {
    state: "present" | "empty" | "zeroed" | "empty_and_zeroed" | "unavailable";
    branches: {
      stage_node_id: string;
      state: string;
      sources: {
        node_id: string;
        class_type: string;
        input?: string;
        state: string;
      }[];
    }[];
  };
  prompts: Prompt[];
  stages: {
    node_id: string;
    class_type: string;
    settings: Record<string, unknown>;
    positive_nodes: string[];
    negative_nodes: string[];
  }[];
  models: string[];
  loras: {
    name: string;
    strength_model: number | null;
    strength_clip: number | null;
    node_id: string;
  }[];
  vaes: string[];
  text_encoders: string[];
  settings: Record<string, (string | number)[]>;
  sources: Record<string, string[]>;
  additional_parameters: Record<string, unknown>;
  confidence: string;
  warnings: string[];
  prompt: Record<string, unknown> | null;
  workflow: Record<string, unknown> | null;
  raw: Record<string, unknown>;
  schema_version?: number;
  metadata_sources?: { role: string; path?: string; reader?: string }[];
  parsers?: { id: string; version: number }[];
};
export type ImageItem = {
  id: string;
  filename: string;
  folder: string;
  root: string;
  width: number;
  height: number;
  size: number;
  model: string | null;
  loras: string[];
  seeds: string[];
  positive: string;
  negative: string;
  sort_date: number;
  generated_at: number | null;
  confidence: string;
  workflow_hash: string | null;
  configuration_hash: string | null;
  positive_hash: string | null;
  image_count?: number;
  favorite: boolean;
  tags: string[];
  media_kind?: "image" | "video";
  duration?: number | null;
  fps?: number | null;
  technical?: Record<string, string | number | boolean | null>;
  prompt_id?: string;
  scope?: string;
  label?: string;
  start?: number | null;
  end?: number | null;
  text_hash?: string;
  shot_count?: number;
};
export type PromptDocument = {
  prompt_id: string;
  positive_hash: string;
  text_hash: string;
  scope: string;
  label: string;
  positive: string;
  text: string;
  start: number | null;
  end: number | null;
  provenance: Record<string, unknown>;
};
export type ImageDetail = ImageItem & {
  path: string;
  created_at: number;
  modified_at: number;
  metadata: Metadata;
  collections: string[];
  raw_json: string;
  prompt_documents: PromptDocument[];
};
export type PromptText = {
  id: string;
  positive_hash: string | null;
  positive: string;
};
export type SimilarPrompt = ImageItem & {
  similarity: number;
  text_similarity: number;
  semantic_similarity: number | null;
  sampled: boolean;
};
export type SimilarPrompts = {
  items: SimilarPrompt[];
  total: number;
  compared: number;
  minimum: number;
  source_sampled: boolean;
  method: string;
  semantic: SemanticStatus;
};
export type SemanticConfig = {
  enabled: boolean;
  model: string;
  custom_model: string;
  revision: string;
  backend: "torch";
  prefix: string;
  max_tokens: number;
  threads: number;
};
export type SemanticStatus = {
  config: SemanticConfig;
  state: string;
  completed: number;
  total: number;
  error: string;
  available: boolean;
  install_command: string;
  model_key: string | null;
  presets: Record<string, { name: string; description: string }>;
};
export type Facet = { name: string; count: number };
export type Facets = {
  total: number;
  unique_prompts: number;
  favorites: number;
  models: Facet[];
  loras: Facet[];
  folders: Facet[];
  roots: Facet[];
  tags: Facet[];
  collections: { id: string; name: string; count: number }[];
};
export type Settings = {
  roots: string[];
  comfy_url: string;
  data_dir: string;
  extensions: string[];
};
export type Status = {
  running: boolean;
  scanned: number;
  indexed: number;
  unchanged: number;
  removed: number;
  errors: string[];
  error_count: number;
  current: string;
  cancelled: boolean;
  watching: boolean;
  started_at: number | null;
  finished_at: number | null;
  pending: number;
  revision: number;
};
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method,
    signal,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    const detail = data.detail;
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  return response.json();
}
export const baseName = (path: string) =>
  path.split(/[\\/]/).filter(Boolean).pop() || path;
export const dateLabel = (n: number) =>
  new Date(n * 1000).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
export const bytes = (n: number) =>
  n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.round(n / 1024) + " KB";
export const media = (id: string, kind = "thumbnail") =>
  `/api/images/${id}/${kind}`;
export const promptResource = (item: ImageItem) =>
  item.prompt_id && item.scope !== "positive"
    ? `/prompts/${item.prompt_id}`
    : `/images/${item.id}/prompt`;
export const similarResource = (item: ImageItem) =>
  item.prompt_id && item.scope !== "positive"
    ? `/prompts/${item.prompt_id}/similar-prompts`
    : `/images/${item.id}/similar-prompts`;
export const scopeLabel = (scope?: string) =>
  scope === "global"
    ? "Global prompt"
    : scope === "shot"
      ? "Shot prompt"
      : "Positive prompt";
export const timeLabel = (value?: number | null) =>
  value === null || value === undefined
    ? ""
    : `${Math.floor(value / 60)}:${(value % 60).toFixed(1).padStart(4, "0")}`;
