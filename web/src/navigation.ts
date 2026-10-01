import { useEffect, useState } from "react";

export type Area = "dashboard" | "package" | "activity" | "settings" | "onboarding";
function readNavigation(): { area: Area; reviewId: number | null } {
  const [path, query] = window.location.hash.replace(/^#\/?/, "").split("?");
  const area = ["dashboard", "package", "activity", "settings", "onboarding"].includes(path) ? path as Area : "dashboard";
  const value = Number(new URLSearchParams(query).get("review"));
  return { area, reviewId: Number.isSafeInteger(value) && value > 0 ? value : null };
}
export function useNavigation() {
  const [route, setRoute] = useState(readNavigation);
  useEffect(() => {
    const update = () => setRoute(readNavigation());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}
