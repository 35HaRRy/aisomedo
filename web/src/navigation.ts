import { useCallback, useEffect, useRef, useState } from "react";

export type Area = "dashboard" | "package" | "activity" | "settings" | "onboarding";
function readNavigation(): { area: Area; reviewId: number | null } {
  const [path, query] = window.location.hash.replace(/^#\/?/, "").split("?");
  const area = ["dashboard", "package", "activity", "settings", "onboarding"].includes(path) ? path as Area : "dashboard";
  const value = Number(new URLSearchParams(query).get("review"));
  return { area, reviewId: Number.isSafeInteger(value) && value > 0 ? value : null };
}
export function useNavigation(canLeave?: () => Promise<boolean>) {
  const [route, setRoute] = useState(readNavigation);
  const accepted = useRef(window.location.hash);
  const guard = useRef(canLeave); guard.current = canLeave;
  const pending = useRef(false);
  const navigate = useCallback(async (href: string) => {
    if (pending.current) return false;
    if (href === accepted.current) return true;
    pending.current = true;
    try {
      if (guard.current && !await guard.current()) return false;
      accepted.current = href; window.location.hash = href; setRoute(readNavigation()); return true;
    } finally { pending.current = false; }
  }, []);
  useEffect(() => {
    const update = () => {
      const href = window.location.hash;
      if (href === accepted.current) return;
      if (!guard.current) { accepted.current = href; setRoute(readNavigation()); return; }
      // Restore accepted route synchronously; children never observe an
      // unapproved hash (including Back/Forward navigation).
      window.history.replaceState(null, "", accepted.current || "#/");
      void navigate(href);
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return { ...route, navigate };
}
