import { useEffect, useState } from "react";
import { CONTRACT_VERSION, fetchCompat } from "./openapi";

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
    <div role="alert">
      <p>Yeni bir arayüz sürümü mevcut. Güncel sözleşme için sayfayı yenileyin.</p>
      <button type="button" onClick={() => window.location.reload()}>
        Yenile
      </button>
    </div>
  );
}
