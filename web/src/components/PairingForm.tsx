import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { tr } from "../i18n";
import { useSession } from "../session";
import { ThemeToggle } from "../theme";
import { SocialLinks } from "./SocialLinks";
import { BrandLogo } from "./BrandLogo";

export function PairingForm() {
  const { pair } = useSession();
  const [code, setCode] = useState("");
  const [previewCode, setPreviewCode] = useState("");
  const trimmedCode = code.trim();
  useEffect(() => {
    if (trimmedCode.length !== 8) return;
    const timer = window.setTimeout(() => setPreviewCode(trimmedCode), 350);
    return () => window.clearTimeout(timer);
  }, [trimmedCode]);
  const logo = trimmedCode.length === 8 && previewCode === trimmedCode
    ? `/api/pairing/branding/logo?code=${encodeURIComponent(trimmedCode)}` : null;
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !code.trim() || !name.trim()) return;
    setBusy(true); setError("");
    try { await pair(code, name); }
    catch (failure) {
      if (failure instanceof DOMException && failure.name === "AbortError") return;
      setError(failure instanceof ApiError && failure.status === 401 ? tr.invalidCode
        : failure instanceof ApiError && failure.status === 429 ? tr.throttled : tr.connectionError);
    } finally { setBusy(false); }
  }
  return <div className="pairing-layout">
    <ThemeToggle floating />
    <div className="pairing-brand"><BrandLogo key={trimmedCode} src={logo} /><strong>{tr.app}</strong><p>{tr.tagline}</p><SocialLinks /></div>
    <main className="pairing-form" id="content" tabIndex={-1}>
      <h1>{tr.pairTitle}</h1><p>{tr.pairIntro}</p>
      <form onSubmit={event => void submit(event)}>
        <label htmlFor="code">{tr.code}</label>
        <input id="code" value={code} onChange={event => setCode(event.target.value)} autoComplete="one-time-code" autoCapitalize="characters" spellCheck={false} required disabled={busy} />
        <label htmlFor="browser-name">{tr.browserName}</label>
        <input id="browser-name" value={name} onChange={event => setName(event.target.value)} autoComplete="off" aria-describedby="name-hint" maxLength={100} required disabled={busy} />
        <small id="name-hint">{tr.nameHint}</small>
        {error && <p role="alert" className="notice">{error}</p>}
        <button className="primary" disabled={busy || !code.trim() || !name.trim()}>{busy ? tr.pairing : tr.pair}</button>
      </form>
      <p className="pairing-note">{tr.pairingNote}</p>
    </main>
  </div>;
}
