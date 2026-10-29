import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { PackageEditorProvider, usePackageEditorContext } from "./PackageEditorProvider";
import { editorServer } from "./testFixtures";
import { writeDraft } from "./drafts";

beforeEach(() => { window.location.hash = "#/package"; Object.defineProperty(navigator, "onLine", { value: true, configurable: true }); });
function Probe() {
  const editor = usePackageEditorContext(); const nav = editor.navigation;
  return <><output>{nav.area}</output>
    <button disabled={!editor.snapshot} onClick={() => editor.setRanges("a", [{ start: 0, end: 5 }])}>Edit</button>
    <button onClick={() => void nav.navigate("#/settings")}>Leave</button>
    <button onClick={() => void editor.remove("a")}>Remove A</button>
    <input aria-label="End" value={editor.draftInputs.a?.[0]?.end ?? ""} onChange={e => editor.setInput("a", 0, "end", e.target.value)} />
    <output>{editor.dirty ? "dirty" : "clean"}</output>
  </>;
}
async function setup() {
  const server = editorServer(); vi.stubGlobal("fetch", server.fetcher);
  render(<SessionProvider><PackageEditorProvider><Probe /></PackageEditorProvider></SessionProvider>);
  await waitFor(() => expect(screen.getByText("Edit")).toBeEnabled());
  fireEvent.click(screen.getByText("Edit")); return server;
}

it("cancel retains route and drafts; explicit discard permits navigation", async () => {
  await setup(); fireEvent.click(screen.getByText("Leave"));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  const background = screen.getByText("Leave").parentElement;
  expect(background).toHaveAttribute("inert");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Vazgeç" })); });
  expect(background).not.toHaveAttribute("inert");
  expect(screen.getByText("package")).toBeInTheDocument(); expect(screen.getByText("dirty")).toBeInTheDocument();
  fireEvent.click(screen.getByText("Leave"));
  fireEvent.click(await screen.findByRole("button", { name: "Değişiklikleri at" }));
  await waitFor(() => expect(screen.getByText("settings")).toBeInTheDocument());
  expect(screen.getByText("clean")).toBeInTheDocument();
});

it("save allows navigation only after acknowledged success", async () => {
  const server = await setup(); server.writeStatus = 0;
  fireEvent.click(screen.getByText("Leave"));
  fireEvent.click(await screen.findByRole("button", { name: "Kaydet ve devam et" }));
  await waitFor(() => expect(server.writes).toHaveLength(1));
  expect(screen.getByText("package")).toBeInTheDocument();
  expect(screen.getByText("dirty")).toBeInTheDocument();
});

it("invalid text stays owned by provider and blocks save/navigation; beforeunload warns", async () => {
  await setup(); fireEvent.change(screen.getByLabelText("End"), { target: { value: "" } });
  fireEvent.click(screen.getByText("Leave"));
  expect(await screen.findByRole("button", { name: "Kaydet ve devam et" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Vazgeç" }));
  expect(screen.getByLabelText("End")).toHaveValue("");
  const event = new Event("beforeunload", { cancelable: true });
  act(() => window.dispatchEvent(event)); expect(event.defaultPrevented).toBe(true);
});

it("dirty removal asks permission and cancellation sends no mutation", async () => {
  const server = await setup(); fireEvent.click(screen.getByText("Remove A"));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Vazgeç" }));
  expect(server.writes).toHaveLength(0); expect(screen.getByText("dirty")).toBeInTheDocument();
});

it("external hash navigation is rejected before draft owner unmounts", async () => {
  await setup(); act(() => { window.location.hash = "#/settings"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(screen.getByText("package")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Vazgeç" }));
  await waitFor(() => expect(window.location.hash).toBe("#/package"));
});

it("acknowledged save moves to requested route and closes the guard", async () => {
  const server = await setup(); fireEvent.click(screen.getByText("Leave"));
  fireEvent.click(await screen.findByRole("button", { name: "Kaydet ve devam et" }));
  await waitFor(() => expect(screen.getByText("settings")).toBeInTheDocument());
  expect(server.writes).toHaveLength(1); expect(screen.getByText("clean")).toBeInTheDocument();
});

it("discard confirmation retains draft if removal fails", async () => {
  const server = await setup(); server.writeStatus = 422;
  fireEvent.click(screen.getByText("Remove A"));
  fireEvent.click(await screen.findByRole("button", { name: "Değişiklikleri at" }));
  await waitFor(() => expect(server.writes).toHaveLength(1));
  expect(screen.getByLabelText("End")).toHaveValue("5");
  expect(screen.getByText("dirty")).toBeInTheDocument();
});

it("a recovered hidden draft does not block navigation back to its editor", async () => {
  const server = editorServer(); vi.stubGlobal("fetch", server.fetcher);
  await writeDraft({ origin: window.location.origin, clientId: 1, packageId: 1 }, 0, {
    schemaVersion: 1, localRevision: 0, folderName: server.snapshot.package.folder_name,
    baseContentRevision: 1, uncertain: false,
    groups: { "video:a": { base: { ranges: [] }, proposed: { ranges: [{ start: 0, end: 5 }] } } },
    inputs: { a: [{ start: "0", end: "5" }] },
  });
  window.location.hash = "#/dashboard";
  render(<SessionProvider><PackageEditorProvider><Probe /></PackageEditorProvider></SessionProvider>);
  await screen.findByText("dirty");
  await act(async () => { window.location.hash = "#/package"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
  await waitFor(() => expect(screen.getByText("package")).toBeInTheDocument());
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByLabelText("End")).toHaveValue("5");
});
