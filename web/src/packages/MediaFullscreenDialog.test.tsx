import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MediaFullscreenDialog } from "./MediaFullscreenDialog";
import { packageSnapshot } from "./testFixtures";

it("uses original without processed fallback and restores entry focus after dismissal", () => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  const trigger = document.createElement("button"); document.body.append(trigger); trigger.focus();
  const media = packageSnapshot().media[0], close = vi.fn();
  const view = render(<MediaFullscreenDialog media={media} onClose={close} />);
  const dialog = screen.getByRole("dialog"), video = view.container.querySelector("video")!;
  expect(video).toHaveAttribute("src", media.original_url);
  expect(screen.getByRole("button", { name: "Tam ekranı kapat" })).toHaveFocus();
  fireEvent.error(video);
  expect(screen.getByRole("alert")).toHaveTextContent("Orijinal medya oynatılamıyor");
  expect(view.container.querySelector("video")).toBeNull();
  fireEvent(dialog, new Event("cancel", { cancelable: true }));
  expect(close).toHaveBeenCalledOnce();
  view.unmount(); expect(trigger).toHaveFocus(); trigger.remove();
});
