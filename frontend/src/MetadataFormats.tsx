import { useEffect, useState } from "react";
import { api } from "./api";

type Capabilities = {
  metadata_schema: number;
  video_available: boolean;
  readers: { id: string; version: number; extensions: string[] }[];
  parsers: { id: string; version: number }[];
};
export function MetadataFormats() {
  const [value, setValue] = useState<Capabilities | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<Capabilities>("/capabilities", "GET", undefined, controller.signal)
      .then(setValue)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, []);
  return (
    <section className="settings-maintenance metadata-summary">
      <h3>Media & metadata formats</h3>
      {value ? (
        <>
          <p>
            Schema {value.metadata_schema}. Formats and workflow adapters are
            detected automatically.
          </p>
          {value.readers.map((reader) => (
            <p key={reader.id}>
              <strong>{reader.id}</strong> · v{reader.version}
              <br />
              {reader.extensions.join(", ")}
            </p>
          ))}
          <p>
            Workflow parsers:{" "}
            {value.parsers
              .map((parser) => `${parser.id} v${parser.version}`)
              .join(", ")}
          </p>
          <p>
            Video processing:{" "}
            {value.video_available
              ? "FFmpeg and ffprobe available."
              : "Install FFmpeg and ffprobe on PATH, then restart the gallery. Images continue to work without them."}
          </p>
          <p>
            Metadata can come from embedded fields or JSON files named after the
            media file. The Metadata tab on each file shows which sources and
            parsers were used.
          </p>
        </>
      ) : (
        <p>{error || "Loading supported formats…"}</p>
      )}
    </section>
  );
}
