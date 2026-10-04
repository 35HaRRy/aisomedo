import { useState } from "react";
import { api } from "../api/client";
import type { BrandingPatchIn } from "../api/openapi";
import { tr } from "../i18n";
import { useLiveData } from "../useLiveData";
import { AssetPreview, imageError, ReloadDraft, useDraft, useFormSave } from "./forms";

type CardKind = "intro" | "outro";
export function CardsStep({ onSaved, onboarding = true }: { onSaved: () => void; onboarding?: boolean }) {
  const snapshot = useLiveData(api.branding);
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
      if (value && (!Number.isFinite(Number(value)) || Number(value) <= 0)) { form.setError("Kart süresi pozitif ve sonlu bir sayı olmalı."); return; }
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
    {snapshot.error && <div role="alert">{tr.loadError}<button onClick={snapshot.retry}>{tr.retry}</button></div>}
    <ReloadDraft changed={state.changed} reload={() => { state.reload(); setFiles({}); setRemoved({}); setFileKey(value => value + 1); }} />
    <form onSubmit={event => { event.preventDefault(); void submit(); }}>
      {(["intro", "outro"] as const).map(kind => {
        const label = kind === "intro" ? "Giriş" : "Çıkış";
        return <fieldset key={kind} disabled={form.busy}><legend>{label} kartı</legend>
          {!removed[kind] && <AssetPreview reference={snapshot.data?.[`${kind}_asset`] ?? null} label={`${label} kartı`} />}
          <label htmlFor={`${kind}-file`}>{label} görseli</label><input key={fileKey} id={`${kind}-file`} type="file" accept="image/png,image/jpeg" onChange={event => {
            const chosen = event.target.files?.[0]; if (!chosen) return;
            const error = imageError(chosen); form.setError(error); if (error) return;
            setFiles(value => ({ ...value, [kind]: chosen })); setRemoved(value => ({ ...value, [kind]: false })); state.edit(state.draft);
          }} />
          <label htmlFor={`${kind}-duration`}>{label} süresi (saniye)</label><input id={`${kind}-duration`} type="number" min="0.01" step="any" value={state.draft[kind]} onChange={event => state.edit({ ...state.draft, [kind]: event.target.value })} />
          <button type="button" onClick={() => { setRemoved(value => ({ ...value, [kind]: true })); state.edit({ ...state.draft, [kind]: "" }); }}>{label} kartını kaldır</button>
        </fieldset>;
      })}
      <button className="primary" disabled={form.busy || !snapshot.data || snapshot.error}>{form.busy ? "Kaydediliyor…" : "Kartları kaydet"}</button>
    </form>{onboarding && <button disabled={form.busy} onClick={() => void form.run(signal => api.skipCards(signal))}>Kartları değiştirmeden devam et</button>}
    {form.error && <p role="alert">{form.error}</p>}
  </div>;
}
