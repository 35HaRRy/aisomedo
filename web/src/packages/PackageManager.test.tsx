import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { UploadProvider } from "../uploads/UploadProvider";
import { PackageEditorProvider } from "./PackageEditorProvider";
import { PackageManager } from "./PackageManager";
import { editorServer } from "./testFixtures";

it("completed view uses draft decision and cancel keeps editor mounted", async () => {
  localStorage.clear(); const server = editorServer();
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => url === "/api/packages" ? server.json([]) : server.fetcher(url, init));
  render(<SessionProvider><PackageEditorProvider><UploadProvider onPackageChanged={() => {}}><PackageManager /></UploadProvider></PackageEditorProvider></SessionProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "a.mp4 bölümlerini düzenle" }));
  fireEvent.click(screen.getByRole("button", { name: "Bölüm ekle" }));
  fireEvent.click(screen.getByRole("button", { name: "Tamamlanmış paketler" }));
  const cancel = await screen.findByRole("button", { name: "Vazgeç" });
  await act(async () => { fireEvent.click(cancel); });
  expect(screen.getByRole("button", { name: "Bölümleri kaydet" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Tamamlanmış paketler" }));
  fireEvent.click(await screen.findByRole("button", { name: "Değişiklikleri at" }));
  await screen.findByText("Henüz tamamlanmış paket yok.");
  expect(screen.queryByRole("button", { name: "Bölümleri kaydet" })).not.toBeInTheDocument();
});
