import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { initializeTheme, ThemeToggle } from "./theme";

let system: MediaQueryList;
beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  system = Object.assign(new EventTarget(), { matches: true }) as MediaQueryList;
  vi.stubGlobal("matchMedia", () => system);
});

it("follows system appearance until the user chooses, then remembers that choice", () => {
  initializeTheme();
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  const view = render(<ThemeToggle />);
  fireEvent.click(screen.getByRole("button", { name: "Açık Mod" }));
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  expect(localStorage.getItem("dojo-theme")).toBe("light");
  view.unmount();
  initializeTheme();
  render(<ThemeToggle />);
  expect(screen.getByRole("button", { name: "Koyu Mod" })).toBeVisible();
  act(() => system.dispatchEvent(new Event("change")));
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
});

it("responds to system changes when no preference is stored", () => {
  render(<ThemeToggle />);
  act(() => {
    Object.assign(system, { matches: false });
    system.dispatchEvent(new Event("change"));
  });
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  expect(screen.getByRole("button", { name: "Koyu Mod" })).toBeVisible();
});

it("ignores invalid preferences and still switches when browser storage is blocked", () => {
  localStorage.setItem("dojo-theme", "invalid");
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
  expect(() => initializeTheme()).not.toThrow();
  render(<ThemeToggle />);
  fireEvent.click(screen.getByRole("button", { name: "Açık Mod" }));
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
});
