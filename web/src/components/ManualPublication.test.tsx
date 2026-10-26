import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Dashboard } from "./Dashboard";
import { dashboard } from "../test/fixtures";

afterEach(() => vi.unstubAllGlobals());
it("confirms a future oneoff skip without requesting review or publishing", async () => {
  const slot = { occurrence_id: 8, kind: "oneoff", due_at: "2099-08-04T07:00:00Z" };
  const calls: Array<[string, unknown]> = [];
  vi.stubGlobal("fetch", async (path: string, options: RequestInit) => {
    calls.push([`${options.method} ${path}`, JSON.parse(String(options.body))]);
    return new Response(JSON.stringify({ occurrence_id: 8, due_at: slot.due_at, status: "skipped", package_folder: null }));
  });
  render(<Dashboard data={{ ...dashboard(), next_slots: [slot] }} />);
  fireEvent.click(screen.getByRole("button", { name: "Bu zamanı atla" }));
  expect(calls).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Atlamayı onayla" }));
  await screen.findByText("Bu Yayın Zamanı atlandı. Paket korunuyor.");
  expect(calls).toEqual([["POST /api/dashboard/occurrences/8/decision", {
    expected_due_at: slot.due_at, action: "skip", confirmed: true,
  }]]);
});

it("waits for the requested oneoff's review, ignores other reviews, and opens approval once", async () => {
  const slot = { occurrence_id: 8, kind: "oneoff", due_at: "2099-08-04T07:00:00Z" };
  const data = { ...dashboard(), next_slots: [slot] };
  const folder = data.package!.folder_name;
  const calls: Array<[string, unknown]> = [];
  const onOpenReview = vi.fn();
  vi.stubGlobal("fetch", async (path: string, options: RequestInit) => {
    calls.push([`${options.method} ${path}`, JSON.parse(String(options.body))]);
    return new Response(JSON.stringify({ occurrence_id: 8, due_at: data.generated_at, status: "pending", package_folder: folder }));
  });
  const { rerender } = render(<Dashboard data={data} onOpenReview={onOpenReview} />);
  const button = screen.getByRole("button", { name: "İncele ve yayınla" });
  fireEvent.click(button); fireEvent.click(button);
  await screen.findByText("Reel hazırlanıyor. Hazır olduğunda inceleme burada açılır.");
  expect(calls).toEqual([["POST /api/dashboard/occurrences/8/decision", { expected_due_at: slot.due_at, action: "review", confirmed: false }]]);
  const unrelated = { occurrence_id: 9, review_id: 22, version: 1, due_at: data.generated_at, package_folder: folder, state: "review_ready" as const };
  rerender(<Dashboard data={{ ...data, pending_actions: [unrelated] }} onOpenReview={onOpenReview} />);
  expect(onOpenReview).not.toHaveBeenCalled();
  const matching = { ...unrelated, occurrence_id: 8, review_id: 23 };
  rerender(<Dashboard data={{ ...data, pending_actions: [unrelated, matching] }} stale onOpenReview={onOpenReview} />);
  expect(onOpenReview).not.toHaveBeenCalled();
  rerender(<Dashboard data={{ ...data, pending_actions: [unrelated, matching] }} onOpenReview={onOpenReview} />);
  await waitFor(() => expect(onOpenReview).toHaveBeenCalledExactlyOnceWith(23));
});

it("does not open a requested review for a replaced package", async () => {
  const slot = { occurrence_id: 8, kind: "oneoff", due_at: "2099-08-04T07:00:00Z" };
  const data = { ...dashboard(), next_slots: [slot] };
  const onOpenReview = vi.fn();
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ occurrence_id: 8, due_at: data.generated_at, status: "pending", package_folder: "old" })));
  const { rerender } = render(<Dashboard data={data} onOpenReview={onOpenReview} />);
  fireEvent.click(screen.getByRole("button", { name: "İncele ve yayınla" }));
  await screen.findByText("Reel hazırlanıyor. Hazır olduğunda inceleme burada açılır.");
  rerender(<Dashboard data={{ ...data, pending_actions: [{ occurrence_id: 8, review_id: 23, version: 1, due_at: data.generated_at, package_folder: data.package!.folder_name, state: "review_ready" }] }} onOpenReview={onOpenReview} />);
  await screen.findByText("Paket değişti. Güncel işlemi kontrol panelinden açın.");
  expect(onOpenReview).not.toHaveBeenCalled();
});

it("blocks future oneoff decisions while stale and after uncertain writes", async () => {
  const data = { ...dashboard(), next_slots: [{ occurrence_id: 8, kind: "oneoff", due_at: "2099-08-04T07:00:00Z" }] };
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (path: string) => { calls.push(path); throw new TypeError("offline"); });
  const { rerender } = render(<Dashboard data={data} stale />);
  expect(screen.getByRole("button", { name: "İncele ve yayınla" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Bu zamanı atla" })).toBeDisabled();
  rerender(<Dashboard data={data} />);
  fireEvent.click(screen.getByRole("button", { name: "İncele ve yayınla" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "İncele ve yayınla" })).toBeDisabled();
  expect(calls).toEqual(["/api/dashboard/occurrences/8/decision"]);
});

it("ends waiting when a fresh dashboard no longer contains the requested occurrence", async () => {
  const slot = { occurrence_id: 8, kind: "oneoff", due_at: "2099-08-04T07:00:00Z" };
  const data = { ...dashboard(), next_slots: [slot] };
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ occurrence_id: 8, due_at: data.generated_at, status: "pending", package_folder: data.package!.folder_name })));
  const { rerender } = render(<Dashboard data={data} />);
  fireEvent.click(screen.getByRole("button", { name: "İncele ve yayınla" }));
  await screen.findByText("Reel hazırlanıyor. Hazır olduğunda inceleme burada açılır.");
  rerender(<Dashboard data={{ ...data, next_slots: [], pending_actions: [] }} />);
  await screen.findByText("Bu inceleme başka bir cihazda tamamlanmış veya artık mevcut değil.");
});

it("allows a new oneoff decision after skipping a different occurrence", async () => {
  const slot = { occurrence_id: 8, kind: "oneoff", due_at: "2099-08-04T07:00:00Z" };
  const data = { ...dashboard(), next_slots: [slot] };
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ occurrence_id: 8, due_at: slot.due_at, status: "skipped", package_folder: null })));
  const { rerender } = render(<Dashboard data={data} />);
  fireEvent.click(screen.getByRole("button", { name: "Bu zamanı atla" }));
  fireEvent.click(screen.getByRole("button", { name: "Atlamayı onayla" }));
  await screen.findByText("Bu Yayın Zamanı atlandı. Paket korunuyor.");
  rerender(<Dashboard data={{ ...data, next_slots: [{ ...slot, occurrence_id: 9 }] }} />);
  expect(screen.getByRole("button", { name: "İncele ve yayınla" })).toBeEnabled();
});

it.each([false, true])("changes a future oneoff date, regular present: %s", async withRegular => {
  const slot = { occurrence_id: 8, kind: "oneoff", due_at: "2099-08-04T07:00:00Z" };
  const regular = { occurrence_id: 9, kind: "regular", due_at: "2099-08-17T07:00:00Z" };
  const updated = { ...slot, due_at: "2099-08-05T12:30:00+03:00" };
  const calls: Array<[string, unknown]> = [];
  vi.stubGlobal("fetch", async (path: string, options: RequestInit) => {
    calls.push([`${options.method} ${path}`, JSON.parse(String(options.body))]);
    return new Response(JSON.stringify(updated), { status: 200 });
  });
  render(<Dashboard data={{ ...dashboard(), next_slots: withRegular ? [slot, regular] : [slot] }} />);
  fireEvent.click(screen.getByRole("button", { name: "Tarihi değiştir" }));
  fireEvent.change(screen.getByLabelText("Yeni yayın tarihi ve saati"), { target: { value: "2099-08-05T12:30" } });
  fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));
  await screen.findByRole("status");
  expect(calls).toEqual([["PATCH /api/dashboard/occurrences/8", {
    expected_due_at: slot.due_at, new_due_at: updated.due_at,
  }]]);
  expect(screen.getByRole("status")).toHaveTextContent("güncellendi");
});

it("blocks dates at the next regular boundary and stale dashboard writes", () => {
  const slot = { occurrence_id: 8, kind: "oneoff", due_at: "2099-08-04T07:00:00Z" };
  const data = { ...dashboard(), next_slots: [slot, { kind: "regular", due_at: "2099-08-17T07:00:00Z" }] };
  const { rerender } = render(<Dashboard data={data} />);
  fireEvent.click(screen.getByRole("button", { name: "Tarihi değiştir" }));
  const input = screen.getByLabelText("Yeni yayın tarihi ve saati");
  for (const value of ["2020-01-01T10:00", "2099-08-17T10:00", "2099-08-18T10:00"]) {
    fireEvent.change(input, { target: { value } });
    expect(screen.getByRole("button", { name: "Kaydet" })).toBeDisabled();
  }
  fireEvent.change(input, { target: { value: "2099-08-17T09:59" } });
  expect(screen.getByRole("button", { name: "Kaydet" })).toBeEnabled();
  rerender(<Dashboard data={data} stale />);
  expect(screen.getByRole("button", { name: "Kaydet" })).toBeDisabled();
});

it("shows edit conflicts without retrying the write", async () => {
  vi.stubGlobal("fetch", async () => new Response("{}", { status: 409 }));
  render(<Dashboard data={{ ...dashboard(), next_slots: [{ occurrence_id: 8, kind: "oneoff", due_at: "2099-08-04T07:00:00Z" }] }} />);
  fireEvent.click(screen.getByRole("button", { name: "Tarihi değiştir" }));
  fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("yenileyin");
  expect(screen.getByRole("button", { name: "Kaydet" })).toBeDisabled();
});

it.each(["regular", "manual", "oneoff"]) ("does not edit past %s slots", kind => {
  render(<Dashboard data={{ ...dashboard(), next_slots: [{ occurrence_id: 8, kind, due_at: "2020-08-04T07:00:00Z" }] }} />);
  expect(screen.queryByRole("button", { name: "Tarihi değiştir" })).not.toBeInTheDocument();
});

it.each(["oneoff", "manual"])("lists pending %s and regular slots together and removes resolved entries", kind => {
  const regular = { kind: "regular", due_at: "2026-08-17T07:00:00Z" };
  const exception = { kind, due_at: "2026-08-04T07:00:00Z" };
  const data = Object.assign(dashboard(), { next_slot: exception, next_slots: [exception, regular] });
  const { rerender } = render(<Dashboard data={data} />);
  const rows = within(screen.getByRole("list", { name: "Sonraki Yayın Zamanı" })).getAllByRole("listitem");
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent("4 Ağustos 2026");
  expect(rows[1]).toHaveTextContent("17 Ağustos 2026");
  expect(rows[1]).toHaveTextContent("Düzenli yayın");
  rerender(<Dashboard data={{ ...data, next_slots: [regular] }} />);
  expect(within(screen.getByRole("list", { name: "Sonraki Yayın Zamanı" })).getAllByRole("listitem")).toHaveLength(1);
  rerender(<Dashboard data={{ ...data, next_slots: [] }} />);
  expect(screen.queryByRole("list", { name: "Sonraki Yayın Zamanı" })).not.toBeInTheDocument();
});

it("blocks manual review when a pending exception is hidden behind the next regular slot", () => {
  const data = Object.assign(dashboard(), { manual_review_allowed: false });
  render(<Dashboard data={data} />);
  expect(screen.getByRole("button", { name: "Manuel Yayın İncelemesi iste" })).toBeDisabled();
});
it.each(["manual", "oneoff"])("blocks manual review while a future %s slot is pending", kind => {
  const data = dashboard();
  data.next_slot = { kind, due_at: "2099-08-04T07:00:00Z" };
  const { rerender } = render(<Dashboard data={data} />);
  expect(screen.getByRole("button", { name: "Manuel Yayın İncelemesi iste" })).toBeDisabled();
  rerender(<Dashboard data={dashboard()} />);
  expect(screen.getByRole("button", { name: "Manuel Yayın İncelemesi iste" })).toBeEnabled();
});

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
