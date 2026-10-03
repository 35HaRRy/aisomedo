import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { tr } from "../i18n";
import { usePackageEditor, type PackageEditorState } from "./usePackageEditor";

export type PackageEditorContext = PackageEditorState & { requestLeave(): Promise<boolean> };
const Context = createContext<PackageEditorContext | null>(null);
type Decision = "save" | "discard" | "cancel";
export function PackageEditorProvider({ children }: { children: ReactNode }) {
  const editor = usePackageEditor();
  const [prompt, setPrompt] = useState<{ id?: string } | null>(null);
  const resolver = useRef<((value: Decision) => void) | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const active = useRef(editor); active.current = editor;
  const choose = useCallback((decision: Decision) => { resolver.current?.(decision); resolver.current = null; setPrompt(null); }, []);
  const ask = useCallback((id?: string) => {
    if (resolver.current) return Promise.resolve<Decision>("cancel");
    return new Promise<Decision>(resolve => { resolver.current = resolve; setPrompt({ id }); });
  }, []);
  const requestLeave = useCallback(async () => {
    if (active.current.busy) return false;
    if (!active.current.dirty) return true;
    const answer = await ask();
    if (answer === "discard") { active.current.discard(); return true; }
    return answer === "save" && await active.current.save();
  }, [ask]);
  const remove = useCallback(async (id: string) => {
    if (active.current.isDirty(id)) {
      const answer = await ask(id);
      if (answer === "cancel") return false;
      if (answer === "save" && !await active.current.save()) return false;
      if (answer === "discard") active.current.discard(id);
    }
    return active.current.remove(id);
  }, [ask]);
  useEffect(() => {
    if (!prompt) return;
    const prior = document.activeElement as HTMLElement | null;
    dialog.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); choose("cancel"); }
      if (event.key !== "Tab") return;
      const elements = Array.from(dialog.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", keys);
    return () => { document.removeEventListener("keydown", keys); prior?.focus(); };
  }, [prompt, choose]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (active.current.dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => { window.removeEventListener("beforeunload", warn); resolver.current?.("cancel"); };
  }, []);
  return <Context.Provider value={{ ...editor, remove, requestLeave }}>
    <div {...(prompt ? { inert: "" } : {})} aria-hidden={prompt ? true : undefined}>{children}</div>
    {prompt && <div className="editor-dialog-backdrop"><div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="draft-dialog-title" className="panel editor-dialog">
      <h2 id="draft-dialog-title">{tr.editor.leaveTitle}</h2><p>{prompt.id ? tr.editor.removeDraft : tr.editor.leaveHelp}</p>
      <div className="actions"><button onClick={() => choose("cancel")}>{tr.editor.cancel}</button>
        <button onClick={() => choose("discard")}>{tr.editor.discard}</button>
        <button disabled={!editor.canSave} onClick={() => choose("save")}>{tr.editor.saveContinue}</button></div>
    </div></div>}
  </Context.Provider>;
}
export function usePackageEditorContext(): PackageEditorContext {
  const value = useContext(Context);
  if (!value) throw new Error("PackageEditorProvider required");
  return value;
}
