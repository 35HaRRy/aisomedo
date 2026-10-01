import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { AttemptOut, StatusOut } from "../api/openapi";
import { tr } from "../i18n";
import { startLiveRefresh } from "../live";
import { useLiveData } from "../useLiveData";
import { useOnboarding } from "./useOnboarding";

export function InstagramStep({ onSaved }: { onSaved: () => void }) {
  const { save } = useOnboarding();
  const snapshot = useLiveData(api.instagram);
  const [verified, setVerified] = useState<StatusOut | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<AttemptOut["candidates"]>([]);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const alive = useRef(true);
  const flight = useRef<AbortController | null>(null);
  const lock = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; flight.current?.abort(); }; }, []);
  const message = (failure: unknown) => failure instanceof ApiError && failure.status === 422 ? tr.tokenInvalid
    : failure instanceof ApiError && failure.status === 503 ? tr.instagramUnconfigured : tr.instagramUnavailable;
  async function mutate<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
    const controller = new AbortController(); flight.current = controller;
    return save(async signal => {
      const cancel = () => controller.abort();
      signal.addEventListener("abort", cancel, { once: true });
      try {
        const result = await operation(controller.signal);
        if (!alive.current || controller.signal.aborted) throw new DOMException("", "AbortError");
        return result;
      } finally { signal.removeEventListener("abort", cancel); }
    });
  }
  async function connect() {
    if (lock.current || !token.trim()) return;
    lock.current = true; setBusy(true); setError(null);
    const submitted = token;
    setToken(""); // Never retain a submitted secret in component state.
    setAttempt(null); setCandidates([]); setAuthUrl(null);
    try { const result = await mutate(signal => api.connectInstagramToken(submitted, signal));
      if (alive.current) { setVerified(result); onSaved(); }
    } catch (failure) { if (alive.current) setError(message(failure)); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function start() {
    if (lock.current) return;
    lock.current = true; setBusy(true); setToken(""); setError(null); setCandidates([]); setAttempt(null); setAuthUrl(null);
    try {
      const result = await mutate(signal => api.startOAuth(signal));
      if (!alive.current) return;
      const url = new URL(result.auth_url);
      if (url.protocol !== "https:") throw new Error("unsafe authorization URL");
      setAuthUrl(url.href); setAttempt(result.attempt_id);
      window.open(url.href, "_blank", "noopener,noreferrer");
    } catch (failure) { if (alive.current) setError(message(failure)); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  useEffect(() => {
    if (!attempt) return;
    let active = true;
    const stop = startLiveRefresh(async signal => {
      try {
        const result = await api.oauthAttempt(attempt, signal);
        if (!active || signal.aborted) return;
        if (result.status === "completed" && result.candidates.length) {
          setCandidates(result.candidates); setAttempt(null);
        } else if (result.status !== "pending") { setError(tr.oauthFailed); setAttempt(null); }
      } catch (failure) {
        if (!active || signal.aborted) return;
        setError(failure instanceof ApiError && failure.status === 503 ? tr.instagramUnconfigured : tr.oauthFailed);
        setAttempt(null);
      }
    });
    return () => { active = false; stop(); };
  }, [attempt]);
  async function select(id: string) {
    if (lock.current || !authUrl) return;
    lock.current = true; setBusy(true); setError(null);
    try {
      const result = await mutate(signal => api.selectInstagramAccount(candidateAttempt.current, id, signal));
      if (alive.current) { setVerified(result); setCandidates([]); setAuthUrl(null); onSaved(); }
    } catch (failure) { if (alive.current) setError(message(failure)); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  const candidateAttempt = useRef("");
  if (attempt) candidateAttempt.current = attempt;
  const status = verified ?? snapshot.data;
  return <div className="onboarding-form">
    <p>Instagram’dan kendi aldığınız erişim tokenını tanımlayın veya yeni pencerede yetkilendirin. Mevcut hesap yeni bağlantı doğrulanana kadar korunur.</p>
    {status?.ig_username && <p>@{status.ig_username} · {status.health === "healthy" ? "Bağlantı doğrulandı" : "Yeniden bağlantı gerekli"}</p>}
    {snapshot.error && <div role="alert">{tr.instagramUnavailable}<button onClick={snapshot.retry}>{tr.retry}</button></div>}
    {error && <p role="alert">{error}</p>}
    <form onSubmit={event => { event.preventDefault(); void connect(); }}>
      <label htmlFor="instagram-token">Instagram erişim tokenı</label>
      <input id="instagram-token" type="password" autoComplete="off" spellCheck={false} value={token} maxLength={16384} disabled={busy} onChange={event => setToken(event.target.value)} />
      <small>Token yalnızca doğrulama için sunucuya gönderilir; tarayıcıda saklanmaz.</small>
      <button className="primary" disabled={busy || !token.trim()}>{busy ? "Bağlantı doğrulanıyor…" : "Token ile bağlan"}</button>
    </form>
    <button disabled={busy} onClick={() => void start()}>Instagram ile yetkilendir</button>
    {authUrl && <a href={authUrl} target="_blank" rel="noopener noreferrer">Yetkilendirme sayfasını aç</a>}
    {attempt && <p role="status">Yeni pencerede yetkilendirmeyi tamamlayın. Bu sayfa sonucu kontrol ediyor.</p>}
    {candidates.map(candidate => <button key={candidate.ig_user_id} disabled={busy} onClick={() => void select(candidate.ig_user_id)}>@{candidate.ig_username} hesabını seç</button>)}
  </div>;
}
