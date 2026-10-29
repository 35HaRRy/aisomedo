import { afterEach, expect, it, vi } from "vitest";
import { startDemo, stopDemo } from "./runtime";
import { demoAssetUrl, demoAssetType, registerDemoFile } from "./assets";

afterEach(() => { stopDemo(); vi.unstubAllGlobals(); });
it("keeps uploaded bytes and previews local and revokes them on exit", async () => {
  const native = vi.fn(); vi.stubGlobal("fetch", native);
  const create = vi.fn(() => "blob:demo-preview"), revoke = vi.fn();
  vi.stubGlobal("URL", class extends URL { static createObjectURL = create; static revokeObjectURL = revoke; });
  startDemo(); expect(registerDemoFile(new File(["photo"], "local.jpg", { type: "image/jpeg" }))).toBe("blob:demo-preview");
  expect(demoAssetUrl("blob:demo-preview")).toBe("blob:demo-preview");
  expect(() => demoAssetUrl("/api/private")).toThrow();
  stopDemo(); expect(revoke).toHaveBeenCalledWith("blob:demo-preview"); expect(native).not.toHaveBeenCalled();
});
it("retains the MIME type for opaque saved video asset URLs", () => {
  startDemo(); const url = registerDemoFile(new Blob(["sample"], { type: "video/mp4" }));
  expect(demoAssetType(url)).toBe("video/mp4");
});
it("validates upload offsets, completes locally, and handles duplicate conflicts", async () => {
  const runtime = startDemo();
  const send = (path: string, body: unknown) => runtime.fetch(`/api/media/uploads${path}`, { method: "POST", body: JSON.stringify(body) });
  const upload = await (await send("", { filename: "antrenman.jpg", content_type: "image/jpeg", declared_size_bytes: 3, expected_package_id: 1 })).json();
  expect(upload.status).toBe("conflict");
  expect((await send(`/${upload.upload_id}/resolve`, { decision: "keep_selected" })).status).toBe(422);
  expect((await send(`/${upload.upload_id}/resolve`, { decision: "keep_both" })).status).toBe(200);
  expect((await runtime.fetch(`/api/media/uploads/${upload.upload_id}/ranges?offset=1&checksum_sha256=${"a".repeat(64)}`, { method: "PUT", body: new Blob(["abc"]) })).status).toBe(409);
  expect((await runtime.fetch(`/api/media/uploads/${upload.upload_id}/ranges?offset=0&checksum_sha256=${"a".repeat(64)}`, { method: "PUT", body: new Blob(["abc"]) })).status).toBe(200);
  expect((await send(`/${upload.upload_id}/complete`, {})).status).toBe(200);
  expect(runtime.state.editor.media).toHaveLength(3);
  expect(runtime.state.editor.media[2].preview_url).not.toContain("/api/");
});
it("simulates rendering and account selection with no external credentials or URLs", async () => {
  const runtime = startDemo(), pkg = runtime.state.editor.package;
  const render = await runtime.fetch("/api/packages/active/render", { method: "POST", body: JSON.stringify({ expected_folder_name: pkg.folder_name }), headers: { "If-Match": '"1:1"' } });
  expect(render.status).toBe(200); expect(runtime.state.editor.render_preview_url).toBe("/demo/training.webm");
  const attempt = await (await runtime.fetch("/api/meta/oauth/start", { method: "POST", body: "{}" })).json();
  expect(attempt.auth_url).not.toContain("facebook");
  const status = await (await runtime.fetch(`/api/meta/oauth/attempts/${attempt.attempt_id}`)).json();
  expect(status.candidates).toHaveLength(2);
  const result = await runtime.fetch(`/api/meta/oauth/attempts/${attempt.attempt_id}/select`, { method: "POST", body: JSON.stringify({ ig_user_id: "demo-account-2" }) });
  expect(result.status).toBe(200); expect(runtime.state.instagram.ig_username).toBe("ornek_studyo_demo_2");
});
