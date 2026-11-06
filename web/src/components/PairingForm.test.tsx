import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { PairingForm } from "./PairingForm";

it("uses the app logo until a full code is entered and resets it when the code changes", async () => {
  vi.stubGlobal("fetch", async () => new Response("{}", { status: 401 }));
  render(<SessionProvider><PairingForm /></SessionProvider>);
  expect(screen.getByRole("img", { name: "Logo" })).toHaveAttribute("src", "/logo.jpg");
  const input = screen.getByLabelText("Eşleştirme kodu");
  fireEvent.change(input, { target: { value: "abcd" } });
  expect(screen.getByRole("img", { name: "Logo" })).toHaveAttribute("src", "/logo.jpg");
  fireEvent.change(input, { target: { value: "abcdefgh" } });
  await waitFor(() => expect(screen.getByRole("img", { name: "Logo" })).toHaveAttribute("src", "/api/pairing/branding/logo?code=abcdefgh"));
  fireEvent.error(screen.getByRole("img", { name: "Logo" }));
  expect(screen.getByRole("img", { name: "Logo" })).toHaveAttribute("src", "/logo.jpg");
  fireEvent.change(input, { target: { value: "abcd1234" } });
  await waitFor(() => expect(screen.getByRole("img", { name: "Logo" })).toHaveAttribute("src", "/api/pairing/branding/logo?code=abcd1234"));
  fireEvent.change(input, { target: { value: "abc" } });
  expect(screen.getByRole("img", { name: "Logo" })).toHaveAttribute("src", "/logo.jpg");
});
