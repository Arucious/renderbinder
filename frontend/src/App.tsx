import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  ArrowDownUp,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Clipboard,
  Code2,
  Copy,
  Download,
  ExternalLink,
  Folder,
  FolderOpen,
  FolderPlus,
  GitCompareArrows,
  Grid2X2,
  Heart,
  Image as ImageIcon,
  Layers,
  List,
  LoaderCircle,
  Maximize2,
  Plus,
  Play,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Square,
  Tag,
  Trash2,
  Workflow,
  X,
} from "lucide-react";
import {
  api,
  baseName,
  bytes,
  dateLabel,
  media,
  promptResource,
  scopeLabel,
  timeLabel,
  type Facets,
  type ImageDetail,
  type ImageItem,
  type Metadata,
  type PromptText,
  type Settings,
  type Status,
} from "./api";
import type { PromptDiff } from "./promptDiff";
import { SemanticSettings } from "./SemanticSettings";
import { SimilarPrompts } from "./SimilarPrompts";
import { VideoPlayer } from "./VideoPlayer";
import { MetadataFormats } from "./MetadataFormats";

type Filters = {
  q: string;
  exact: boolean;
  favorite: boolean;
  folder: string;
  root: string;
  model: string;
  lora: string;
  seed: string;
  tag: string;
  collection: string;
  after: string;
  before: string;
  workflow: string;
  configuration: string;
  prompt: string;
  media_kind: string;
  prompt_scope: string;
};
const clean: Filters = {
  q: "",
  exact: false,
  favorite: false,
  folder: "",
  root: "",
  model: "",
  lora: "",
  seed: "",
  tag: "",
  collection: "",
  after: "",
  before: "",
  workflow: "",
  configuration: "",
  prompt: "",
  media_kind: "",
  prompt_scope: "",
};
const emptyFacets: Facets = {
  total: 0,
  unique_prompts: 0,
  favorites: 0,
  models: [],
  loras: [],
  folders: [],
  roots: [],
  tags: [],
  collections: [],
};
const pageSize = 60;
const localDate = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const readPref = (key: string, fallback: string) => {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
};
const writePref = (key: string, value: string) => {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Private mode can disable storage. */
  }
};

function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const old = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        closeRef.current();
      }
      if (event.key === "Tab" && ref.current) {
        const els = Array.from(
          ref.current.querySelectorAll<HTMLElement>(
            'button:not(:disabled),a[href],input:not(:disabled),select,textarea,[tabindex="0"]',
          ),
        ).filter((el) => el.offsetParent !== null);
        if (!els.length) {
          event.preventDefault();
          return;
        }
        const first = els[0],
          last = els[els.length - 1];
        if (
          event.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === ref.current)
        ) {
          event.preventDefault();
          last.focus();
        } else if (
          !event.shiftKey &&
          (document.activeElement === last ||
            document.activeElement === ref.current)
        ) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.body.style.overflow = old;
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={ref}
        className={`modal ${wide ? "modal-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
      >
        <div className="modal-heading">
          <h2>{title}</h2>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function App() {
  const [settings, setSettings] = useState<Settings | null>(null),
    [facets, setFacets] = useState(emptyFacets),
    [status, setStatus] = useState<Status | null>(null);
  const [filters, setFilters] = useState<Filters>(clean),
    [search, setSearch] = useState("");
  const [sort, setSort] = useState("date"),
    [direction, setDirection] = useState("desc"),
    [group, setGroup] = useState("");
  const [view, setView] = useState(readPref("view", "grid")),
    [size, setSize] = useState(Number(readPref("size", "230"))),
    [previews, setPreviews] = useState(readPref("previews", "true") === "true");
  const [items, setItems] = useState<ImageItem[]>([]),
    [total, setTotal] = useState(0),
    [imageTotal, setImageTotal] = useState(0),
    [page, setPage] = useState(0),
    [loading, setLoading] = useState(true),
    [reload, setReload] = useState(0),
    [error, setError] = useState("");
  const [showFilters, setShowFilters] = useState(false),
    [showSettings, setShowSettings] = useState(false),
    [sidebar, setSidebar] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set()),
    [selecting, setSelecting] = useState(false),
    [detailId, setDetailId] = useState<string | null>(null),
    [compare, setCompare] = useState(false);
  const [promptSelection, setPromptSelection] = useState<ImageItem[]>([]),
    [promptCompareOpen, setPromptCompareOpen] = useState(false);
  const [similarPrompt, setSimilarPrompt] = useState<ImageItem | null>(null);
  const [toast, setToast] = useState(""),
    [collectionName, setCollectionName] = useState<string | null>(null),
    [bulkTags, setBulkTags] = useState<string | null>(null),
    [deleting, setDeleting] = useState<string | null>(null);
  const revision = useRef(-1),
    toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const notify = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 4500);
  }, []);
  const update = useCallback((part: Partial<Filters>) => {
    setFilters((f) => ({ ...f, ...part }));
    setPage(0);
    setSelected(new Set());
  }, []);
  const refresh = useCallback(() => setReload((n) => n + 1), []);
  const action = async (fn: () => Promise<unknown>, message?: string) => {
    try {
      await fn();
      refresh();
      if (message) notify(message);
    } catch (e) {
      notify((e as Error).message);
    }
  };
  useEffect(() => {
    const timer = setTimeout(() => update({ q: search }), 250);
    return () => clearTimeout(timer);
  }, [search, update]);
  useEffect(() => {
    writePref("view", view);
    writePref("size", String(size));
    writePref("previews", String(previews));
  }, [view, size, previews]);
  useEffect(() => {
    let live = true;
    const poll = async () => {
      try {
        const [s, latestSettings] = await Promise.all([
          api<Status>("/status"),
          api<Settings>("/settings"),
        ]);
        if (!live) return;
        setSettings((previous) =>
          JSON.stringify(previous) === JSON.stringify(latestSettings)
            ? previous
            : latestSettings,
        );
        setStatus(s);
        if (revision.current !== s.revision) {
          revision.current = s.revision;
          refresh();
        }
      } catch (e) {
        if (live)
          setError(
            "The local server is unavailable. Check the startup window.",
          );
      }
    };
    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [refresh]);
  useEffect(() => {
    const controller = new AbortController();
    api<Facets>("/facets", "GET", undefined, controller.signal)
      .then(setFacets)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [reload]);
  const query = useMemo(() => {
    const params = new URLSearchParams({
      sort,
      direction,
      group: view === "prompts" ? "" : group,
      limit: String(pageSize),
      offset: String(page * pageSize),
      unique_prompts: String(view === "prompts"),
    });
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, String(value));
    });
    return params.toString();
  }, [filters, sort, direction, group, page, view]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api<{ items: ImageItem[]; total: number; image_total: number }>(
      "/images?" + query,
      "GET",
      undefined,
      controller.signal,
    )
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
        setImageTotal(data.image_total);
        if (page > 0 && page * pageSize >= data.total)
          setPage(Math.max(0, Math.ceil(data.total / pageSize) - 1));
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [query, reload]);
  useEffect(() => {
    setSelected(new Set());
    setSelecting(false);
  }, [page, view]);
  const closeDetail = useCallback(() => setDetailId(null), []),
    closeSettings = useCallback(() => setShowSettings(false), []),
    closeCompare = useCallback(() => setCompare(false), []),
    closePromptCompare = useCallback(() => setPromptCompareOpen(false), []);
  const togglePromptComparison = (item: ImageItem) =>
    setPromptSelection((current) =>
      current.some((prompt) => prompt.positive_hash === item.positive_hash)
        ? current.filter(
            (prompt) => prompt.positive_hash !== item.positive_hash,
          )
        : current.length < 2
          ? [...current, item]
          : current,
    );
  const clear = () => {
    setFilters(clean);
    setSearch("");
    setPage(0);
  };
  const navigate = (part: Partial<Filters> = {}, mode?: string) => {
    if (mode) setView(mode);
    else if (view === "prompts") setView("grid");
    setFilters({ ...clean, ...part });
    setSearch("");
    setPage(0);
    setSelected(new Set());
    setSidebar(false);
  };
  const favorite = (item: ImageItem) =>
    action(
      () =>
        api("/annotations", "PATCH", {
          image_ids: [item.id],
          favorite: !item.favorite,
        }),
      item.favorite ? "Removed from favorites" : "Added to favorites",
    );
  const toggleSelect = (id: string) =>
    setSelected((old) => {
      const next = new Set(old);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const title =
    view === "prompts"
      ? "Prompt library"
      : filters.prompt
        ? "Files using prompt"
        : filters.favorite
          ? "Favorites"
          : filters.collection
            ? facets.collections.find((c) => c.id === filters.collection)
                ?.name || "Collection"
            : filters.folder
              ? baseName(filters.folder)
              : filters.root
                ? baseName(filters.root)
                : "All media";
  const activeFilters = Object.entries(filters).filter(
    ([key, value]) =>
      value && !["q", "favorite", "collection", "exact"].includes(key),
  );
  const filtered = Boolean(
    filters.q || filters.favorite || filters.collection || activeFilters.length,
  );
  const copy = useCallback(
    async (text: string, label = "Copied to clipboard") => {
      try {
        await navigator.clipboard.writeText(text);
        notify(label);
      } catch {
        notify("Clipboard unavailable. Select the text and copy it manually.");
      }
    },
    [notify],
  );
  const groupLabel = (item: ImageItem) =>
    group === "model"
      ? item.model || "Model unavailable"
      : group === "date"
        ? dateLabel(item.sort_date)
        : group === "workflow"
          ? item.workflow_hash
            ? "Workflow " + item.workflow_hash.slice(0, 10)
            : "No embedded workflow"
          : "";

  return (
    <div className="app-shell">
      {sidebar && (
        <div className="sidebar-scrim" onClick={() => setSidebar(false)} />
      )}
      <aside className={`sidebar ${sidebar ? "is-open" : ""}`}>
        <a
          className="brand"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            navigate();
          }}
        >
          <span className="brand-icon">
            <Layers size={23} strokeWidth={1.8} />
          </span>
          <span>
            RenderBinder<small>COMFYUI IMAGE GALLERY</small>
          </span>
        </a>
        <div className="workspace-label">
          <span className="local-dot" /> LOCAL WORKSPACE{" "}
          <span className="version">v1.0</span>
        </div>
        <nav className="main-nav" aria-label="Library">
          <button
            className={
              !filters.favorite &&
              !filters.collection &&
              !filters.folder &&
              !filters.root &&
              !filters.prompt &&
              view !== "prompts"
                ? "active"
                : ""
            }
            onClick={() => {
              navigate({}, "grid");
            }}
          >
            <Grid2X2 size={18} />
            All media<span>{facets.total.toLocaleString()}</span>
          </button>
          <button
            className={filters.favorite ? "active" : ""}
            onClick={() => navigate({ favorite: true })}
          >
            <Heart size={18} />
            Favorites<span>{facets.favorites.toLocaleString()}</span>
          </button>
          <button
            className={
              view === "prompts" && !filters.favorite && !filters.collection
                ? "active"
                : ""
            }
            onClick={() => {
              navigate({}, "prompts");
            }}
          >
            <Clipboard size={18} />
            Prompt library<span>{facets.unique_prompts.toLocaleString()}</span>
          </button>
          <button
            onClick={() => {
              const d = new Date();
              d.setDate(d.getDate() - 6);
              navigate({ after: localDate(d) });
            }}
          >
            <RefreshCw size={18} />
            Last 7 days
          </button>
        </nav>
        <div className="side-section">
          <div className="section-label">
            SOURCES
            <button
              aria-label="Add source directory"
              onClick={() => setShowSettings(true)}
            >
              <Plus size={15} />
            </button>
          </div>
          {settings?.roots.length ? (
            settings.roots.map((root) => (
              <div key={root} className="source-tree">
                <button
                  className={`source-root ${filters.root === root ? "chosen" : ""}`}
                  title={root}
                  onClick={() => navigate({ root })}
                >
                  <ChevronDown size={12} />
                  <FolderOpen size={16} />
                  <span>{baseName(root)}</span>
                  <small>
                    {facets.roots.find(
                      (r) => r.name.toLowerCase() === root.toLowerCase(),
                    )?.count || 0}
                  </small>
                </button>
                <p className="source-path" title={root}>
                  {root}
                </p>
                {facets.folders
                  .filter(
                    (f) =>
                      f.name
                        .toLowerCase()
                        .startsWith(
                          root.toLowerCase().replace(/[\\/]+$/, "") +
                            (root.includes("\\") ? "\\" : "/"),
                        ) && f.name.toLowerCase() !== root.toLowerCase(),
                  )
                  .map((f) => (
                    <button
                      key={f.name}
                      className={`folder-item ${filters.folder === f.name ? "chosen" : ""}`}
                      title={f.name}
                      onClick={() => navigate({ folder: f.name })}
                    >
                      <Folder size={14} />
                      <span>{f.name.slice(root.length + 1)}</span>
                      <small>{f.count}</small>
                    </button>
                  ))}
              </div>
            ))
          ) : (
            <button
              className="add-source"
              onClick={() => setShowSettings(true)}
            >
              <FolderPlus size={16} />
              Connect a folder
            </button>
          )}
        </div>
        <div className="side-section">
          <div className="section-label">
            COLLECTIONS
            <button
              aria-label="Create collection"
              onClick={() => setCollectionName("")}
            >
              <Plus size={15} />
            </button>
          </div>
          {facets.collections.map((c) => (
            <div className="collection-row" key={c.id}>
              <button
                className={filters.collection === c.id ? "chosen" : ""}
                onClick={() => navigate({ collection: c.id })}
              >
                <span className="collection-dot" />
                <span>{c.name}</span>
                <small>{c.count}</small>
              </button>
              <button
                className="delete-collection"
                title="Delete collection"
                aria-label={`Delete ${c.name}`}
                onClick={() => setDeleting(c.id)}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
          {!facets.collections.length && (
            <p className="side-hint">No collections.</p>
          )}
        </div>
        {facets.tags.length > 0 && (
          <div className="side-section">
            <div className="section-label">TAGS</div>
            <div className="tag-cloud">
              {facets.tags.map((t) => (
                <button
                  key={t.name}
                  className={filters.tag === t.name ? "selected" : ""}
                  onClick={() =>
                    update({ tag: filters.tag === t.name ? "" : t.name })
                  }
                >
                  #{t.name}
                  <small>{t.count}</small>
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="sidebar-bottom">
          <div className="local-card">
            <span className={`status-dot ${status?.running ? "pulse" : ""}`} />
            <div>
              {status?.running
                ? "Indexing media"
                : status?.watching
                  ? "Watching for new files"
                  : "File watcher inactive"}
              <small>
                {status?.running
                  ? `${status.scanned.toLocaleString()} scanned · ${status.indexed} updated`
                  : `${settings?.roots.length || 0} configured source${settings?.roots.length === 1 ? "" : "s"}`}
              </small>
            </div>
          </div>
          <button
            className="settings-link"
            onClick={() => setShowSettings(true)}
          >
            <Settings2 size={17} />
            Settings & sources
            <ArrowUpRight size={15} />
          </button>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu icon-button"
              aria-label="Open navigation"
              onClick={() => setSidebar(true)}
            >
              <Layers size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>{title}</strong>
          </div>
          <div className="top-actions">
            <span className="local-badge">
              <span className="local-dot" />
              On your device
            </span>
            <button
              className="icon-button"
              title="Settings"
              aria-label="Settings"
              onClick={() => setShowSettings(true)}
            >
              <Settings2 size={18} />
            </button>
            <span className="avatar">R</span>
          </div>
        </header>
        <div className="content-inner">
          <div className="page-heading">
            <div>
              {filters.prompt && (
                <button
                  className="text-button prompt-back"
                  onClick={() => {
                    setView("prompts");
                    update({ prompt: "" });
                  }}
                >
                  <ArrowLeft size={13} />
                  Back to prompt library
                </button>
              )}
              <h1>
                {title}
                <span>
                  {view === "prompts" || filtered ? total : facets.total}
                </span>
              </h1>
              <p>
                {view === "prompts"
                  ? "Positive, global, and shot prompts, grouped by type and text."
                  : "Browse images and videos and inspect their generation metadata."}
              </p>
            </div>
            <button
              className="button secondary"
              onClick={() =>
                action(() => api("/scans", "POST"), "Rescan requested")
              }
            >
              <RefreshCw size={16} className={status?.running ? "spin" : ""} />
              {status?.running ? "Scanning…" : "Rescan library"}
            </button>
          </div>
          {status?.running && (
            <div className="scan-banner">
              <LoaderCircle size={16} className="spin" />
              <span>
                Scanning in the background{" "}
                <strong>{status.scanned.toLocaleString()}</strong> files ·{" "}
                {status.indexed} updated
              </span>
              <button
                onClick={() =>
                  action(
                    () => api("/scans/cancel", "POST"),
                    "Scan cancellation requested",
                  )
                }
              >
                Cancel scan
              </button>
            </div>
          )}
          {!status?.running && Boolean(status?.error_count) && (
            <button
              className="notice warning"
              onClick={() => setShowSettings(true)}
            >
              <CircleHelp size={16} />
              {status!.error_count} indexing issue
              {status!.error_count === 1 ? "" : "s"}. Open settings to review.
            </button>
          )}
          <div className="search-row">
            <div className="search-field">
              <Search size={19} />
              <input
                aria-label="Search library"
                placeholder="Search prompts, filenames, models, or tags…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {search ? (
                <button aria-label="Clear search" onClick={() => setSearch("")}>
                  <X size={16} />
                </button>
              ) : (
                <kbd>SEARCH</kbd>
              )}
            </div>
            <button
              aria-label="Filters"
              aria-expanded={showFilters}
              className={`button secondary filter-toggle ${showFilters || activeFilters.length ? "highlight" : ""}`}
              onClick={() => setShowFilters(!showFilters)}
            >
              <SlidersHorizontal size={16} />
              Filters
              {activeFilters.length > 0 && (
                <span className="count-bubble">{activeFilters.length}</span>
              )}
            </button>
          </div>
          {showFilters && (
            <div className="filter-panel">
              <label>
                Media type
                <select
                  aria-label="Media type"
                  value={filters.media_kind}
                  onChange={(e) => update({ media_kind: e.target.value })}
                >
                  <option value="">Images & videos</option>
                  <option value="image">Images</option>
                  <option value="video">Videos</option>
                </select>
              </label>
              <label>
                Prompt type
                <select
                  aria-label="Prompt type"
                  value={filters.prompt_scope}
                  onChange={(e) => update({ prompt_scope: e.target.value })}
                >
                  <option value="">All prompt types</option>
                  <option value="positive">Image prompts</option>
                  <option value="global">Global prompts</option>
                  <option value="shot">Shot prompts</option>
                </select>
              </label>
              <label>
                Model
                <select
                  aria-label="Model"
                  value={filters.model}
                  onChange={(e) => update({ model: e.target.value })}
                >
                  <option value="">All models</option>
                  {facets.models.map((m) => (
                    <option key={m.name}>{m.name}</option>
                  ))}
                </select>
              </label>
              <label>
                LoRA
                <select
                  aria-label="LoRA"
                  value={filters.lora}
                  onChange={(e) => update({ lora: e.target.value })}
                >
                  <option value="">All LoRAs</option>
                  {facets.loras.map((m) => (
                    <option key={m.name}>{m.name}</option>
                  ))}
                </select>
              </label>
              <label>
                Source
                <select
                  aria-label="Source"
                  value={filters.root}
                  onChange={(e) => update({ root: e.target.value, folder: "" })}
                >
                  <option value="">All sources</option>
                  {settings?.roots.map((root) => (
                    <option key={root} value={root}>
                      {root}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Seed
                <input
                  placeholder="Exact seed"
                  value={filters.seed}
                  onChange={(e) => update({ seed: e.target.value })}
                />
              </label>
              <label>
                From
                <input
                  type="date"
                  value={filters.after}
                  onChange={(e) => update({ after: e.target.value })}
                />
              </label>
              <label>
                Through
                <input
                  type="date"
                  value={filters.before}
                  onChange={(e) => update({ before: e.target.value })}
                />
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={filters.exact}
                  onChange={(e) => update({ exact: e.target.checked })}
                />
                Exact substring
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={filters.favorite}
                  onChange={(e) => update({ favorite: e.target.checked })}
                />
                Favorites only
              </label>
              <button className="text-button" onClick={clear}>
                Reset filters
              </button>
            </div>
          )}
          {activeFilters.length > 0 && (
            <div className="filter-chips">
              {activeFilters.map(([key, value]) => (
                <button key={key} onClick={() => update({ [key]: "" })}>
                  <span>{key === "prompt" ? "Prompt group" : `${key}:`}</span>
                  {key === "prompt"
                    ? ""
                    : String(value).length > 42
                      ? baseName(String(value)).slice(0, 42)
                      : String(value)}
                  <X size={12} />
                </button>
              ))}
            </div>
          )}
          <div className="gallery-toolbar">
            <div className="result-count">
              {loading ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <span className="subtle-dot" />
              )}
              <strong>{total.toLocaleString()}</strong>{" "}
              {view === "prompts"
                ? `${total === 1 ? "unique prompt" : "unique prompts"} · ${imageTotal.toLocaleString()} files`
                : total === 1
                  ? "image"
                  : "images"}
              {view !== "prompts" && (
                <>
                  <span className="toolbar-separator" />
                  <button
                    className={`text-button ${selecting ? "accent" : ""}`}
                    onClick={() => {
                      setSelecting(!selecting);
                      setSelected(new Set());
                    }}
                  >
                    <CheckCheck size={15} />
                    {selecting ? "Done selecting" : "Select"}
                  </button>
                </>
              )}
            </div>
            <div className="view-controls">
              <label className="sort-control">
                <ArrowDownUp size={14} />
                <select
                  aria-label="Sort images"
                  value={sort}
                  onChange={(e) => {
                    setSort(e.target.value);
                    setPage(0);
                  }}
                >
                  <option value="date">Date added</option>
                  <option value="filename">Filename</option>
                  <option value="resolution">Resolution</option>
                  <option value="model">Model</option>
                </select>
              </label>
              <button
                className="icon-button small"
                aria-label={
                  direction === "desc" ? "Sort ascending" : "Sort descending"
                }
                title={direction === "desc" ? "Descending" : "Ascending"}
                onClick={() => {
                  setDirection((d) => (d === "desc" ? "asc" : "desc"));
                  setPage(0);
                }}
              >
                {direction === "desc" ? (
                  <ArrowDownUp size={14} />
                ) : (
                  <ArrowUpRight size={14} />
                )}
              </button>
              {view !== "prompts" && (
                <>
                  <select
                    className="group-select"
                    aria-label="Group images"
                    value={group}
                    onChange={(e) => {
                      setGroup(e.target.value);
                      setPage(0);
                    }}
                  >
                    <option value="">No grouping</option>
                    <option value="model">By model</option>
                    <option value="date">By date</option>
                    <option value="workflow">By workflow</option>
                  </select>
                  <div className="size-control">
                    <ImageIcon size={14} />
                    <input
                      type="range"
                      min="170"
                      max="360"
                      step="10"
                      aria-label="Thumbnail size"
                      value={size}
                      onChange={(e) => setSize(Number(e.target.value))}
                    />
                  </div>
                </>
              )}
              {view !== "prompts" && (
                <div className="view-switch">
                  <button
                    aria-label="Grid view"
                    className={view === "grid" ? "active" : ""}
                    onClick={() => setView("grid")}
                  >
                    <Grid2X2 size={16} />
                  </button>
                  <button
                    aria-label="List view"
                    className={view === "list" ? "active" : ""}
                    onClick={() => setView("list")}
                  >
                    <List size={17} />
                  </button>
                </div>
              )}
            </div>
          </div>
          {error ? (
            <div className="empty-state">
              <CircleHelp size={32} />
              <h2>Something needs attention</h2>
              <p>{error}</p>
              <button className="button primary" onClick={refresh}>
                Try again
              </button>
            </div>
          ) : !items.length && !loading ? (
            <div className="empty-state onboarding">
              <div className="empty-art">
                <div className="empty-frame back" />
                <div className="empty-frame front">
                  <ImageIcon size={38} strokeWidth={1} />
                  <Sparkles size={18} />
                </div>
                <span className="orbit-dot" />
              </div>
              <h2>
                {filtered
                  ? "No matching files"
                  : settings?.roots.length
                    ? view === "prompts"
                      ? "No extracted prompts"
                      : "No indexed media"
                    : "No image folders configured"}
              </h2>
              <p>
                {filtered
                  ? "Change the search or filters to see more results."
                  : settings?.roots.length
                    ? "Configured folders are scanned in the background. New results appear automatically."
                    : "Add a ComfyUI output folder to index its media and metadata."}
              </p>
              <button
                className="button primary"
                onClick={filtered ? clear : () => setShowSettings(true)}
              >
                {filtered ? <X size={16} /> : <FolderPlus size={17} />}{" "}
                {filtered
                  ? "Clear filters"
                  : settings?.roots.length
                    ? "Manage sources"
                    : "Add image folder"}
                {!filtered && <ArrowRight size={16} />}
              </button>
              {!filtered && (
                <div className="empty-features">
                  <span>
                    <Check size={13} />
                    Original files untouched
                  </span>
                  <span>
                    <Check size={13} />
                    No cloud or API keys
                  </span>
                  <span>
                    <Check size={13} />
                    SQLite search index
                  </span>
                </div>
              )}
            </div>
          ) : (
            <div
              className={`gallery ${view === "list" ? "gallery-list" : view === "prompts" ? "gallery-prompts" : "gallery-grid"} ${loading ? "is-loading" : ""}`}
              style={{ "--card-size": `${size}px` } as CSSProperties}
            >
              {items
                .filter((item) =>
                  view === "prompts"
                    ? Boolean(item.prompt_id)
                    : !item.prompt_id,
                )
                .map((item, index) =>
                  view === "prompts" ? (
                    <PromptGroupCard
                      key={item.positive_hash || item.id}
                      item={item}
                      comparisonIndex={promptSelection.findIndex(
                        (prompt) => prompt.positive_hash === item.positive_hash,
                      )}
                      comparisonDisabled={promptSelection.length === 2}
                      onToggleComparison={() => togglePromptComparison(item)}
                      onFindSimilar={() => setSimilarPrompt(item)}
                      onOpen={() => {
                        setView("grid");
                        update({ prompt: item.positive_hash || "" });
                      }}
                      onCopy={() =>
                        action(async () => {
                          const detail = await api<PromptText>(
                            promptResource(item),
                          );
                          await copy(detail.positive);
                        })
                      }
                    />
                  ) : (
                    <ImageCard
                      key={item.id}
                      item={item}
                      view={view}
                      selecting={selecting}
                      selected={selected.has(item.id)}
                      previews={previews}
                      group={
                        group &&
                        (!index ||
                          groupLabel(items[index - 1]) !== groupLabel(item))
                          ? groupLabel(item)
                          : ""
                      }
                      onOpen={() =>
                        selecting ? toggleSelect(item.id) : setDetailId(item.id)
                      }
                      onSelect={() => {
                        setSelecting(true);
                        toggleSelect(item.id);
                      }}
                      onFavorite={() => favorite(item)}
                    />
                  ),
                )}
              {loading &&
                !items.length &&
                Array.from({ length: 8 }, (_, i) => (
                  <div className="skeleton-card" key={i}>
                    <div />
                    <span />
                    <small />
                  </div>
                ))}
            </div>
          )}
          {items.length > 0 && (
            <footer className="gallery-footer">
              <span>
                Showing {(page * pageSize + 1).toLocaleString()}–
                {Math.min((page + 1) * pageSize, total).toLocaleString()} of{" "}
                {total.toLocaleString()}{" "}
                {view === "prompts" ? "prompts" : "files"}
              </span>
              {view !== "prompts" && (
                <label className="preview-toggle">
                  <input
                    type="checkbox"
                    checked={previews}
                    onChange={(e) => setPreviews(e.target.checked)}
                  />
                  Prompt previews
                </label>
              )}
              <div className="pagination">
                <button
                  aria-label="Previous page"
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                >
                  <ChevronLeft size={16} />
                </button>
                <span>
                  {page + 1} / {Math.max(1, Math.ceil(total / pageSize))}
                </span>
                <button
                  aria-label="Next page"
                  disabled={(page + 1) * pageSize >= total}
                  onClick={() => setPage((p) => p + 1)}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </footer>
          )}
        </div>
      </main>
      {view === "prompts" && promptSelection.length > 0 && (
        <div
          className="selection-bar prompt-selection-bar"
          aria-label="Prompt comparison selection"
        >
          <button
            className="icon-button"
            aria-label="Clear prompt comparison selection"
            onClick={() => setPromptSelection([])}
          >
            <X size={17} />
          </button>
          <strong>
            {promptSelection.length}{" "}
            {promptSelection.length === 1 ? "prompt" : "prompts"} selected
          </strong>
          {promptSelection.length === 1 && (
            <span className="prompt-selection-hint">
              Select one more prompt
            </span>
          )}
          <button
            className="compare-prompts-button"
            disabled={promptSelection.length !== 2}
            onClick={() => setPromptCompareOpen(true)}
          >
            <GitCompareArrows size={16} />
            Compare prompts
          </button>
        </div>
      )}
      {selected.size > 0 && (
        <div className="selection-bar">
          <button
            className="icon-button"
            aria-label="Clear selection"
            onClick={() => setSelected(new Set())}
          >
            <X size={17} />
          </button>
          <strong>{selected.size} selected</strong>
          <button onClick={() => setSelected(new Set(items.map((i) => i.id)))}>
            <CheckCheck size={15} />
            Select page
          </button>
          <span />
          <button
            disabled={selected.size < 2 || selected.size > 4}
            onClick={() => setCompare(true)}
            title="Compare 2–4 selected images"
          >
            <GitCompareArrows size={16} />
            Compare
          </button>
          <button
            onClick={() =>
              action(
                () =>
                  api("/annotations", "PATCH", {
                    image_ids: [...selected],
                    favorite: true,
                  }),
                "Added to favorites",
              )
            }
          >
            <Heart size={16} />
            Favorite
          </button>
          <button onClick={() => setBulkTags("")}>
            <Tag size={16} />
            Set tags
          </button>
          <select
            aria-label="Add selection to collection"
            value=""
            onChange={(e) => {
              if (e.target.value)
                action(
                  () =>
                    api("/collections/" + e.target.value, "PATCH", {
                      image_ids: [...selected],
                    }),
                  "Added to collection",
                );
            }}
          >
            <option value="">Add to collection…</option>
            {facets.collections.map((c) => (
              <option value={c.id} key={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          {filters.collection && (
            <button
              onClick={() =>
                action(
                  () =>
                    api("/collections/" + filters.collection, "PATCH", {
                      image_ids: [...selected],
                      remove: true,
                    }),
                  "Removed from collection",
                )
              }
            >
              Remove
            </button>
          )}
        </div>
      )}
      {toast && (
        <div className="toast" role="status">
          <Check size={16} />
          {toast}
          <button
            aria-label="Dismiss notification"
            onClick={() => setToast("")}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {showSettings && settings && (
        <SettingsModal
          settings={settings}
          status={status}
          onClose={closeSettings}
          onSaved={(s) => {
            setSettings(s);
            refresh();
            notify("Sources saved. Indexing will start automatically.");
          }}
          notify={notify}
        />
      )}
      {detailId && (
        <DetailModal
          id={detailId}
          settings={settings}
          onClose={closeDetail}
          onChanged={refresh}
          notify={notify}
          copy={copy}
          onPrevious={
            items.findIndex((i) => i.id === detailId) > 0
              ? () =>
                  setDetailId(
                    items[items.findIndex((i) => i.id === detailId) - 1].id,
                  )
              : undefined
          }
          onNext={
            items.findIndex((i) => i.id === detailId) < items.length - 1
              ? () =>
                  setDetailId(
                    items[items.findIndex((i) => i.id === detailId) + 1].id,
                  )
              : undefined
          }
          collections={facets.collections}
          onSimilar={(key, value) => {
            closeDetail();
            update({ [key]: value });
          }}
          onPromptSimilar={(item) => {
            closeDetail();
            setSimilarPrompt(item);
          }}
        />
      )}
      {compare && <CompareModal ids={[...selected]} onClose={closeCompare} />}
      {similarPrompt && (
        <Modal
          title="Similar prompts"
          wide
          onClose={() => setSimilarPrompt(null)}
        >
          <SimilarPrompts
            source={similarPrompt}
            onCompare={(item) => {
              setPromptSelection([similarPrompt, item]);
              setSimilarPrompt(null);
              setPromptCompareOpen(true);
            }}
            onSettings={() => {
              setSimilarPrompt(null);
              setShowSettings(true);
            }}
          />
        </Modal>
      )}
      {promptCompareOpen && promptSelection.length === 2 && (
        <PromptDiffModal
          items={promptSelection}
          onClose={closePromptCompare}
          copy={copy}
        />
      )}
      {collectionName !== null && (
        <Modal
          title="Create a collection"
          onClose={() => setCollectionName(null)}
        >
          <form
            className="form-body"
            onSubmit={(e) => {
              e.preventDefault();
              action(async () => {
                await api("/collections", "POST", { name: collectionName });
                setCollectionName(null);
              }, "Collection created");
            }}
          >
            <p>Keep files together without moving them.</p>
            <label>
              Collection name
              <input
                autoFocus
                maxLength={100}
                value={collectionName}
                placeholder="e.g. Worlds worth revisiting"
                onChange={(e) => setCollectionName(e.target.value)}
              />
            </label>
            <button
              className="button primary"
              disabled={!collectionName.trim()}
              type="submit"
            >
              <Plus size={16} />
              Create collection
            </button>
          </form>
        </Modal>
      )}
      {bulkTags !== null && (
        <Modal
          title={`Set tags for ${selected.size} images`}
          onClose={() => setBulkTags(null)}
        >
          <form
            className="form-body"
            onSubmit={(e) => {
              e.preventDefault();
              action(async () => {
                await api("/annotations", "PATCH", {
                  image_ids: [...selected],
                  tags: bulkTags.split(","),
                });
                setBulkTags(null);
              }, "Tags saved");
            }}
          >
            <p>
              This replaces the tags on every selected image. Separate tags with
              commas; leave empty to clear them.
            </p>
            <label>
              Tags
              <input
                autoFocus
                value={bulkTags}
                onChange={(e) => setBulkTags(e.target.value)}
                placeholder="landscape, inspiration, final"
              />
            </label>
            <button type="submit" className="button primary">
              Save tags
            </button>
          </form>
        </Modal>
      )}
      {deleting && (
        <Modal title="Delete collection?" onClose={() => setDeleting(null)}>
          <div className="form-body">
            <p>
              The collection will be removed. Your original files, favorites,
              and tags are kept.
            </p>
            <button
              className="button danger"
              onClick={() =>
                action(async () => {
                  await api("/collections/" + deleting, "DELETE");
                  if (filters.collection === deleting) navigate();
                  setDeleting(null);
                }, "Collection deleted")
              }
            >
              Delete collection
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function ImageCard({
  item,
  view,
  selecting,
  selected,
  previews,
  group,
  onOpen,
  onSelect,
  onFavorite,
}: {
  item: ImageItem;
  view: string;
  selecting: boolean;
  selected: boolean;
  previews: boolean;
  group: string;
  onOpen: () => void;
  onSelect: () => void;
  onFavorite: () => void;
}) {
  return (
    <>
      {group && (
        <div className="group-heading">
          <Layers size={14} />
          {group}
        </div>
      )}
      <article
        className={`image-card ${selected ? "selected" : ""} ${selecting ? "selecting" : ""}`}
      >
        <button
          className="image-open"
          aria-label={`Inspect ${item.filename}`}
          onClick={onOpen}
        >
          <img
            loading="lazy"
            decoding="async"
            src={media(item.id)}
            alt={item.positive || item.filename}
          />
          <span className="image-dimensions">
            {item.media_kind === "video" && (
              <>
                <Play size={12} />
                {timeLabel(item.duration)} ·{" "}
              </>
            )}
            {item.width} × {item.height}
          </span>
          <span className="image-inspect">
            <Maximize2 size={18} />
          </span>
        </button>
        <button
          className={`card-select ${selected ? "checked" : ""}`}
          aria-label={`${selected ? "Deselect" : "Select"} ${item.filename}`}
          onClick={onSelect}
        >
          {selected ? <Check size={13} /> : <Square size={14} />}
        </button>
        <button
          className={`card-favorite ${item.favorite ? "is-favorite" : ""}`}
          aria-label={`${item.favorite ? "Unfavorite" : "Favorite"} ${item.filename}`}
          onClick={onFavorite}
        >
          <Heart size={15} fill={item.favorite ? "currentColor" : "none"} />
        </button>
        <div className="card-info">
          <button
            className="card-filename"
            onClick={onOpen}
            title={item.filename}
          >
            {item.filename}
          </button>
          <div className="card-subline">
            <span
              className="model-name"
              title={item.model || "Model unavailable"}
            >
              <span />
              {item.model ? baseName(item.model) : "Model unavailable"}
            </span>
            <time
              title={
                item.generated_at
                  ? "Embedded generation date"
                  : "File modification date"
              }
            >
              {dateLabel(item.sort_date)}
            </time>
          </div>
          {previews && (
            <p className="prompt-preview">
              {item.positive ||
                (item.shot_count
                  ? `${item.shot_count} shot ${item.shot_count === 1 ? "prompt" : "prompts"}. Open the video to inspect.`
                  : "No positive prompt could be reliably extracted.")}
            </p>
          )}
          {item.tags.length > 0 && (
            <div className="card-tags">
              {item.tags.slice(0, 3).map((t) => (
                <span key={t}>#{t}</span>
              ))}
              {item.tags.length > 3 && <span>+{item.tags.length - 3}</span>}
            </div>
          )}
        </div>
        {view === "list" && (
          <div className="list-details">
            <span>
              {item.width} × {item.height}
            </span>
            <span>{bytes(item.size)}</span>
            <span className={`confidence ${item.confidence}`}>
              {item.confidence}
            </span>
          </div>
        )}
      </article>
    </>
  );
}

function PromptGroupCard({
  item,
  onOpen,
  onCopy,
  comparisonIndex,
  comparisonDisabled,
  onToggleComparison,
  onFindSimilar,
}: {
  item: ImageItem;
  onOpen: () => void;
  onCopy: () => void;
  comparisonIndex: number;
  comparisonDisabled: boolean;
  onToggleComparison: () => void;
  onFindSimilar: () => void;
}) {
  const count = item.image_count || 1;
  const noun = item.media_kind === "video" ? "video" : "image";
  const [expanded, setExpanded] = useState(false),
    [fullText, setFullText] = useState<string | null>(null),
    [textLoading, setTextLoading] = useState(false),
    [textError, setTextError] = useState(""),
    [retry, setRetry] = useState(0);
  const loaded = useRef<{ id: string; text: string } | null>(null);
  useEffect(() => {
    setTextError("");
    if (loaded.current?.id === (item.prompt_id || item.id)) {
      setFullText(loaded.current.text);
      setTextLoading(false);
      return;
    }
    setFullText(null);
    if (!expanded) {
      setTextLoading(false);
      return;
    }
    const controller = new AbortController();
    setTextLoading(true);
    api<PromptText>(promptResource(item), "GET", undefined, controller.signal)
      .then((prompt) => {
        loaded.current = {
          id: item.prompt_id || item.id,
          text: prompt.positive,
        };
        setFullText(prompt.positive);
        setTextLoading(false);
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setTextError(error.message);
          setTextLoading(false);
        }
      });
    return () => controller.abort();
  }, [expanded, item.id, item.prompt_id, retry]);
  const textId = `prompt-text-${item.positive_hash || item.id}`;
  return (
    <article
      className={`prompt-group-card ${expanded ? "is-expanded" : ""} ${comparisonIndex >= 0 ? "is-comparison-selected" : ""}`}
    >
      <button
        className="prompt-group-preview"
        aria-label="View images using this prompt"
        onClick={onOpen}
      >
        <img
          loading="lazy"
          decoding="async"
          src={media(item.id)}
          alt="Latest image using this prompt"
        />
        <span>
          <ImageIcon size={12} />
          {count}
        </span>
      </button>
      <div className="prompt-group-content">
        <div className="prompt-group-heading">
          <strong>
            {count.toLocaleString()} {count === 1 ? noun : noun + "s"}
          </strong>
          <time>Last used {dateLabel(item.sort_date)}</time>
        </div>
        {item.scope && item.scope !== "positive" && (
          <div className="prompt-scope-label">
            {scopeLabel(item.scope)}
            {item.start != null
              ? ` · ${timeLabel(item.start)}–${timeLabel(item.end)}`
              : ""}{" "}
            · {item.filename}
          </div>
        )}
        <p
          id={textId}
          className={`prompt-group-text ${expanded ? "expanded" : ""}`}
          aria-busy={textLoading}
        >
          {expanded && fullText !== null ? fullText : item.positive}
        </p>
        {expanded && textLoading && (
          <p className="prompt-load-status" role="status">
            <LoaderCircle size={12} className="spin" />
            Loading full prompt…
          </p>
        )}
        {expanded && textError && (
          <div className="prompt-load-error" role="alert">
            {textError}
            <button
              className="text-button"
              onClick={() => setRetry((n) => n + 1)}
            >
              Retry
            </button>
          </div>
        )}
        <div className="prompt-group-tools">
          <button className="text-button" onClick={onFindSimilar}>
            <Search size={13} />
            Find similar prompts
          </button>
          <button
            className="text-button"
            aria-expanded={expanded}
            aria-controls={textId}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            {expanded ? "Collapse prompt" : "Expand prompt"}
          </button>
          <button
            className={`text-button ${comparisonIndex >= 0 ? "accent" : ""}`}
            aria-pressed={comparisonIndex >= 0}
            aria-label={
              comparisonIndex >= 0
                ? `Remove prompt ${comparisonIndex === 0 ? "A" : "B"} from comparison`
                : "Select prompt for comparison"
            }
            disabled={comparisonDisabled && comparisonIndex < 0}
            onClick={onToggleComparison}
          >
            <GitCompareArrows size={13} />
            {comparisonIndex >= 0
              ? `Prompt ${comparisonIndex === 0 ? "A" : "B"} selected`
              : "Select for comparison"}
          </button>
        </div>
        <div className="prompt-group-actions">
          <button className="text-button" onClick={onCopy}>
            <Copy size={13} />
            Copy prompt
          </button>
          <button className="text-button accent" onClick={onOpen}>
            View {count.toLocaleString()} {count === 1 ? noun : noun + "s"}
            <ArrowRight size={13} />
          </button>
        </div>
      </div>
    </article>
  );
}

function PromptDiffModal({
  items,
  onClose,
  copy,
}: {
  items: ImageItem[];
  onClose: () => void;
  copy: (text: string, label?: string) => Promise<void>;
}) {
  const [texts, setTexts] = useState<PromptText[] | null>(null),
    [result, setResult] = useState<PromptDiff | null>(null),
    [error, setError] = useState(""),
    [swapped, setSwapped] = useState(false);
  const ids = items.map((item) => item.prompt_id || item.id).join(",");
  const diffColumns = useRef<HTMLDivElement>(null);
  const jumpToChanges = useCallback(() => {
    diffColumns.current
      ?.querySelectorAll<HTMLElement>(".prompt-diff-text")
      .forEach((panel) => {
        const change = panel.querySelector<HTMLElement>("mark");
        if (change)
          panel.scrollTop +=
            change.getBoundingClientRect().top -
            panel.getBoundingClientRect().top -
            panel.clientHeight / 2;
      });
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setTexts(null);
    setResult(null);
    Promise.all(
      items.map((item) =>
        api<PromptText>(
          promptResource(item),
          "GET",
          undefined,
          controller.signal,
        ),
      ),
    )
      .then(setTexts)
      .catch((error) => {
        if (error.name !== "AbortError") setError(error.message);
      });
    return () => controller.abort();
  }, [ids]);
  useEffect(() => {
    if (!texts) return;
    setResult(null);
    setError("");
    const worker = new Worker(
      new URL("./promptDiff.worker.ts", import.meta.url),
      { type: "module" },
    );
    worker.onmessage = (
      event: MessageEvent<{ result?: PromptDiff; error?: string }>,
    ) => {
      if (event.data.result) setResult(event.data.result);
      else setError(event.data.error || "Could not compare the prompts.");
    };
    worker.onerror = () =>
      setError(
        "Could not start the prompt comparison. Close this dialog and try again.",
      );
    worker.postMessage({
      before: texts[swapped ? 1 : 0].positive,
      after: texts[swapped ? 0 : 1].positive,
    });
    return () => worker.terminate();
  }, [texts, swapped]);
  useEffect(() => {
    if (result && !result.identical) jumpToChanges();
  }, [result, jumpToChanges]);
  return (
    <Modal title="Compare prompts" onClose={onClose} wide>
      <div className="prompt-diff-body">
        <div className="prompt-diff-toolbar">
          <p>
            Text removed from A is red. Text added in B is green. Whitespace and
            punctuation are included.
          </p>
          <div className="prompt-diff-tools">
            <button
              className="button secondary"
              disabled={!result || result.identical}
              onClick={jumpToChanges}
            >
              <Search size={14} />
              Jump to changes
            </button>
            <button
              className="button secondary"
              disabled={!texts}
              onClick={() => setSwapped((value) => !value)}
            >
              <ArrowDownUp size={14} />
              Swap A and B
            </button>
          </div>
        </div>
        {error ? (
          <p className="notice warning" role="alert">
            {error}
          </p>
        ) : !result || !texts ? (
          <div className="diff-loading" role="status">
            <LoaderCircle size={20} className="spin" />
            Comparing full prompts…
          </div>
        ) : (
          <>
            <div className="prompt-diff-summary" role="status">
              {result.identical ? (
                <span>
                  <Check size={14} />
                  No text differences
                </span>
              ) : (
                <>
                  <span className="diff-removed-label">
                    − {result.removedCharacters.toLocaleString()} characters
                    removed
                  </span>
                  <span className="diff-added-label">
                    + {result.addedCharacters.toLocaleString()} characters added
                  </span>
                  {result.whitespaceOnly && (
                    <span>Only whitespace differs.</span>
                  )}
                </>
              )}
            </div>
            {result.simplified && (
              <p className="diff-fallback-note">
                A detailed diff exceeded the comparison limit. Both full prompts
                are shown below as removed and added text.
              </p>
            )}
            <div className="prompt-diff-columns" ref={diffColumns}>
              {(["before", "after"] as const).map((side, index) => {
                const sourceIndex = swapped ? 1 - index : index;
                const item = items[sourceIndex];
                return (
                  <section
                    className={`prompt-diff-panel diff-${side}`}
                    key={side}
                    aria-label={`Prompt ${index === 0 ? "A" : "B"}`}
                  >
                    <header>
                      <div>
                        <h3>Prompt {index === 0 ? "A" : "B"}</h3>
                        <small>
                          {(item.image_count || 1).toLocaleString()}{" "}
                          {item.media_kind === "video"
                            ? (item.image_count || 1) === 1
                              ? "video"
                              : "videos"
                            : (item.image_count || 1) === 1
                              ? "image"
                              : "images"}{" "}
                          · {dateLabel(item.sort_date)}
                        </small>
                        {item.scope && item.scope !== "positive" && (
                          <small>
                            {scopeLabel(item.scope)} · {item.label} ·{" "}
                            {item.filename}
                          </small>
                        )}
                      </div>
                      <button
                        className="text-button"
                        aria-label={`Copy prompt ${index === 0 ? "A" : "B"}`}
                        onClick={() =>
                          copy(
                            texts[sourceIndex].positive,
                            `Prompt ${index === 0 ? "A" : "B"} copied`,
                          )
                        }
                      >
                        <Copy size={13} />
                        Copy
                      </button>
                    </header>
                    <div className="prompt-diff-text">
                      {result.parts
                        .filter(
                          (part) =>
                            part.kind !==
                            (side === "before" ? "added" : "removed"),
                        )
                        .map((part, partIndex) =>
                          part.kind === "same" ? (
                            <span key={partIndex}>{part.value}</span>
                          ) : (
                            <mark
                              key={partIndex}
                              className={`diff-${part.kind}`}
                            >
                              {part.value}
                            </mark>
                          ),
                        )}
                    </div>
                  </section>
                );
              })}
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}

function SettingsModal({
  settings,
  status,
  onClose,
  onSaved,
  notify,
}: {
  settings: Settings;
  status: Status | null;
  onClose: () => void;
  onSaved: (s: Settings) => void;
  notify: (s: string) => void;
}) {
  const [roots, setRoots] = useState(settings.roots.join("\n")),
    [url, setUrl] = useState(settings.comfy_url),
    [saving, setSaving] = useState(false),
    [error, setError] = useState(""),
    [rebuild, setRebuild] = useState(false);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const s = await api<Settings>("/settings", "PUT", {
        roots: roots
          .split("\n")
          .map((x) => x.trim())
          .filter(Boolean),
        comfy_url: url,
      });
      onSaved(s);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal title="Settings & sources" onClose={onClose}>
      <form className="form-body settings-body" onSubmit={save}>
        <div className="settings-intro">
          <span className="settings-icon">
            <FolderOpen size={24} />
          </span>
          <div>
            <h3>Image sources</h3>
            <p>
              Connect existing folders. Subfolders are included automatically.
            </p>
          </div>
        </div>
        <label>
          Image directories <span>One absolute path per line</span>
          <textarea
            rows={4}
            value={roots}
            onChange={(e) => setRoots(e.target.value)}
            placeholder={"C:\\ComfyUI\\output\nD:\\Images\\generations"}
            spellCheck={false}
          />
        </label>
        <div className="info-note">
          <Check size={15} />
          <p>
            Sources are read only. Your files are never moved, renamed, or
            rewritten. Nested sources are combined automatically.
          </p>
        </div>
        <label>
          Local ComfyUI URL
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="http://127.0.0.1:8188"
          />
        </label>
        <p className="muted small-text">
          ComfyUI is optional. Workflow exports and gallery browsing work while
          it is offline.
        </p>
        <div className="settings-storage">
          <span>Library data</span>
          <code>{settings.data_dir}</code>
          <small>
            Index and thumbnails are rebuildable. Favorites, tags, and
            collections are stored separately in library.sqlite3.
          </small>
        </div>
        {error && (
          <div className="notice warning" role="alert">
            {error}
          </div>
        )}
        <button className="button primary" type="submit" disabled={saving}>
          {saving ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <Check size={16} />
          )}
          Save & scan folders
        </button>
      </form>
      <SemanticSettings />
      <MetadataFormats />
      <div className="settings-maintenance">
        <h3>Index maintenance</h3>
        <p>
          {status?.cancelled
            ? "The last scan was cancelled."
            : status?.running
              ? `Scanning: ${status.scanned} files.`
              : status?.finished_at
                ? `Last scan: ${new Date(status.finished_at * 1000).toLocaleString()}`
                : "Waiting for the first scan."}{" "}
          {status?.pending ? `${status.pending} file changes pending.` : ""}
        </p>
        <div className="maintenance-actions">
          <button
            className="button secondary"
            onClick={async () => {
              try {
                await api("/scans", "POST");
                notify("Rescan requested");
              } catch (e) {
                notify((e as Error).message);
              }
            }}
          >
            <RefreshCw size={14} />
            Rescan
          </button>
          {status?.running && (
            <button
              className="button secondary"
              onClick={() =>
                api("/scans/cancel", "POST").catch((e) => notify(e.message))
              }
            >
              Cancel scan
            </button>
          )}
          <button className="text-button" onClick={() => setRebuild(!rebuild)}>
            Rebuild index
          </button>
        </div>
        {rebuild && (
          <div className="rebuild-box">
            <p>
              Re-read every original and rebuild the search index. Favorites,
              tags, and collections are preserved. Browsing fills in as the scan
              progresses.
            </p>
            <button
              className="button secondary"
              onClick={async () => {
                try {
                  await api("/scans?rebuild=true", "POST");
                  setRebuild(false);
                  notify("Index rebuild requested");
                } catch (e) {
                  notify((e as Error).message);
                }
              }}
            >
              Start rebuild
            </button>
          </div>
        )}
        {Boolean(status?.errors.length) && (
          <details className="error-log">
            <summary>{status!.error_count} indexing issues (latest 30)</summary>
            {status!.errors.map((e, i) => (
              <p key={i}>{e}</p>
            ))}
          </details>
        )}
      </div>
    </Modal>
  );
}

function DetailModal({
  id,
  settings,
  onClose,
  onChanged,
  notify,
  copy,
  onPrevious,
  onNext,
  collections,
  onSimilar,
  onPromptSimilar,
}: {
  id: string;
  settings: Settings | null;
  onClose: () => void;
  onChanged: () => void;
  notify: (s: string) => void;
  copy: (text: string, label?: string) => Promise<void>;
  onPrevious?: () => void;
  onNext?: () => void;
  collections: Facets["collections"];
  onSimilar: (key: string, value: string) => void;
  onPromptSimilar: (item: ImageItem) => void;
}) {
  const [image, setImage] = useState<ImageDetail | null>(null),
    [tab, setTab] = useState("prompts"),
    [error, setError] = useState(""),
    [tags, setTags] = useState(""),
    [queue, setQueue] = useState(false),
    [confirmed, setConfirmed] = useState(false),
    [sending, setSending] = useState(false);
  const [seek, setSeek] = useState<{ time: number; nonce: number } | null>(
    null,
  );
  useEffect(() => {
    const c = new AbortController();
    setImage(null);
    setSeek(null);
    setError("");
    setQueue(false);
    setConfirmed(false);
    api<ImageDetail>("/images/" + id, "GET", undefined, c.signal)
      .then((i) => {
        setImage(i);
        setTags(i.tags.join(", "));
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => c.abort();
  }, [id]);
  const reload = async () => {
    setImage(await api<ImageDetail>("/images/" + id));
    onChanged();
  };
  const mutate = async (fn: () => Promise<unknown>, message?: string) => {
    try {
      await fn();
      await reload();
      if (message) notify(message);
    } catch (e) {
      notify((e as Error).message);
    }
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).matches("input,textarea,select")) return;
      if (e.key === "ArrowLeft") onPrevious?.();
      if (e.key === "ArrowRight") onNext?.();
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onPrevious, onNext]);
  const label: Record<string, string> = {
    seed: "Seed",
    steps: "Steps",
    cfg: "CFG scale",
    sampler: "Sampler",
    scheduler: "Scheduler",
    denoise: "Denoise",
    start_at_step: "Start at step",
    end_at_step: "End at step",
  };
  return (
    <Modal title={image?.filename || "Media details"} onClose={onClose} wide>
      {error ? (
        <div className="form-body notice warning">{error}</div>
      ) : !image ? (
        <div className="dialog-loading">
          <LoaderCircle className="spin" />
        </div>
      ) : (
        <div className="detail-layout">
          <div className="detail-preview">
            {image.media_kind === "video" ? (
              <VideoPlayer key={id} item={image} seek={seek} />
            ) : (
              <img
                src={media(id, "original")}
                alt={image.positive || image.filename}
              />
            )}
            <div className="preview-nav">
              <button
                className="icon-button"
                disabled={!onPrevious}
                onClick={onPrevious}
                aria-label="Previous image"
              >
                <ChevronLeft size={20} />
              </button>
              <span>
                {image.width} × {image.height}
                <span> · </span>
                {bytes(image.size)}
                {image.media_kind === "video" && (
                  <>
                    {" "}
                    · {timeLabel(image.duration)} · {image.fps?.toFixed(2)} fps
                  </>
                )}
              </span>
              <button
                className="icon-button"
                disabled={!onNext}
                onClick={onNext}
                aria-label="Next image"
              >
                <ChevronRight size={20} />
              </button>
            </div>
          </div>
          <div className="detail-panel">
            <div className="detail-title">
              <div>
                <span className="eyebrow">GENERATION DETAILS</span>
                <h3>
                  {image.model ? baseName(image.model) : "Model unavailable"}
                </h3>
              </div>
              <button
                className={`icon-button ${image.favorite ? "accent" : ""}`}
                aria-label={image.favorite ? "Remove favorite" : "Add favorite"}
                onClick={() =>
                  mutate(() =>
                    api("/annotations", "PATCH", {
                      image_ids: [id],
                      favorite: !image.favorite,
                    }),
                  )
                }
              >
                <Heart
                  size={20}
                  fill={image.favorite ? "currentColor" : "none"}
                />
              </button>
            </div>
            <div className="detail-badges">
              <span className={`confidence ${image.confidence}`}>
                {image.confidence === "high"
                  ? "Graph linked"
                  : image.confidence === "partial"
                    ? "Partial extraction"
                    : "Metadata unavailable"}
              </span>
              <span>
                {dateLabel(image.sort_date)}{" "}
                {image.generated_at ? "" : "· file date"}
              </span>
            </div>
            <div className="detail-tabs">
              {[
                ["prompts", "Prompts"],
                ["settings", "Settings"],
                ["file", "File"],
                ["metadata", "Metadata"],
                ["raw", "Raw JSON"],
              ].map(([key, value]) => (
                <button
                  key={key}
                  className={tab === key ? "active" : ""}
                  onClick={() => setTab(key)}
                >
                  {value}
                </button>
              ))}
            </div>
            <div className="detail-tab-content">
              {tab === "metadata" && (
                <div className="metadata-summary">
                  <section>
                    <h4>Format</h4>
                    <p>
                      {image.media_kind || "image"} · Schema{" "}
                      {image.metadata.schema_version || 1}
                    </p>
                    <p>
                      {image.technical?.video_codec}
                      {image.technical?.audio_codec
                        ? ` · Audio: ${image.technical.audio_codec}`
                        : ""}
                    </p>
                  </section>
                  <section>
                    <h4>Metadata sources</h4>
                    {image.metadata.metadata_sources?.map((source, index) => (
                      <p key={index}>
                        {source.role === "sidecar"
                          ? source.path
                          : `Embedded · ${source.reader}`}
                      </p>
                    ))}
                  </section>
                  <section>
                    <h4>Parsers</h4>
                    {image.metadata.parsers?.map((parser) => (
                      <p key={parser.id}>
                        {parser.id} · v{parser.version}
                      </p>
                    ))}
                  </section>
                  <section>
                    <h4>Prompt fields</h4>
                    {image.prompt_documents?.map((document) => (
                      <p key={document.prompt_id}>
                        {document.label} ·{" "}
                        {String(document.provenance.node_id || "")} ·{" "}
                        {String(document.provenance.field || "positive")}
                      </p>
                    ))}
                  </section>
                  <p>
                    Original metadata is retained in Raw JSON. Sidecar conflicts
                    and extraction limits are listed below.
                  </p>
                </div>
              )}
              {tab === "prompts" && (
                <>
                  <div className="detail-seed">
                    <Parameter
                      name="Seed"
                      value={image.metadata.settings.seed?.join(" / ")}
                      onCopy={
                        image.metadata.settings.seed?.length
                          ? () =>
                              copy(
                                image.metadata.settings.seed.join(", "),
                                "Seed copied",
                              )
                          : undefined
                      }
                    />
                  </div>
                  {image.prompt_documents?.some(
                    (d) => d.scope !== "positive",
                  ) ? (
                    <div className="video-prompts">
                      {image.prompt_documents.map((document) => (
                        <section
                          className="video-prompt-document"
                          key={document.prompt_id}
                        >
                          <header>
                            <h4>{document.label}</h4>
                            <span>
                              {scopeLabel(document.scope)}
                              {document.start != null
                                ? ` · ${timeLabel(document.start)}–${timeLabel(document.end)}`
                                : document.scope === "shot"
                                  ? " · Timing unavailable"
                                  : ""}
                            </span>
                          </header>
                          <p>{document.positive}</p>
                          <div className="video-prompt-actions">
                            <button
                              className="text-button"
                              onClick={() =>
                                copy(document.positive, "Prompt copied")
                              }
                            >
                              <Copy size={13} />
                              Copy
                            </button>
                            <button
                              className="text-button"
                              onClick={() =>
                                onPromptSimilar({
                                  ...image,
                                  ...document,
                                  id: image.id,
                                })
                              }
                            >
                              <Search size={13} />
                              Find similar prompts
                            </button>
                            {image.media_kind === "video" &&
                              document.start != null && (
                                <button
                                  className="text-button"
                                  onClick={() =>
                                    setSeek({
                                      time: document.start!,
                                      nonce: Date.now(),
                                    })
                                  }
                                >
                                  <Play size={13} />
                                  Seek to shot
                                </button>
                              )}
                          </div>
                        </section>
                      ))}
                      {!image.prompt_documents.some(
                        (d) => d.scope === "global",
                      ) && (
                        <p className="muted small-text">
                          No global prompt was recorded. Shot prompts are listed
                          separately.
                        </p>
                      )}
                    </div>
                  ) : (
                    <PromptBlock
                      title="Positive prompt"
                      text={image.metadata.positive}
                      onCopy={() =>
                        copy(image.metadata.positive, "Positive prompt copied")
                      }
                    />
                  )}
                  <PromptBlock
                    title="Negative prompt"
                    text={image.metadata.negative}
                    status={image.metadata.negative_status?.state}
                    negative
                    onCopy={() =>
                      copy(image.metadata.negative, "Negative prompt copied")
                    }
                  />
                  {image.metadata.prompts.length > 0 && (
                    <details className="prompt-stages">
                      <summary>
                        <Workflow size={14} />
                        {image.metadata.prompts.length} prompt node inputs ·{" "}
                        {image.metadata.stages.length} conditioning stages
                      </summary>
                      {image.metadata.prompts.map((p, i) => (
                        <div className="stage" key={i}>
                          <div>
                            <strong>
                              #{p.node_id} · {p.title}
                            </strong>
                            <span className={p.used === false ? "muted" : ""}>
                              {p.role} ·{" "}
                              {p.used === false
                                ? "not connected"
                                : p.used === null
                                  ? "relevance unknown"
                                  : "output connected"}
                            </span>
                          </div>
                          <small>
                            {p.input} · {p.confidence} confidence
                          </small>
                          <p>{p.text}</p>
                          <button
                            className="text-button"
                            onClick={() => copy(p.text)}
                          >
                            <Copy size={12} />
                            Copy
                          </button>
                        </div>
                      ))}
                    </details>
                  )}
                </>
              )}
              {tab === "settings" && (
                <>
                  <div className="parameter-grid">
                    <Parameter
                      name="Model"
                      value={image.metadata.models.join(" · ")}
                    />
                    <Parameter
                      name="Resolution"
                      value={`${image.width} × ${image.height}`}
                      note="Measured from the image"
                    />
                    {Object.entries(label).map(([key, value]) => (
                      <Parameter
                        key={key}
                        name={value}
                        value={image.metadata.settings[key]?.join(" / ")}
                        note={
                          image.metadata.sources[key]?.length
                            ? "Node " + image.metadata.sources[key].join(", ")
                            : undefined
                        }
                        onCopy={
                          key === "seed" && image.metadata.settings.seed
                            ? () =>
                                copy(
                                  image.metadata.settings.seed.join(", "),
                                  "Seed copied",
                                )
                            : undefined
                        }
                      />
                    ))}
                    <Parameter
                      name="VAE"
                      value={image.metadata.vaes.join(" · ")}
                    />
                    <Parameter
                      name="Text encoders"
                      value={image.metadata.text_encoders.join(" · ")}
                    />
                  </div>
                  <h4 className="subheading">LoRAs</h4>
                  {image.metadata.loras.length ? (
                    image.metadata.loras.map((l, i) => (
                      <div className="lora-item" key={i}>
                        <Layers size={15} />
                        <div>
                          <strong>{l.name}</strong>
                          <small>
                            Model: {l.strength_model ?? "unavailable"} · CLIP:{" "}
                            {l.strength_clip ?? "unavailable"} · node{" "}
                            {l.node_id}
                          </small>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="muted small-text">
                      No LoRAs were reliably identified.
                    </p>
                  )}
                  <details className="raw-details">
                    <summary>All stages & additional node parameters</summary>
                    <pre>
                      {JSON.stringify(
                        {
                          stages: image.metadata.stages,
                          parameters: image.metadata.additional_parameters,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                  <button
                    className="button secondary full"
                    onClick={() =>
                      copy(
                        JSON.stringify(
                          {
                            positive: image.positive,
                            negative: image.negative,
                            models: image.metadata.models,
                            loras: image.metadata.loras,
                            settings: image.metadata.settings,
                            width: image.width,
                            height: image.height,
                            vaes: image.metadata.vaes,
                            text_encoders: image.metadata.text_encoders,
                            stages: image.metadata.stages,
                          },
                          null,
                          2,
                        ),
                        "Generation settings copied",
                      )
                    }
                  >
                    <Copy size={14} />
                    Copy all generation settings
                  </button>
                  {image.workflow_hash && (
                    <button
                      className="text-button full"
                      onClick={() =>
                        onSimilar("workflow", image.workflow_hash!)
                      }
                    >
                      Find this exact execution graph
                      <ArrowRight size={13} />
                    </button>
                  )}
                  {image.configuration_hash && (
                    <button
                      className="text-button full"
                      onClick={() =>
                        onSimilar("configuration", image.configuration_hash!)
                      }
                    >
                      Find this configuration across seeds
                      <ArrowRight size={13} />
                    </button>
                  )}
                </>
              )}
              {tab === "file" && (
                <div className="file-info">
                  <Parameter name="Original filename" value={image.filename} />
                  <Parameter
                    name="Absolute path"
                    value={image.path}
                    onCopy={() => copy(image.path, "File path copied")}
                  />
                  <Parameter
                    name="File size"
                    value={`${bytes(image.size)} (${image.size.toLocaleString()} bytes)`}
                  />
                  <Parameter
                    name="Dimensions"
                    value={`${image.width} × ${image.height}`}
                  />
                  <Parameter
                    name="Created"
                    value={new Date(image.created_at * 1000).toLocaleString()}
                    note="Filesystem timestamp"
                  />
                  <Parameter
                    name="Modified"
                    value={new Date(image.modified_at * 1000).toLocaleString()}
                  />
                  <Parameter
                    name="Generation date"
                    value={
                      image.generated_at
                        ? new Date(image.generated_at * 1000).toLocaleString()
                        : undefined
                    }
                  />
                  <button
                    className="button secondary full"
                    onClick={() =>
                      mutate(() => api("/images/" + id + "/reveal", "POST"))
                    }
                  >
                    <FolderOpen size={15} />
                    Show in original folder
                  </button>
                </div>
              )}
              {tab === "raw" && (
                <>
                  <p className="muted small-text">
                    Original embedded fields, including unknown nodes and
                    unparsed text. Metadata is displayed as text and is never
                    executed.
                  </p>
                  <div className="raw-actions">
                    <button
                      className="text-button"
                      onClick={() => copy(image.raw_json)}
                    >
                      <Copy size={13} />
                      Copy raw metadata
                    </button>
                    <a
                      className="text-button"
                      href={media(id, "workflow?kind=raw")}
                      download
                    >
                      <Download size={13} />
                      Export
                    </a>
                  </div>
                  <pre className="raw-json">{image.raw_json}</pre>
                </>
              )}
              {image.metadata.warnings.length > 0 && (
                <details
                  className="extraction-notes"
                  open={image.confidence === "unavailable"}
                >
                  <summary>
                    <CircleHelp size={14} />
                    Extraction notes ({image.metadata.warnings.length})
                  </summary>
                  {image.metadata.warnings.map((w, i) => (
                    <p key={i}>{w}</p>
                  ))}
                </details>
              )}
            </div>
            <form
              className="detail-tags"
              onSubmit={(e) => {
                e.preventDefault();
                mutate(
                  () =>
                    api("/annotations", "PATCH", {
                      image_ids: [id],
                      tags: tags.split(","),
                    }),
                  "Tags saved",
                );
              }}
            >
              <label htmlFor="image-tags">
                <Tag size={14} />
                Tags
              </label>
              <div>
                <input
                  id="image-tags"
                  value={tags}
                  onChange={(e) => setTags(e.target.value)}
                  placeholder="Add tags, separated by commas"
                />
                <button
                  type="submit"
                  className="icon-button"
                  aria-label="Save tags"
                >
                  <Check size={16} />
                </button>
              </div>
            </form>
            {collections.length > 0 && (
              <div className="detail-collections">
                <label htmlFor="image-collections">Collections</label>
                <select
                  id="image-collections"
                  value=""
                  onChange={(e) => {
                    const cid = e.target.value;
                    if (cid)
                      mutate(
                        () =>
                          api("/collections/" + cid, "PATCH", {
                            image_ids: [id],
                            remove: image.collections.includes(cid),
                          }),
                        "Collection updated",
                      );
                  }}
                >
                  <option value="">Add or remove a collection…</option>
                  {collections.map((c) => (
                    <option value={c.id} key={c.id}>
                      {image.collections.includes(c.id)
                        ? "✓ Remove from "
                        : "Add to "}
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div className="detail-actions">
              <a
                className="button primary"
                href={media(id, "original?download=true")}
                download
              >
                <Download size={15} />
                Original
              </a>
              {image.metadata.workflow ? (
                <a
                  className="button secondary"
                  href={media(id, "workflow")}
                  download
                >
                  <Workflow size={15} />
                  Workflow
                </a>
              ) : image.metadata.prompt ? (
                <a
                  className="button secondary"
                  href={media(id, "workflow?kind=prompt")}
                  download
                >
                  <Code2 size={15} />
                  API graph
                </a>
              ) : (
                <button className="button secondary" disabled>
                  <Workflow size={15} />
                  No workflow
                </button>
              )}
              <a
                className="icon-button"
                title="Open local ComfyUI"
                aria-label="Open local ComfyUI"
                href={settings?.comfy_url || "http://127.0.0.1:8188"}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink size={17} />
              </a>
            </div>
            <p className="recovery-hint">
              Drop the original image or exported workflow into ComfyUI to
              restore it.
            </p>
            {image.metadata.prompt && (
              <button
                className="text-button queue-link"
                onClick={() => setQueue(!queue)}
              >
                <Sparkles size={13} />
                Run saved graph in ComfyUI
              </button>
            )}
            {queue && (
              <div className="queue-box">
                <strong>Submit a new generation</strong>
                <p>
                  This sends the saved API graph to {settings?.comfy_url}. It
                  uses the saved seeds and requires the same models and nodes.
                  Custom nodes may perform their own actions.
                </p>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  I want to queue a new generation.
                </label>
                <button
                  className="button primary"
                  disabled={!confirmed || sending}
                  onClick={async () => {
                    setSending(true);
                    try {
                      const result = await api<{ prompt_id: string }>(
                        "/images/" + id + "/queue",
                        "POST",
                        { confirm_generation: true },
                      );
                      notify("Generation queued: " + result.prompt_id);
                      setQueue(false);
                      setConfirmed(false);
                    } catch (e) {
                      notify((e as Error).message);
                    } finally {
                      setSending(false);
                    }
                  }}
                >
                  {sending ? (
                    <LoaderCircle size={14} className="spin" />
                  ) : (
                    <Sparkles size={14} />
                  )}
                  Queue generation
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}

function PromptBlock({
  title,
  text,
  negative = false,
  status,
  onCopy,
}: {
  title: string;
  text: string;
  negative?: boolean;
  status?: NonNullable<Metadata["negative_status"]>["state"];
  onCopy: () => void;
}) {
  const absence = !text && negative ? status : undefined;
  const label =
    absence === "empty"
      ? "Explicitly empty"
      : absence === "zeroed"
        ? "Zeroed out"
        : absence === "empty_and_zeroed"
          ? "Empty / zeroed out"
          : undefined;
  const emptyText =
    absence === "empty"
      ? "Negative prompt was explicitly left empty in the workflow."
      : absence === "zeroed"
        ? "The workflow zeroed out negative conditioning."
        : absence === "empty_and_zeroed"
          ? "All recorded negative conditioning is explicitly empty or zeroed out."
          : negative
            ? "No negative prompt could be determined from the stored metadata."
            : "Unavailable in the embedded graph.";
  return (
    <section
      className={`prompt-block ${negative ? "negative" : ""}`}
      data-state={absence}
    >
      <div>
        <h4>
          <span />
          {title}
          {label && <small className="prompt-state-label">{label}</small>}
        </h4>
        <button
          className="icon-button small"
          aria-label={"Copy " + title.toLowerCase()}
          disabled={!text}
          onClick={onCopy}
        >
          <Copy size={14} />
        </button>
      </div>
      <p>{text || emptyText}</p>
    </section>
  );
}
function Parameter({
  name,
  value,
  note,
  onCopy,
}: {
  name: string;
  value?: string;
  note?: string;
  onCopy?: () => void;
}) {
  return (
    <div className="parameter">
      <span>
        {name}
        {onCopy && (
          <button
            className="icon-button small"
            aria-label={"Copy " + name.toLowerCase()}
            onClick={onCopy}
          >
            <Copy size={12} />
          </button>
        )}
      </span>
      <strong className={value ? "" : "unavailable"}>
        {value || "Unavailable"}
      </strong>
      {note && <small>{note}</small>}
    </div>
  );
}

function CompareModal({
  ids,
  onClose,
}: {
  ids: string[];
  onClose: () => void;
}) {
  const [images, setImages] = useState<ImageDetail[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    Promise.all(ids.slice(0, 4).map((id) => api<ImageDetail>("/images/" + id)))
      .then((data) => {
        if (live) setImages(data);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [ids.join(",")]);
  const fields: { name: string; get: (i: ImageDetail) => string }[] = [
    { name: "Positive prompt", get: (i) => i.positive },
    { name: "Negative prompt", get: (i) => i.negative },
    { name: "Models", get: (i) => i.metadata.models.join(", ") },
    { name: "Seed", get: (i) => i.metadata.settings.seed?.join(", ") || "" },
    {
      name: "Sampler",
      get: (i) => i.metadata.settings.sampler?.join(", ") || "",
    },
    {
      name: "Scheduler",
      get: (i) => i.metadata.settings.scheduler?.join(", ") || "",
    },
    { name: "Steps", get: (i) => i.metadata.settings.steps?.join(", ") || "" },
    { name: "CFG", get: (i) => i.metadata.settings.cfg?.join(", ") || "" },
    {
      name: "Denoise",
      get: (i) => i.metadata.settings.denoise?.join(", ") || "",
    },
    { name: "Resolution", get: (i) => `${i.width} × ${i.height}` },
    {
      name: "LoRAs & strengths",
      get: (i) =>
        i.metadata.loras
          .map(
            (l) =>
              `${l.name} (model ${l.strength_model ?? "?"}, CLIP ${l.strength_clip ?? "?"})`,
          )
          .join(", "),
    },
  ];
  return (
    <Modal title="Compare generations" onClose={onClose} wide>
      <div className="compare-body">
        <p className="muted">
          Different values are highlighted. Missing metadata stays unavailable.
        </p>
        {error ? (
          <p className="notice warning">{error}</p>
        ) : !images.length ? (
          <LoaderCircle className="spin" />
        ) : (
          <div className="compare-scroll">
            <table className="compare-table">
              <thead>
                <tr>
                  <th>Generation</th>
                  {images.map((i) => (
                    <th key={i.id}>
                      <img src={media(i.id)} alt={i.filename} />
                      <span>{i.filename}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {fields.map((f) => {
                  const differs = new Set(images.map(f.get)).size > 1;
                  return (
                    <tr className={differs ? "differs" : ""} key={f.name}>
                      <th>
                        {differs && <span className="diff-dot" />}
                        {f.name}
                      </th>
                      {images.map((i) => (
                        <td key={i.id}>
                          {f.get(i) || (
                            <span className="muted">Unavailable</span>
                          )}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Modal>
  );
}

export default App;
