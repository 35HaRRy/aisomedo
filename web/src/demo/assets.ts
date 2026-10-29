import { getDemoRuntime } from "./runtime";
import { PHOTO, VIDEO } from "./seed";

export function demoAssetUrl(path: string): string {
  if ([PHOTO, VIDEO].includes(path) || getDemoRuntime()?.objectUrls.has(path)) return path;
  throw new Error("Unknown demo asset");
}
export function registerDemoFile(file: Blob): string {
  const runtime = getDemoRuntime();
  if (!runtime || runtime.signal.aborted) throw new Error("Demo runtime unavailable");
  const url = URL.createObjectURL(file); runtime.objectUrls.set(url, file.type);
  return url;
}
export function demoAssetType(path: string): string {
  demoAssetUrl(path);
  return getDemoRuntime()?.objectUrls.get(path) ?? (path === VIDEO ? "video/webm" : "image/svg+xml");
}
