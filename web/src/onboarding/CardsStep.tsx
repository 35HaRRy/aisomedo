import { useId, useState } from "react";
import { api } from "../api/client";
import type { BrandingPatchIn } from "../api/openapi";
import { tr } from "../i18n";
import { useLiveData } from "../useLiveData";
import { AssetPreview, cardMediaError, ReloadDraft, StepActions, useDraft, useFormSave } from "./forms";

type CardKind = "intro" | "outro";
export function CardsStep({ onSaved, onboarding = true }: { onSaved: () => void; onboarding?: boolean }) {
  const formId = useId();
  const snapshot = useLiveData(api.branding, true, ["settings"]);
  const form = useFormSave(onSaved);
  const state = useDraft(snapshot.data ? { intro: snapshot.data.intro_duration?.toString() ?? "", outro: snapshot.data.outro_duration?.toString() ?? "", introAsset: snapshot.data.intro_asset ?? null, outroAsset: snapshot.data.outro_asset ?? null } : null, { intro: "", outro: "", introAsset: null as string | null, outroAsset: null as string | null });
  const [files, setFiles] = useState<Partial<Record<CardKind, File>>>({});
  const [removed, setRemoved] = useState<Partial<Record<CardKind, boolean>>>({});
  const [fileKey, setFileKey] = useState(0);
  async function submit() {
    if (!snapshot.data) return;
    const changes: BrandingPatchIn = {};
    for (const kind of ["intro", "outro"] as const) {
      const assetKey = `${kind}_asset` as const;
      const durationKey = `${kind}_duration` as const;
      if (removed[kind]) { changes[assetKey] = null; changes[durationKey] = null; continue; }
      const value = state.draft[kind];
      if (value && (!/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value)))) { form.setError("Kart süresi sıfırdan büyük bir tam sayı olmalı."); return; }
      if (value && !files[kind] && !snapshot.data[assetKey]) { form.setError("Süre tanımlamadan önce kart görseli seçin."); return; }
      const current = snapshot.data[durationKey]?.toString() ?? "";
      if (value !== current) changes[durationKey] = value ? Number(value) : null;
    }
    void form.run(async signal => {
      for (const kind of ["intro", "outro"] as const) {
        if (!files[kind] || removed[kind]) continue;
        const uploaded = await api.uploadBranding(files[kind]!, signal);
        if (signal.aborted) throw new DOMException("", "AbortError");
        changes[`${kind}_asset`] = uploaded.asset;
      }
      if (Object.keys(changes).length) await api.patchBranding(changes, signal);
      if (signal.aborted) throw new DOMException("", "AbortError");
      if (onboarding) return api.skipCards(signal);
    });
  }
  return <div className="onboarding-form"><p>Giriş ve çıkış kartları isteğe bağlı. Süre boş bırakılırsa varsayılan fotoğraf süresi kullanılır.</p>
    {snapshot.error && <div role="alert">{tr.loadError}<StepActions><button onClick={snapshot.retry}>{tr.retry}</button></StepActions></div>}
    <ReloadDraft changed={state.changed} reload={() => { state.reload(); setFiles({}); setRemoved({}); setFileKey(value => value + 1); }} />
    <form id={formId} onSubmit={event => { event.preventDefault(); void submit(); }}>
      <div className="optional-cards">
      {(["intro", "outro"] as const).map(kind => {
        const label = kind === "intro" ? "Giriş" : "Çıkış";
        return <fieldset className="optional-card" key={kind} disabled={form.busy}><legend>{label} kartı</legend>
          {!removed[kind] && (files[kind] || snapshot.data?.[`${kind}_asset`]) && <button className="card-remove icon-button" type="button" aria-label={`${label} kartını kaldır`} title={`${label} kartını kaldır`} onClick={() => { setRemoved(value => ({ ...value, [kind]: true })); setFiles(value => ({ ...value, [kind]: undefined })); setFileKey(value => value + 1); state.edit({ ...state.draft, [kind]: "" }); }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7" /></svg>
          </button>}
          {!removed[kind] && <AssetPreview reference={snapshot.data?.[`${kind}_asset`] ?? null} label={`${label} kartı`} file={files[kind] ?? null} />}
          <label htmlFor={`${kind}-file`}>{label} görseli</label><input key={fileKey} id={`${kind}-file`} type="file" accept=".png,.jpg,.jpeg,.mp4,.mov,.webm,.mkv,.avi,image/png,image/jpeg,video/mp4,video/quicktime,video/webm,video/x-matroska,video/x-msvideo" onChange={event => {
            const chosen = event.target.files?.[0]; if (!chosen) return;
            const error = cardMediaError(chosen); form.setError(error); if (error) return;
            setFiles(value => ({ ...value, [kind]: chosen })); setRemoved(value => ({ ...value, [kind]: false })); state.edit(state.draft);
          }} />
          <small>PNG/JPEG veya MP4, MOV, WebM, MKV, AVI · En fazla 10 MiB.</small>
          <label htmlFor={`${kind}-duration`}>{label} süresi (saniye)</label><input id={`${kind}-duration`} type="number" inputMode="numeric" min="1" step="1" value={state.draft[kind]} onChange={event => {
            const value = event.target.value;
            if (value === "" || /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value))) state.edit({ ...state.draft, [kind]: value });
          }} />
        </fieldset>;
      })}
      </div>
      <StepActions><button form={formId} className="primary" disabled={form.busy || !snapshot.data || snapshot.error}>{form.busy ? "Kaydediliyor…" : "Kartları kaydet"}</button>
      {onboarding && <button type="button" disabled={form.busy} onClick={() => void form.run(signal => api.skipCards(signal))}>Kartları değiştirmeden devam et</button>}</StepActions>
    </form>
    {form.error && <p role="alert">{form.error}</p>}
  </div>;
}
