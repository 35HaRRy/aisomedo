import type { Page } from "@playwright/test";

/** Exercise the real Fetch parser without a buffered route.fulfill SSE body. */
export async function installLiveStream(page: Page, ready = true, tours = false) {
  // Existing workflow tests exercise product actions, not first-visit tour overlays.
  if (!tours) await page.addInitScript(() => localStorage.setItem("aisomedo:promotion:v1:1", JSON.stringify({ version: 1, completed: [], dismissed: [], skipAll: true })));
  await page.addInitScript(initialReady => {
    const original = window.fetch.bind(window);
    const outputs = new Set<ReadableStreamDefaultController<Uint8Array>>();
    let version = 0, available = true;
    const encode = (event: string, data: unknown) => new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    window.addEventListener("fixture:ready", () => { for (const output of outputs) output.enqueue(encode("ready", { protocol: 1 })); });
    window.addEventListener("fixture:heartbeat", () => { for (const output of outputs) output.enqueue(encode("heartbeat", {})); });
    window.addEventListener("fixture:change", event => {
      const next = ++version;
      const resources = (event as CustomEvent<string[]>).detail;
      for (const output of outputs) output.enqueue(encode("change", { event_id: `browser-${next}`, versions: Object.fromEntries(resources.map(key => [key, next])) }));
    });
    window.addEventListener("fixture:disconnect", () => {
      available = false;
      for (const output of outputs) output.error(new Error("fixture connection lost"));
      outputs.clear();
    });
    window.fetch = async (input, init) => {
      if (String(input) !== "/api/events") return original(input, init);
      if (!available) return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("", "AbortError")), { once: true });
      });
      let output!: ReadableStreamDefaultController<Uint8Array>;
      const body = new ReadableStream<Uint8Array>({ start(controller) {
        output = controller; outputs.add(output); if (initialReady) output.enqueue(encode("ready", { protocol: 1 }));
      }, cancel() { outputs.delete(output); } });
      init?.signal?.addEventListener("abort", () => { if (outputs.delete(output)) output.close(); }, { once: true });
      return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
    };
  }, ready);
}

export async function invalidateLive(page: Page, resources = ["dashboard", "publication", "setup", "settings", "activity", "package:1"]) {
  await page.evaluate(keys => window.dispatchEvent(new CustomEvent("fixture:change", { detail: keys })), resources);
}
