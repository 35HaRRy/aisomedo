import { useState } from "react";
import { tr } from "../i18n";
import { ActivePackagePanel } from "./ActivePackagePanel";
import { CompletedPackages } from "./CompletedPackages";
import { usePackageEditorContext } from "./PackageEditorProvider";

export function PackageManager() {
  const [completed, setCompleted] = useState(false), editor = usePackageEditorContext();
  return completed ? <CompletedPackages onBack={() => setCompleted(false)} /> : <>
    <div className="package-mode-actions"><button disabled={editor.busy} onClick={async () => { if (await editor.requestLeave()) setCompleted(true); }}>{tr.packageManagement.completed}</button></div>
    <ActivePackagePanel />
  </>;
}
