import { useEffect, useState } from "react";
import { CONTRACT_VERSION, type CompatInfo } from "./openapi";
import { transportFetch } from "./transport";
import { tr } from "../i18n";

function apiBaseUrl(): string {
  return window.location.origin;
}

export function ContractBanner() {
  const [stale, setStale] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    transportFetch(`${apiBaseUrl()}/api/compat`, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error("Compatibility unavailable");
      return await response.json() as CompatInfo;
    })
      .then((compat) => {
        if (!cancelled && compat.api_version !== CONTRACT_VERSION) {
          setStale(true);
        }
      })
      .catch(() => {
        // Backend unreachable: dashboard stays usable, no banner.
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  if (!stale) {
    return null;
  }
  return (
    <div role="alert" className="notice compatibility">
      <p>{tr.compat}</p>
      <button type="button" onClick={() => window.location.reload()}>
        {tr.reload}
      </button>
    </div>
  );
}
