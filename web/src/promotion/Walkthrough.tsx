import { useEffect, useState } from "react";
import { driver, type Driver } from "driver.js";
import { readTourProgress, resetTourProgress, writeTourProgress } from "./tourProgress";
import { tours, type TourId } from "./tours";
import "./promotion.css";

export function replayTours(clientId: number): void {
  resetTourProgress(clientId);
  window.dispatchEvent(new CustomEvent("aisomedo:replay-tours", { detail: clientId }));
}

export function Walkthrough({ clientId, tour, enabled }: { clientId: number; tour: TourId; enabled: boolean }) {
  const [replay, setReplay] = useState(0);
  useEffect(() => {
    const restart = (event: Event) => { if ((event as CustomEvent<number>).detail === clientId) setReplay(value => value + 1); };
    window.addEventListener("aisomedo:replay-tours", restart);
    return () => window.removeEventListener("aisomedo:replay-tours", restart);
  }, [clientId]);
  useEffect(() => {
    if (!enabled) return;
    let instance: Driver | null = null, started = false, quiet = false;
    let returnFocus: HTMLElement | null = null;
    const blocked = () => !!document.querySelector('dialog[open], [role="dialog"]:not(.driver-popover), [aria-modal="true"]:not(.driver-popover), .editor-dialog-backdrop, .review-confirmation');
    const visible = (selector: string) => {
      const node = document.querySelector<HTMLElement>(selector);
      return node && node.getClientRects().length && !node.closest('[hidden], [inert]') ? node : null;
    };
    function stop() { quiet = true; instance?.destroy(); instance = null; }
    function attempt() {
      if (instance?.isActive()) {
        const target = instance.getActiveElement();
        if (!target?.isConnected || !target.getClientRects().length || blocked()) stop();
        return;
      }
      if (started || blocked()) return;
      const progress = readTourProgress(clientId);
      if (progress.skipAll || progress.dismissed.includes(tour)) return;
      const remaining = tours[tour].filter(step => !progress.completed.includes(step.id) && visible(step.target));
      if (!remaining.length) return;
      started = true;
      returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      const advance = () => {
        const index = instance?.getActiveIndex() ?? 0, step = remaining[index];
        if (!step || !visible(step.target)) { stop(); return; }
        const latest = readTourProgress(clientId);
        writeTourProgress(clientId, { ...latest, completed: [...latest.completed, step.id] });
        if (index + 1 === remaining.length) stop();
        else if (visible(remaining[index + 1].target)) instance?.moveNext();
        else stop();
      };
      instance = driver({
        animate: !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
        smoothScroll: false, disableActiveInteraction: true, overlayClickBehavior: "none",
        showProgress: true, progressText: "{{current}} / {{total}}", nextBtnText: "İleri", prevBtnText: "Geri", doneBtnText: "Bitir", closeBtnLabel: "Tanıtımı kapat",
        steps: remaining.map(step => ({ element: step.target, popover: { title: step.title, description: step.description, side: "bottom", align: "start" } })),
        onNextClick: advance, onDoneClick: advance,
        onDestroyStarted: () => {
          if (!quiet) { const latest = readTourProgress(clientId); writeTourProgress(clientId, { ...latest, dismissed: [...latest.dismissed, tour] }); }
          instance?.destroy();
        },
        onDestroyed: () => { if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true }); },
        onPopoverRender: popover => {
          popover.wrapper.setAttribute("role", "dialog");
          popover.wrapper.setAttribute("aria-modal", "true");
          popover.wrapper.setAttribute("aria-label", popover.title.textContent ?? "Tanıtım");
          const skip = document.createElement("button");
          skip.textContent = "Tüm tanıtımları geç"; skip.className = "promotion-skip-tours";
          skip.onclick = () => { writeTourProgress(clientId, { ...readTourProgress(clientId), skipAll: true }); stop(); };
          popover.footer.appendChild(skip);
          popover.wrapper.onkeydown = event => {
            if (event.key !== "Tab") return;
            const controls = [...popover.wrapper.querySelectorAll<HTMLButtonElement>("button")].filter(node => !node.disabled && node.getClientRects().length);
            const first = controls[0], last = controls[controls.length - 1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
          };
          queueMicrotask(() => { if (popover.wrapper.isConnected) popover.nextButton.focus({ preventScroll: true }); });
        },
      });
      instance.drive();
    }
    // Wait for the real page's asynchronously loaded controls; never fabricate targets.
    const observer = new MutationObserver(attempt);
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "open", "aria-modal", "inert"] });
    const timer = window.setTimeout(attempt, 500);
    return () => { window.clearTimeout(timer); observer.disconnect(); stop(); };
  }, [clientId, tour, enabled, replay]);
  return null;
}
