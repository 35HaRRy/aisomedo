import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { LandingPage } from "./LandingPage";

it("explains approval and opens the existing application without changing the route for section links", () => {
  const open = vi.fn(), scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  render(<LandingPage onOpenApp={open} />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Antrenmandan");
  fireEvent.click(screen.getByRole("button", { name: "Akışı keşfet" }));
  expect(scroll).toHaveBeenCalled();
  expect(screen.getByText("Sen onaylamadan yayınlanmaz.")).toBeVisible();
  fireEvent.click(screen.getAllByRole("button", { name: "Uygulamayı aç" })[0]);
  expect(open).toHaveBeenCalledOnce();
});
