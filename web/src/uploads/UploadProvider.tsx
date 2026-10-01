import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { tr } from "../i18n";
import { startLiveRefresh } from "../live";
import { useSession } from "../session";
import { createUploadController, type UploadController, type UploadSnapshot } from "./controller";

interface Uploads { snapshot: UploadSnapshot; controller: UploadController }
const Context = createContext<Uploads | null>(null);

export function UploadProvider({ children, onPackageChanged }: { children: ReactNode; onPackageChanged: () => void }) {
  const { client, generation, invalidate } = useSession();
  const changed = useRef(onPackageChanged);
  changed.current = onPackageChanged;
  const [binding, setBinding] = useState<Uploads | null>(null);
  useEffect(() => {
    if (!client) return;
    let storage: Storage | null = null;
    try { storage = window.localStorage; } catch { /* Blocked storage must not hide shell. */ }
    const transport = { limits: api.uploadLimits, start: api.startUpload, status: api.uploadStatus,
      range: api.uploadRange, complete: api.completeUpload, resolve: api.resolveUpload };
    // Create in setup: StrictMode cleanup must not leave a reused disposed store.
    const controller = createUploadController({ clientId: client.id, storage, transport,
      onUnauthorized: invalidate, onPackageChanged: () => changed.current() });
    const update = () => setBinding({ controller, snapshot: controller.getSnapshot() });
    const unsubscribe = controller.subscribe(update);
    update();
    const initial = new AbortController();
    void controller.initialize(initial.signal);
    const stop = startLiveRefresh(signal => controller.refresh(signal));
    return () => { unsubscribe(); initial.abort(); stop(); controller.dispose(); };
  }, [client?.id, generation, invalidate]);
  return binding ? <Context.Provider value={binding}>{children}</Context.Provider> : <p role="status">{tr.loading}</p>;
}

export function useUploads(): Uploads {
  const value = useContext(Context);
  if (!value) throw new Error("UploadProvider required");
  return value;
}
