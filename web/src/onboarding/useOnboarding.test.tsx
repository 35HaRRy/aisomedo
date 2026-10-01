import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SessionProvider, useSession } from "../session";
import { api } from "../api/client";
import { client, setupState } from "../test/fixtures";
import { OnboardingProvider, useOnboarding } from "./useOnboarding";

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
