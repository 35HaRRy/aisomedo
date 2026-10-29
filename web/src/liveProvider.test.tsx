import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { LiveProvider } from "./liveProvider";
import { SessionProvider, useSession } from "./session";
import { client } from "./test/fixtures";
import { useLiveData } from "./useLiveData";
import { tr } from "./i18n";

it("locks native editing controls until subscription and required view synchronize", async () => {
  let output!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(controller) { output = controller; } });
  vi.stubGlobal("fetch", async (url: string) => url === "/api/events"
    ? new Response(body, { headers: { "Content-Type": "text/event-stream" } })
    : new Response(JSON.stringify(client)));
  const load = vi.fn(async () => "snapshot");
  function View() {
    useLiveData(load, true, ["dashboard"]);
    return <input aria-label="Draft" defaultValue="preserved" />;
  }
  function Paired() {
    const session = useSession();
    return session.status === "paired" ? <LiveProvider><View /></LiveProvider> : null;
  }
  render(<SessionProvider><Paired /></SessionProvider>);
  const input = await screen.findByLabelText("Draft");
  await waitFor(() => expect(input).toBeDisabled()); expect(load).not.toHaveBeenCalled();
  await act(async () => output.enqueue(new TextEncoder().encode('event: ready\ndata: {"protocol":1}\n\n')));
  await waitFor(() => expect(input).not.toBeDisabled());
  await act(async () => output.error(new Error("lost connection")));
  await waitFor(() => expect(input).toBeDisabled());
  expect(input).toHaveValue("preserved"); expect(load).toHaveBeenCalledTimes(1);
});

it("keeps foreground resynchronization quiet but exposes failed reads and retry", async () => {
  let output!: ReadableStreamDefaultController<Uint8Array>;
  let hidden = false, fail = false;
  vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
  vi.stubGlobal("fetch", async (url: string) => url === "/api/events"
    ? new Response(new ReadableStream<Uint8Array>({ start(controller) { output = controller; } }),
      { headers: { "Content-Type": "text/event-stream" } })
    : new Response(JSON.stringify(client)));
  let finish!: () => void;
  const load = vi.fn(async () => {
    await new Promise<void>(resolve => { finish = resolve; });
    if (fail) throw new Error("snapshot unavailable");
    return "snapshot";
  });
  function View() {
    useLiveData(load, true, ["dashboard"]);
    return <input aria-label="Draft" defaultValue="preserved" />;
  }
  function Paired() {
    return useSession().status === "paired" ? <LiveProvider><View /></LiveProvider> : null;
  }
  const ready = () => output.enqueue(new TextEncoder().encode('event: ready\ndata: {"protocol":1}\n\n'));
  render(<SessionProvider><Paired /></SessionProvider>);
  const input = await screen.findByLabelText("Draft");
  await waitFor(() => expect(input).toBeDisabled());
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  await act(async () => ready());
  expect(input).toBeDisabled();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  await act(async () => finish());
  await waitFor(() => expect(input).not.toBeDisabled());
  await act(async () => { hidden = true; document.dispatchEvent(new Event("visibilitychange")); });
  await act(async () => { hidden = false; document.dispatchEvent(new Event("visibilitychange")); });
  expect(input).toBeDisabled();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  await act(async () => ready());
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  fail = true;
  await act(async () => finish());
  expect(screen.getByRole("status")).toHaveTextContent(/doğrulanamadı/);
  expect(input).toBeDisabled();
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: tr.liveRetry }));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  await act(async () => finish());
  await waitFor(() => expect(input).not.toBeDisabled());
  expect(input).toHaveValue("preserved");
  expect(load).toHaveBeenCalledTimes(3);
  await act(async () => output.error(new Error("connection lost")));
  expect(screen.getByRole("status")).toHaveTextContent(tr.liveState.disconnected);
});
