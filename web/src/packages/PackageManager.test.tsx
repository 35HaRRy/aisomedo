import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { UploadProvider } from "../uploads/UploadProvider";
import { PackageEditorProvider } from "./PackageEditorProvider";
import { PackageManager } from "./PackageManager";
import { editorServer } from "./testFixtures";

it("collapsing the editor retains unsaved video ranges", async () => {
  window.location.hash = "#/package";
  localStorage.clear(); const server = editorServer();
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => url === "/api/packages" ? server.json([]) : server.fetcher(url, init));
  render(<SessionProvider><PackageEditorProvider><UploadProvider onPackageChanged={() => {}}><PackageManager /></UploadProvider></PackageEditorProvider></SessionProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "a.mp4 bölümlerini düzenle" }));
  fireEvent.click(screen.getByRole("button", { name: "Bölüm ekle" }));
  fireEvent.click(screen.getByRole("button", { name: "Aktif paket medyası panelini kapat" }));
  expect(screen.queryByRole("button", { name: "Bölümleri kaydet" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Aktif paket medyası panelini aç" }));
  expect(screen.getByRole("button", { name: "Bölümleri kaydet" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Bölümleri kaydet" })).toBeEnabled();
  expect(server.writes).toEqual([]);
});
