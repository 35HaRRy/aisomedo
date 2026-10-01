import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { tr } from "../i18n";
import { useOnboarding } from "./useOnboarding";

export function useDraft<T>(source: T | null, initial: T) {
  const [draft, setDraft] = useState(initial);
  const [dirty, setDirty] = useState(false);
  const [baseline, setBaseline] = useState("");
  const fingerprint = JSON.stringify(source);
  useEffect(() => {
    if (source && !dirty) { setDraft(source); setBaseline(fingerprint); }
  }, [fingerprint, dirty]);
  return { draft, dirty, changed: dirty && baseline !== fingerprint,
    edit: (value: T) => { setDirty(true); setDraft(value); },
    reload: () => { if (source) { setDraft(source); setBaseline(fingerprint); setDirty(false); } },
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
  return changed ? <div className="notice" role="status"><p>Başka bir cihaz ayarları değiştirdi. Taslağınız korunuyor.</p><button type="button" onClick={reload}>Sunucudaki değerleri yükle</button></div> : null;
}

export function imageError(file: File): string | null {
  return !["image/png", "image/jpeg"].includes(file.type) ? "PNG veya JPEG görsel seçin."
    : file.size > 10 * 1024**2 ? "Görsel en fazla 10 MiB olabilir." : null;
}
export function AssetPreview({ reference, label }: { reference: string | null; label: string }) {
  if (!reference) return null;
  const generated = /^branding\/assets\/[0-9a-f]{32}\.(png|jpg)$/.test(reference);
  return <><p>{label} tanımlı</p>{generated && <img className="branding-preview" src={`/api/settings/branding/assets/${reference.split("/").pop()}`} alt={`${label} önizlemesi`} />}</>;
}
