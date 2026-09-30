import { useEffect, useState } from "react";
import { CONTRACT_VERSION, fetchCompat } from "./openapi";
import { tr } from "../i18n";

function apiBaseUrl(): string {
  return window.location.origin;
}

export function ContractBanner() {
  const [stale, setStale] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchCompat(apiBaseUrl())
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
