import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { tr } from "../i18n";
import { startLiveRefresh } from "../live";
import { useSession } from "../session";
import { createUploadController, type UploadController, type UploadSnapshot } from "./controller";
import { recoveryStorage } from "../demo/runtime";

interface Uploads { snapshot: UploadSnapshot; controller: UploadController }
const Context = createContext<Uploads | null>(null);

export function UploadProvider({ children, onPackageChanged }: { children: ReactNode; onPackageChanged?: () => void }) {
  const { client, generation, invalidate } = useSession();
  const changed = useRef(onPackageChanged);
  changed.current = onPackageChanged;
  const [binding, setBinding] = useState<Uploads | null>(null);
  useEffect(() => {
    if (!client) return;
    const storage = recoveryStorage();
    const transport = { limits: api.uploadLimits, start: api.startUpload, status: api.uploadStatus,
      range: api.uploadRange, complete: api.completeUpload, resolve: api.resolveUpload };
    // Create in setup: StrictMode cleanup must not leave a reused disposed store.
    const controller = createUploadController({ clientId: client.id, storage, transport,
      onUnauthorized: invalidate, onPackageChanged: () => changed.current?.() });
    const update = () => setBinding({ controller, snapshot: controller.getSnapshot() });
    const unsubscribe = controller.subscribe(update);
    update();
    let initialized = false, initializationAttempted = false;
    const stop = startLiveRefresh(async signal => {
      if (!initialized) {
        const reconcile = initializationAttempted; initializationAttempted = true;
        await controller.initialize(signal);
        if (reconcile) await controller.refresh(signal);
      }
      else await controller.refresh(signal);
      const snapshot = controller.getSnapshot();
      if (snapshot.limitsError || snapshot.rows.some(row => ["queued", "processing", "conflict"].includes(row.phase)
        && row.error !== null && ["network", "server", "invalid-response"].includes(row.error))) throw new Error("upload snapshot unavailable");
      initialized = true;
    }, ["upload:*", "package:*", "settings"]);
    return () => { unsubscribe(); stop(); controller.dispose(); };
  }, [client?.id, generation, invalidate]);
  return binding ? <Context.Provider value={binding}>{children}</Context.Provider> : <p role="status">{tr.loading}</p>;
}

export function useUploads(): Uploads {
  const value = useContext(Context);
  if (!value) throw new Error("UploadProvider required");
  return value;
}
