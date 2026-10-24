import { useEffect, useRef, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { api, media, type ImageItem } from "./api";

type Playback = {
  state: string;
  url?: string;
  error?: string;
  proxy?: boolean;
};
export function VideoPlayer({
  item,
  seek,
}: {
  item: ImageItem;
  seek: { time: number; nonce: number } | null;
}) {
  const [state, setState] = useState<Playback | null>(null);
  const [failed, setFailed] = useState(false);
  const [compatible, setCompatible] = useState(false);
  const [retry, setRetry] = useState(0);
  const video = useRef<HTMLVideoElement>(null);
  const requestedSeek = useRef(seek);
  requestedSeek.current = seek;
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setState(null);
    setFailed(false);
    let requestRetry = retry > 0;
    const poll = async () => {
      try {
        const value = await api<Playback>(
          `/images/${item.id}/playback?compatible=${compatible}&retry=${requestRetry}`,
          "POST",
          undefined,
          controller.signal,
        );
        requestRetry = false;
        if (controller.signal.aborted) return;
        setState(value);
        if (value.state === "processing") timer = setTimeout(poll, 1500);
      } catch (e) {
        if (!controller.signal.aborted)
          setState({ state: "error", error: (e as Error).message });
      }
    };
    poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [item.id, compatible, retry]);
  const applySeek = () => {
    if (video.current && requestedSeek.current && video.current.readyState > 0)
      video.current.currentTime = Math.min(
        requestedSeek.current.time,
        Math.max(0, video.current.duration - 0.01),
      );
  };
  useEffect(applySeek, [seek]);
  return (
    <div className="video-player">
      {state?.state === "ready" && !failed ? (
        <>
          <video
            ref={video}
            aria-label="Video playback"
            controls
            playsInline
            preload="metadata"
            poster={media(item.id)}
            src={state.url}
            onLoadedMetadata={applySeek}
            onError={() => setFailed(true)}
          />
          {state.proxy && (
            <p className="video-note">
              Playback uses a cached compatible copy. The original is available
              for download.
            </p>
          )}
        </>
      ) : (
        <div className="video-pending">
          <img src={media(item.id)} alt="Video preview" />
          <div>
            {state?.state === "error" || failed ? (
              <>
                <p role="alert">
                  {state?.error || "The browser could not play this video."}
                </p>
                <button
                  className="button secondary"
                  onClick={() => {
                    setCompatible(true);
                    setRetry((n) => n + 1);
                  }}
                >
                  Prepare compatible playback
                </button>
                <a
                  className="text-button"
                  href={media(item.id, "original?download=true")}
                >
                  Download original
                </a>
              </>
            ) : (
              <p role="status">
                <LoaderCircle size={18} className="spin" />
                {state?.state === "processing"
                  ? "Preparing a compatible video for playback…"
                  : "Loading video…"}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
