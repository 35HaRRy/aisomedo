import { api } from "../api/client";
import { tr } from "../i18n";
import { ReloadDraft, useDraft, useFormSave } from "../onboarding/forms";
import { useLiveData } from "../useLiveData";

export function ReminderSettings({ onSaved }: { onSaved: () => void }) {
  const snapshot = useLiveData(api.reminders);
  const state = useDraft(snapshot.data ? {
    interval: String(snapshot.data.interval_minutes), start: snapshot.data.delivery_start.slice(0, 5), end: snapshot.data.delivery_end.slice(0, 5),
  } : null, { interval: "", start: "", end: "" });
  const form = useFormSave(onSaved);
  const copy = tr.settingsPage;
  function submit() {
    const interval = Number(state.draft.interval);
    if (!Number.isSafeInteger(interval) || interval <= 0) { form.setError(copy.invalidInterval); return; }
    const time = /^([01]\d|2[0-3]):[0-5]\d$/;
    if (!time.test(state.draft.start) || !time.test(state.draft.end) || state.draft.start === state.draft.end) { form.setError(copy.invalidWindow); return; }
    void form.run(signal => api.saveReminders({ interval_minutes: interval, delivery_start: state.draft.start, delivery_end: state.draft.end, timezone: "Europe/Istanbul" }, signal), copy.reminderRejected);
  }
  return <div className="onboarding-form">
    <p>{copy.reminderHelp}</p><small>{tr.timezone}</small>
    {!snapshot.data && !snapshot.error && <p role="status">{tr.loading}</p>}
    {snapshot.error && <div role="alert">{snapshot.data ? tr.stale : tr.loadError}<button onClick={snapshot.retry}>{tr.retry}</button></div>}
    <ReloadDraft changed={state.changed} reload={state.reload} />
    <form onSubmit={event => { event.preventDefault(); submit(); }}>
      <fieldset disabled={form.busy || !snapshot.data || snapshot.error}>
        <label htmlFor="reminder-interval">{copy.interval}</label><input id="reminder-interval" type="number" min="1" step="1" required value={state.draft.interval} onChange={event => state.edit({ ...state.draft, interval: event.target.value })} />
        <label htmlFor="reminder-start">{copy.deliveryStart}</label><input id="reminder-start" type="time" required value={state.draft.start} onChange={event => state.edit({ ...state.draft, start: event.target.value })} />
        <label htmlFor="reminder-end">{copy.deliveryEnd}</label><input id="reminder-end" type="time" required value={state.draft.end} onChange={event => state.edit({ ...state.draft, end: event.target.value })} />
        <button className="primary">{form.busy ? copy.saving : copy.saveReminders}</button>
      </fieldset>
    </form>{form.error && <p role="alert">{form.error}</p>}
  </div>;
}
