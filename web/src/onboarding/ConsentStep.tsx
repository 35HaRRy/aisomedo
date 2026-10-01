import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { formatDate, tr } from "../i18n";
import { useLiveData } from "../useLiveData";
import { useOnboarding } from "./useOnboarding";

export function ConsentStep({ onSaved }: { onSaved: () => void }) {
  const { save } = useOnboarding();
  const load = useCallback(async (signal: AbortSignal) => {
    try { return { policy: await api.consent(signal) }; }
    catch (failure) { if (failure instanceof ApiError && failure.status === 404) return { policy: null }; throw failure; }
  }, []);
  const snapshot = useLiveData(load);
  const [acknowledgedVersion, setAcknowledgedVersion] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<{ version: number; accepted_at: string } | null>(null);
  const alive = useRef(true);
  const flight = useRef<AbortController | null>(null);
  useEffect(() => { alive.current = true; return () => { alive.current = false; flight.current?.abort(); }; }, []);
  const policy = snapshot.data?.policy;
  const acceptedAt = policy?.accepted_at ?? (accepted?.version === policy?.version ? accepted?.accepted_at : null);
  async function accept() {
    if (!policy || busy || acknowledgedVersion !== policy.version || acceptedAt) return;
    setBusy(true); setError(null);
    const controller = new AbortController(); flight.current = controller;
    try {
      const result = await save(async signal => {
        const cancel = () => controller.abort();
        signal.addEventListener("abort", cancel, { once: true });
        try {
          const value = await api.acceptConsent(policy.version, controller.signal);
          if (!alive.current || controller.signal.aborted) throw new DOMException("", "AbortError");
          return value;
        } finally { signal.removeEventListener("abort", cancel); }
      });
      if (alive.current) { setAccepted(result); onSaved(); }
    }
    catch (failure) {
      if (!alive.current) return;
      if (failure instanceof ApiError && failure.status === 409) {
        setAcknowledgedVersion(null); setError(tr.consentChanged); snapshot.retry();
      } else setError(tr.connectionError);
    } finally { if (alive.current) setBusy(false); }
  }
  return <div className="onboarding-form">
    {snapshot.error && <div role="alert">{tr.loadError}<button onClick={snapshot.retry}>{tr.retry}</button></div>}
    {!snapshot.data && !snapshot.error && <p role="status">{tr.loading}</p>}
    {snapshot.data && !policy && <><p>{tr.consentMissing}</p><button onClick={snapshot.retry}>{tr.retry}</button></>}
    {policy && <><p>Rıza metni · Sürüm {policy.version}</p><div className="consent-text">{policy.text}</div>
      {acceptedAt ? <p role="status">Rıza kaydedildi · {formatDate(acceptedAt)}</p> : <form onSubmit={event => { event.preventDefault(); void accept(); }}>
        <label className="checkbox-label"><input type="checkbox" checked={acknowledgedVersion === policy.version} disabled={busy || snapshot.error} onChange={event => setAcknowledgedVersion(event.target.checked ? policy.version : null)} />Metni okudum ve medya kullanımına rıza veriyorum.</label>
        <button className="primary" disabled={busy || snapshot.error || acknowledgedVersion !== policy.version}>{busy ? "Kaydediliyor…" : "Rızayı kaydet"}</button>
      </form>}</>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
