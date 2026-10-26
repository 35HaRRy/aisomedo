import { live } from "../live";

let version = 0;
/** Unit consumers use a ready coordinator; transport is exercised separately. */
export function readyLive() { live.stop(); live.acceptMessage("ready", { protocol: 1 }); }
export function invalidateLive(resources = ["dashboard", "activity", "setup", "settings", "publication", "package:1"]) {
  const next = ++version;
  live.acceptMessage("change", { event_id: `fixture-${next}`, versions: Object.fromEntries(resources.map(key => [key, next])) });
}
export function liveResponse() {
  return new Response(new ReadableStream<Uint8Array>({ start(controller) {
    controller.enqueue(new TextEncoder().encode('event: ready\ndata: {"protocol":1}\n\n'));
  } }), { headers: { "Content-Type": "text/event-stream" } });
}
