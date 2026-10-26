import { useEffect, useLayoutEffect, useSyncExternalStore, type ReactNode } from "react";
import { resetResourceVersions } from "./api/client";
import { tr } from "./i18n";
import { live } from "./live";
import { useSession } from "./session";

export function useLivePhase() {
  return useSyncExternalStore(live.watch, live.getSnapshot, live.getSnapshot);
}

export function LiveProvider({ children }: { children: ReactNode }) {
  const phase = useLivePhase(), { invalidate } = useSession();
  useLayoutEffect(() => { resetResourceVersions(); return live.start(); }, []);
  useEffect(() => { if (phase === "unauthorized") invalidate(); }, [phase, invalidate]);
  return <>
    {(phase === "disconnected" || phase === "sync-failed" || phase === "unauthorized") && <div className="notice live-notice" role="status">
      <p>{tr.liveState[phase]}</p>
      {phase !== "unauthorized" && <button type="button" onClick={() => live.retry()}>{tr.liveRetry}</button>}
    </div>}
    <fieldset className="live-content" aria-label={tr.liveWorkspace} disabled={phase !== "live"}>{children}</fieldset>
  </>;
}
