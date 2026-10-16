import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Dashboard } from "./Dashboard";
import { dashboard } from "../test/fixtures";

afterEach(() => vi.unstubAllGlobals());
it("requests a manual review without publishing and blocks a second request", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (path: string, options: RequestInit) => {
    calls.push(`${options.method} ${path}`);
    return new Response(JSON.stringify({ id: 8 }), { status: 200 });
  });
  render(<Dashboard data={dashboard()} />);
  fireEvent.click(screen.getByRole("button", { name: "Manuel Yayın İncelemesi iste" }));
  await waitFor(() => expect(screen.getByRole("link", { name: "İncelemeye devam et" })).toHaveAttribute("href", expect.stringContaining("occurrence=8")));
  expect(calls).toEqual(["POST /api/settings/manual-publish"]);
  expect(screen.getByRole("button", { name: "Manuel Yayın İncelemesi iste" })).toBeDisabled();
});

it("keeps uncertain manual requests blocked until dashboard is refreshed", async () => {
  vi.stubGlobal("fetch", async () => { throw new TypeError("offline"); });
  render(<Dashboard data={dashboard()} />);
  fireEvent.click(screen.getByRole("button", { name: "Manuel Yayın İncelemesi iste" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("kontrol");
  expect(screen.getByRole("button", { name: "Manuel Yayın İncelemesi iste" })).toBeDisabled();
});
