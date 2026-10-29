export const isDemoHash = (hash: string) => /^#\/demo(?:\/|\?|$)/.test(hash);
let validatedPairing = false;
export function normalHref(hash: string): string {
  if (!isDemoHash(hash)) return hash;
  const rest = hash.replace(/^#\/demo\/?/, "");
  return `#/${!rest || rest.startsWith("?") ? "dashboard" : ""}${rest}`;
}
export function workspaceHref(href: string, demo = isDemoHash(window.location.hash)): string {
  return demo && href.startsWith("#/") && href !== "#/welcome" && !isDemoHash(href) ? href.replace("#/", "#/demo/") : href;
}
function browserStorage(): Storage | null {
  try { return window.localStorage; } catch { return null; }
}
export function readPairingMarker(storage = browserStorage()): boolean {
  try { return storage ? storage.getItem("aisomedo:real-paired:v1") === "1" : validatedPairing; } catch { return validatedPairing; }
}
export function noteRealPairing(paired: boolean): void { validatedPairing = paired; writePairingMarker(paired); }
export function writePairingMarker(paired: boolean, storage = browserStorage()): void {
  try { if (paired) storage?.setItem("aisomedo:real-paired:v1", "1"); else storage?.removeItem("aisomedo:real-paired:v1"); } catch { /* A hint never grants authentication. */ }
}
