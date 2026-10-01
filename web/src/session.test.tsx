import { act, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
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
