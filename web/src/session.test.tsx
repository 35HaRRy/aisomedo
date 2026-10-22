import { act, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { clearIdentityDrafts, readDraft, writeDraft, type StoredDraft } from "./packages/drafts";
import { SessionProvider, useSession } from "./session";

function Probe() {
  const session = useSession();
  return <><span>{session.status}:{session.client?.name}</span>
    <button onClick={session.invalidate}>revoke</button>
    <button onClick={() => void session.pair("CODE", "Web").catch(() => {})}>pair</button></>;
}

it("restores session and clears protected identity on revocation", async () => {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ id: 1, name: "Dojo" })));
  render(<SessionProvider><Probe /></SessionProvider>);
  expect(await screen.findByText("paired:Dojo")).toBeInTheDocument();
  await act(async () => screen.getByText("revoke").click());
  expect(screen.getByText("unpaired:")).toBeInTheDocument();
});

it("revocation preserves isolated drafts; explicit identity clearing removes only that identity", async () => {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ id: 1, name: "Dojo" })));
  const draft: StoredDraft = { schemaVersion: 1, localRevision: 0, folderName: "active", baseContentRevision: 1,
    groups: { "video:a": { base: { ranges: [] }, proposed: { ranges: [{ start: 0, end: 1 }] } } },
    inputs: { a: [{ start: "0", end: "1" }] }, uncertain: false };
  const mine = { origin: window.location.origin, clientId: 1, packageId: 9 };
  const other = { origin: window.location.origin, clientId: 2, packageId: 9 };
  await writeDraft(mine, 0, draft); await writeDraft(other, 0, draft);
  render(<SessionProvider><Probe /></SessionProvider>);
  await screen.findByText("paired:Dojo");
  await act(async () => screen.getByText("revoke").click());
  expect(screen.getByText("unpaired:")).toBeInTheDocument();
  expect(await readDraft(mine)).not.toBeNull();
  await clearIdentityDrafts(mine);
  expect(await readDraft(mine)).toBeNull();
  expect(await readDraft(other)).not.toBeNull();
});

it("late restore cannot resurrect revoked identity", async () => {
  let finish!: (value: Response) => void;
  vi.stubGlobal("fetch", () => new Promise<Response>(resolve => { finish = resolve; }));
  render(<SessionProvider><Probe /></SessionProvider>);
  await act(async () => screen.getByText("revoke").click());
  await act(async () => finish(new Response(JSON.stringify({ name: "Old" }))));
  expect(screen.getByText("unpaired:")).toBeInTheDocument();
});

it("invalid pairing stays unpaired; server failures stay retryable", async () => {
  vi.stubGlobal("fetch", async () => new Response("", { status: 401 }));
  render(<SessionProvider><Probe /></SessionProvider>);
  await screen.findByText("unpaired:");
  await act(async () => screen.getByText("pair").click());
  expect(screen.getByText("unpaired:")).toBeInTheDocument();
});

it("network failure does not imply unpaired", async () => {
  vi.stubGlobal("fetch", async () => { throw new TypeError("offline"); });
  render(<SessionProvider><Probe /></SessionProvider>);
  await waitFor(() => expect(screen.getByText("error:")).toBeInTheDocument());
});
