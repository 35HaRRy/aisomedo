import { useEffect, useState } from "react";

export function useFilePreview(file: File | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) { setUrl(null); return; }
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return url;
}

export function MediaPreview({ src, contentType, label }: { src: string; contentType: string; label: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  if (failed) return null;
  if (contentType.startsWith("video/")) return <video className="media-preview" src={`${src}#t=0.1`} aria-label={label}
    muted playsInline preload="metadata" onError={() => setFailed(true)} />;
  return <img className="media-preview" src={src} alt={label} onError={() => setFailed(true)} />;
}
