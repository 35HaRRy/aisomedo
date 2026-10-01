import { act, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { SessionProvider, useSession } from "../session";
import { client } from "../test/fixtures";
import { UploadProvider, useUploads } from "./UploadProvider";
import { deferred, installCrypto, uploadServer } from "./testFixtures";

function Probe() {
  const { snapshot, controller } = useUploads();
  const session = useSession();
  return <><span>{snapshot.rows.map(row => row.phase).join(",") || "empty"}</span>
    <button onClick={() => void controller.add([new File(["abc"], "dojo.jpg")])}>select</button>
    <button onClick={session.invalidate}>revoke</button></>;
}
function Gate() {
  const session = useSession();
  return session.status === "paired" ? <UploadProvider onPackageChanged={() => {}}><Probe /></UploadProvider> : <span>{session.status}</span>;
}
function setup() {
  const server = uploadServer();
  vi.spyOn(api, "me").mockResolvedValue(client);
  vi.spyOn(api, "uploadLimits").mockImplementation(signal => server.transport.limits(signal!));
  vi.spyOn(api, "startUpload").mockImplementation((body, signal) => server.transport.start(body, signal!));
  vi.spyOn(api, "uploadStatus").mockImplementation((id, signal) => server.transport.status(id, signal!));
  vi.spyOn(api, "uploadRange").mockImplementation((id, offset, hash, blob, signal) => server.transport.range(id, offset, hash, blob, signal!));
  vi.spyOn(api, "completeUpload").mockImplementation((id, signal) => server.transport.complete(id, signal!));
  return server;
}
beforeEach(() => { localStorage.clear(); installCrypto(); });
afterEach(() => vi.useRealTimers());

it("StrictMode effect replay leaves one usable controller", async () => {
  const server = setup();
  render(<StrictMode><SessionProvider><Gate /></SessionProvider></StrictMode>);
  await screen.findByRole("button", { name: "select" });
  await waitFor(() => expect(server.transport.limits).toHaveBeenCalled());
  await act(async () => screen.getByRole("button", { name: "select" }).click());
  await screen.findByText("queued");
  expect(server.transport.start).toHaveBeenCalledTimes(1);
});

it("foreground polling stops hidden, coalesces wake, and never overlaps", async () => {
  const server = setup();
  render(<SessionProvider><Gate /></SessionProvider>);
  await screen.findByRole("button", { name: "select" });
  await waitFor(() => expect(server.transport.limits).toHaveBeenCalled());
  await act(async () => screen.getByRole("button", { name: "select" }).click());
  await screen.findByText("queued");
  vi.useFakeTimers();
  let hidden = true;
  vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await vi.advanceTimersByTimeAsync(10000); });
  expect(server.transport.status).toHaveBeenCalledTimes(1);
  hidden = false;
  const pending = deferred<Awaited<ReturnType<typeof server.transport.status>>>();
  server.transport.status.mockImplementationOnce(() => pending.promise);
  await act(async () => { window.dispatchEvent(new Event("focus")); window.dispatchEvent(new Event("online")); await vi.advanceTimersByTimeAsync(0); });
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(server.transport.status).toHaveBeenCalledTimes(2);
  await act(async () => pending.resolve({ ...server.records.get("upload-1")!, status: "finalized" }));
  expect(screen.getByText("finalized")).toBeInTheDocument();
});

it("401 while uploading clears paired state and ignores late work", async () => {
  const server = setup();
  const { ApiError } = await import("../api/client");
  server.transport.range.mockRejectedValueOnce(new ApiError(401));
  render(<SessionProvider><Gate /></SessionProvider>);
  await screen.findByRole("button", { name: "select" });
  await waitFor(() => expect(server.transport.limits).toHaveBeenCalled());
  await act(async () => screen.getByRole("button", { name: "select" }).click());
  await screen.findByText("unpaired");
  expect(screen.queryByText("queued")).not.toBeInTheDocument();
  expect(server.transport.complete).not.toHaveBeenCalled();
});

it("revocation during digest ignores late preparation without starting upload", async () => {
  const server = setup();
  const pending = deferred<ArrayBuffer>();
  const digest = vi.fn(() => pending.promise);
  vi.stubGlobal("crypto", { randomUUID: () => "row", subtle: { digest } });
  render(<SessionProvider><Gate /></SessionProvider>);
  await screen.findByRole("button", { name: "select" });
  await waitFor(() => expect(server.transport.limits).toHaveBeenCalled());
  fireSelect();
  await waitFor(() => expect(digest).toHaveBeenCalled());
  await act(async () => screen.getByRole("button", { name: "revoke" }).click());
  await screen.findByText("unpaired");
  await act(async () => pending.resolve(new ArrayBuffer(32)));
  expect(server.transport.start).not.toHaveBeenCalled();
});

function fireSelect() { act(() => screen.getByRole("button", { name: "select" }).click()); }
