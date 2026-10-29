import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ApiError } from "../api/client";
import { MediaPreview, useFilePreview } from "../components/MediaPreview";
import { tr } from "../i18n";
import { useOnboarding } from "./useOnboarding";
import { getDemoRuntime } from "../demo/runtime";
import { demoAssetUrl, demoAssetType } from "../demo/assets";

export const SetupActionTarget = createContext<HTMLElement | null>(null);
export function StepActions({ children }: { children: ReactNode }) {
  const target = useContext(SetupActionTarget);
  return target ? createPortal(children, target) : <div className="step-actions">{children}</div>;
}

export function useDraft<T>(source: T | null, initial: T) {
  const [draft, setDraft] = useState(initial);
  const [dirty, setDirty] = useState(false);
  const [baseline, setBaseline] = useState("");
  const fingerprint = JSON.stringify(source);
  // Hydrate before committing enabled inputs; an effect leaves an editable empty draft.
  if (source && !dirty && baseline !== fingerprint) {
    setDraft(source); setBaseline(fingerprint);
  }
  return { draft, dirty, changed: dirty && baseline !== fingerprint,
    edit: (value: T) => { setDirty(true); setDraft(value); },
    reload: () => { if (source) { setDraft(source); setBaseline(fingerprint); setDirty(false); } },
    markSaved: () => { setDirty(false); setBaseline(fingerprint); },
  };
}

export function useFormSave(onSaved: () => void) {
  const { save } = useOnboarding();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const flight = useRef<AbortController | null>(null);
  const lock = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; flight.current?.abort(); }; }, []);
  async function run(operation: (signal: AbortSignal) => Promise<unknown>, failureCopy?: string) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null);
    const controller = new AbortController(); flight.current = controller;
    try {
      await save(async signal => {
        const cancel = () => controller.abort(); signal.addEventListener("abort", cancel, { once: true });
        try {
          const value = await operation(controller.signal);
          if (controller.signal.aborted || !alive.current) throw new DOMException("", "AbortError");
          return value;
        } finally { signal.removeEventListener("abort", cancel); }
      });
      if (alive.current) onSaved();
    } catch (failure) {
      if (alive.current) setError(failure instanceof ApiError && failure.status === 422 ? failureCopy ?? "Değerler kaydedilemedi. Bilgileri kontrol edip tekrar deneyin." : tr.connectionError);
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  return { busy, error, setError, run };
}

export function ReloadDraft({ changed, reload }: { changed: boolean; reload: () => void }) {
  return changed ? <div className="notice" role="status"><p>Başka bir cihaz ayarları değiştirdi. Taslağınız korunuyor.</p><StepActions><button type="button" onClick={reload}>Sunucudaki değerleri yükle</button></StepActions></div> : null;
}

export function imageError(file: File): string | null {
  return !["image/png", "image/jpeg"].includes(file.type) ? "PNG veya JPEG görsel seçin."
    : file.size > 10 * 1024**2 ? "Görsel en fazla 10 MiB olabilir." : null;
}
export function cardMediaError(file: File): string | null {
  return !["image/png", "image/jpeg", "video/mp4", "video/quicktime", "video/webm", "video/x-matroska", "video/x-msvideo"].includes(cardContentType(file))
    ? "PNG/JPEG görsel veya MP4, MOV, WebM, MKV, AVI video seçin."
    : file.size > 10 * 1024**2 ? "Kart medyası en fazla 10 MiB olabilir." : null;
}
function cardContentType(file: File): string {
  const types: Record<string, string> = { png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", mp4: "video/mp4", mov: "video/quicktime", webm: "video/webm", mkv: "video/x-matroska", avi: "video/x-msvideo" };
  return file.type || types[file.name.split(".").pop()?.toLowerCase() ?? ""] || "";
}
export function AssetPreview({ reference, label, file = null }: { reference: string | null; label: string; file?: File | null }) {
  const local = useFilePreview(file);
  const selected = `Seçilen ${label.toLocaleLowerCase("tr")} önizlemesi`;
  if (local && file) return <><p>{selected}</p><MediaPreview src={local} contentType={cardContentType(file)} label={selected} /></>;
  if (!reference) return null;
  if (getDemoRuntime()) return <MediaPreview src={demoAssetUrl(reference)} contentType={demoAssetType(reference)} label={`${label} önizlemesi`} />;
  const generated = /^branding\/assets\/[0-9a-f]{32}\.(png|jpg|mp4|mov|webm|mkv|avi)$/.test(reference);
  const contentType = /\.(mp4|mov|webm|mkv|avi)$/.test(reference) ? "video/mp4" : "image/png";
  return <><p>{label} tanımlı</p>{generated && <MediaPreview src={`/api/settings/branding/assets/${reference.split("/").pop()}`} contentType={contentType} label={`${label} önizlemesi`} />}</>;
}
