import { api } from "../api/client";
import { tr } from "../i18n";
import { useLiveData } from "../useLiveData";
import { ReloadDraft, useDraft, useFormSave } from "./forms";

export function PlanStep({ onSaved }: { onSaved: () => void }) {
  const snapshot = useLiveData(api.plan);
  const form = useFormSave(onSaved);
  const state = useDraft(snapshot.data ? { anchor_date: snapshot.data.anchor_date ?? "", anchor_time: snapshot.data.anchor_time?.slice(0, 5) ?? "", enabled: snapshot.data.enabled } : null,
    { anchor_date: "", anchor_time: "", enabled: false });
  const { draft, edit } = state;
  function submit() {
    const date = new Date(`${draft.anchor_date}T12:00:00Z`);
    if (!draft.anchor_date || Number.isNaN(date.getTime()) || date.getUTCDay() !== 1) { form.setError("İlk yayın tarihi Pazartesi olmalı."); return; }
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(draft.anchor_time)) { form.setError("Geçerli bir yayın saati seçin."); return; }
    void form.run(signal => api.savePlan(draft, signal));
  }
  return <div className="onboarding-form"><p>Her iki haftada bir Pazartesi yayın. Saat dilimi: Europe/Istanbul.</p>
    {snapshot.data?.anchor_date && <p>{snapshot.data.enabled ? "Plan etkin" : "Plan tanımlı, yayın kapalı"}</p>}
    {snapshot.error && <div role="alert">{tr.loadError}<button onClick={snapshot.retry}>{tr.retry}</button></div>}
    <ReloadDraft changed={state.changed} reload={state.reload} />
    <form onSubmit={event => { event.preventDefault(); submit(); }}>
      <label htmlFor="plan-date">İlk yayın tarihi</label><input id="plan-date" type="date" required value={draft.anchor_date} onChange={event => edit({ ...draft, anchor_date: event.target.value })} disabled={form.busy} />
      <label htmlFor="plan-time">Yayın saati</label><input id="plan-time" type="time" required value={draft.anchor_time} onChange={event => edit({ ...draft, anchor_time: event.target.value })} disabled={form.busy} />
      <label className="checkbox-label"><input type="checkbox" checked={draft.enabled} onChange={event => edit({ ...draft, enabled: event.target.checked })} disabled={form.busy} />Düzenli yayını etkinleştir</label>
      <button className="primary" disabled={form.busy || !snapshot.data || snapshot.error}>{form.busy ? "Kaydediliyor…" : "Planı kaydet"}</button>
    </form>{form.error && <p role="alert">{form.error}</p>}
  </div>;
}
