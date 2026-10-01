import type { SetupItemOut } from "../api/openapi";
import type { OnboardingStep } from "./types";

export function firstIncompleteRequired(checklist: SetupItemOut[]): OnboardingStep | null {
  return (checklist.find(item => item.required !== false && !item.complete)?.key as OnboardingStep) ?? null;
}
