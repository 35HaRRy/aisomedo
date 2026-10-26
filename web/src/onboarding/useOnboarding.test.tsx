import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SessionProvider, useSession } from "../session";
import { api } from "../api/client";
import { client, setupState } from "../test/fixtures";
import { OnboardingProvider, useOnboarding } from "./useOnboarding";
import { invalidateLive } from "../test/live";

function Consumer() {
  const { setup, error, save, refresh } = useOnboarding();
  const { invalidate, status } = useSession();
  return <><span>{status}</span><span>{setup?.ready ? "ready" : "incomplete"}</span>
    {error && <span role="alert">refresh failed</span>}
    <button onClick={() => void save(s => api.skipCards(s)).catch(() => {})}>Save</button>
    <button onClick={() => void refresh().catch(() => {})}>Refresh</button>
    <button onClick={invalidate}>Revoke</button></>;
}
function Harness() {
  const session = useSession();
  return session.status === "paired" ? <OnboardingProvider key={session.generation}><Consumer /></OnboardingProvider> : <span>{session.status}</span>;
}
it("refreshes authoritative setup after saves and presents read failures", async () => {
  let reads = 0;
  vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(url.endsWith("/me") ? client : setupState()), { status: url === "/api/setup" && ++reads > 1 ? 500 : 200 }));
  render(<SessionProvider><Harness /></SessionProvider>);
  await screen.findByText("ready");
  fireEvent.click(screen.getByText("Save"));
  await screen.findByRole("alert");
  expect(screen.getByText("ready")).toBeInTheDocument();
});
it("aborts pending save on revocation and ignores late responses", async () => {
  let resolve: (value: Response) => void = () => {};
  let signal: AbortSignal | undefined;
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url.endsWith("/skip")) { signal = init.signal as AbortSignal; return new Promise<Response>(done => { resolve = done; }); }
    return new Response(JSON.stringify(url.endsWith("/me") ? client : setupState()));
  });
  render(<SessionProvider><Harness /></SessionProvider>);
  await screen.findByText("ready");
  fireEvent.click(screen.getByText("Save"));
  await waitFor(() => expect(signal).toBeDefined());
  fireEvent.click(screen.getByText("Revoke"));
  expect(signal?.aborted).toBe(true);
  await act(async () => resolve(new Response(JSON.stringify(setupState()))));
  expect(screen.getByText("unpaired")).toBeInTheDocument();
  expect(screen.queryByText("ready")).not.toBeInTheDocument();
});

it("invalidates session on protected mutation 401", async () => {
  vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(url.endsWith("/me") ? client : setupState()), { status: url.endsWith("/skip") ? 401 : 200 }));
  render(<SessionProvider><Harness /></SessionProvider>);
  await screen.findByText("ready");
  fireEvent.click(screen.getByText("Save"));
  await screen.findByText("unpaired");
});

it("concurrent setup refreshes share one request without aborting it", async () => {
  let finish!: (response: Response) => void;
  let readSignal!: AbortSignal;
  let reads = 0;
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url === "/api/setup") {
      reads++; readSignal = init.signal!;
      return new Promise<Response>(resolve => { finish = resolve; });
    }
    return new Response(JSON.stringify(client));
  });
  render(<SessionProvider><Harness /></SessionProvider>);
  await waitFor(() => expect(reads).toBe(1));
  const firstSignal = readSignal;
  fireEvent.click(screen.getByText("Refresh"));
  fireEvent.click(screen.getByText("Refresh"));
  expect(reads).toBe(1);
  expect(firstSignal.aborted).toBe(false);
  await act(async () => finish(new Response(JSON.stringify(setupState()))));
  await screen.findByText("ready");
});

it("a setup change during a manual read receives one deferred fresh read", async () => {
  let reads = 0, finish!: (response: Response) => void;
  vi.stubGlobal("fetch", async (url: string) => {
    if (url !== "/api/setup") return new Response(JSON.stringify(client));
    if (++reads === 2) return new Promise<Response>(resolve => { finish = resolve; });
    return new Response(JSON.stringify(reads === 1 ? setupState() : setupState("logo")));
  });
  render(<SessionProvider><Harness /></SessionProvider>);
  await screen.findByText("ready");
  fireEvent.click(screen.getByText("Refresh"));
  await waitFor(() => expect(reads).toBe(2));
  await act(async () => invalidateLive(["setup"]));
  expect(reads).toBe(2);
  await act(async () => finish(new Response(JSON.stringify(setupState()))));
  await screen.findByText("incomplete");
  expect(reads).toBe(3);
});

it("each concurrent save verifies a snapshot started after its own commit", async () => {
  const commits: ((value: Response) => void)[] = [];
  let reads = 0, finishOldRead!: (value: Response) => void;
  vi.stubGlobal("fetch", async (url: string) => {
    if (url.endsWith("/skip")) return new Promise<Response>(resolve => { commits.push(resolve); });
    if (url !== "/api/setup") return new Response(JSON.stringify(client));
    if (++reads === 2) return new Promise<Response>(resolve => { finishOldRead = resolve; });
    return new Response(JSON.stringify(reads === 1 ? setupState() : setupState("logo")));
  });
  render(<SessionProvider><Harness /></SessionProvider>);
  await screen.findByText("ready");
  fireEvent.click(screen.getByText("Save"));
  fireEvent.click(screen.getByText("Save"));
  await waitFor(() => expect(commits).toHaveLength(2));
  await act(async () => commits[0](new Response(JSON.stringify(setupState()))));
  expect(reads).toBe(2);
  await act(async () => commits[1](new Response(JSON.stringify(setupState("logo")))));
  await act(async () => finishOldRead(new Response(JSON.stringify(setupState()))));
  await screen.findByText("incomplete");
  expect(reads).toBe(3);
});
