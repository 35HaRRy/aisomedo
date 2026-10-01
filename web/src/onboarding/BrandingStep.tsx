import { useState } from "react";
import { api } from "../api/client";
import { tr } from "../i18n";
import { useLiveData } from "../useLiveData";
import { AssetPreview, imageError, ReloadDraft, useDraft, useFormSave } from "./forms";

export function BrandingStep({ kind, onSaved }: { kind: "logo" | "caption_template"; onSaved: () => void }) {
  const snapshot = useLiveData(api.branding);
  const state = useDraft(snapshot.data ? { caption: snapshot.data.caption_template ?? "" } : null, { caption: "" });
  const form = useFormSave(onSaved);
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0);
  const [stage, setStage] = useState<"upload" | "install">("upload");
  function submit() {
    if (kind === "caption_template") {
      if (!state.draft.caption.trim()) { form.setError("Açıklama şablonu boş olamaz."); return; }
      void form.run(signal => api.patchBranding({ caption_template: state.draft.caption }, signal));
    } else if (file) {
      setStage("upload");
      void form.run(async signal => {
        const uploaded = await api.uploadBranding(file, signal);
        if (signal.aborted) throw new DOMException("", "AbortError");
        setStage("install");
        return api.patchBranding({ logo_asset: uploaded.asset }, signal);
      }, "Görsel doğrulanamadı veya kaydedilemedi. PNG/JPEG ve en fazla 4096 piksel kullanın.");
    }
  }
  return <div className="onboarding-form">
    {snapshot.error && <div role="alert">{tr.loadError}<button onClick={snapshot.retry}>{tr.retry}</button></div>}
    <ReloadDraft changed={state.changed} reload={() => { state.reload(); setFile(null); setFileKey(value => value + 1); }} />
    <form onSubmit={event => { event.preventDefault(); submit(); }}>
      {kind === "logo" ? <><p>PNG/JPEG · En fazla 10 MiB ve 4096 × 4096 piksel. Şeffaf PNG logo kullanabilirsiniz.</p>
        <AssetPreview reference={snapshot.data?.logo_asset ?? null} label="Logo" />
        <label htmlFor="logo-file">Logo görseli</label><input key={fileKey} id="logo-file" type="file" accept="image/png,image/jpeg" disabled={form.busy} onChange={event => {
          const chosen = event.target.files?.[0] ?? null;
          const error = chosen ? imageError(chosen) : null; form.setError(error); setFile(error ? null : chosen);
          if (chosen) state.edit(state.draft);
        }} /></> : <><p>Yeni paketlerin açıklaması bu şablondan oluşturulur. Mevcut paketler değişmez.</p>
        <label htmlFor="caption-template">Açıklama şablonu</label><textarea id="caption-template" required value={state.draft.caption} disabled={form.busy} onChange={event => state.edit({ caption: event.target.value })} /></>}
      <button className="primary" disabled={form.busy || !snapshot.data || snapshot.error || (kind === "logo" && !file)}>{form.busy ? stage === "upload" && kind === "logo" ? "Görsel yükleniyor…" : "Kaydediliyor…" : kind === "logo" ? "Logoyu kaydet" : "Açıklamayı kaydet"}</button>
    </form>{form.error && <p role="alert">{kind === "logo" ? stage === "upload" ? "Görsel yüklenemedi. " : "Logo yüklenmiş olsa da ayar kaydedilemedi. " : ""}{form.error}</p>}
  </div>;
}
