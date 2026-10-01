import { tr } from "../i18n";
import { useUploads } from "./UploadProvider";
import { ConflictControls } from "./ConflictControls";
import type { UploadRow } from "./types";

function bytes(value: number): string {
  const unit = Math.min(3, Math.floor(Math.log(Math.max(1, value)) / Math.log(1024)));
  return `${new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 1 }).format(value / 1024 ** unit)} ${tr.upload.units[unit]}`;
}
const formats = ".jpg,.jpeg,.png,.webp,.heic,.heif,.mp4,.mov,image/jpeg,image/png,image/webp,image/heic,image/heif,video/mp4,video/quicktime";

function UploadItem({ row }: { row: UploadRow }) {
  const { controller, snapshot } = useUploads();
  const count = row.status?.received_bytes ?? 0;
  const percentage = new Intl.NumberFormat("tr-TR", { style: "percent", maximumFractionDigits: 0 }).format(row.size ? count / row.size : 0);
  const receiving = row.status?.status === "receiving";
  const selectFile = ["needs-file", "retryable", "failed", "expired"].includes(row.phase);
  const label = receiving || (!row.status && row.identity) ? tr.upload.reselect : tr.upload.newFile;
  return <li className="upload-row" aria-labelledby={`${row.id}-name`}>
    <div className="upload-row-heading"><h3 id={`${row.id}-name`} tabIndex={-1}>{row.filename}</h3>
      <p className="upload-phase" role="status" aria-label={row.filename}>{tr.upload.phases[row.phase]}</p></div>
    <progress value={count} max={Math.max(1, row.size)} aria-label={row.filename} />
    <p className="upload-count muted">{bytes(count)} / {bytes(row.size)} <span>{percentage}</span></p>
    {row.phase === "preparing" && <div className="upload-preparation"><p className="muted">{tr.upload.preparingHelp}</p>
      <progress value={row.preparedBytes} max={Math.max(1, row.size)} aria-label={`${tr.upload.preparationProgress}: ${row.filename}`} /></div>}
    {row.phase === "queued" || row.phase === "processing" ? <p className="muted">{tr.upload.processingHelp}</p> : null}
    {(row.error || row.phase === "failed") && <div role="alert" className="upload-error"><p>{row.phase === "failed" ? tr.upload.validationFailed : tr.upload.errors[row.error!]}</p>
      {row.diagnostic && <p className="upload-diagnostic">{row.diagnostic}</p>}</div>}
    <div className="upload-actions">
      {["preparing", "waiting", "uploading"].includes(row.phase) && <button onClick={() => controller.pause(row.id)}>{tr.upload.pause}</button>}
      {row.phase === "paused" && <button onClick={() => void controller.resume(row.id)}>{tr.upload.resume}</button>}
      {(row.phase === "retryable" || ((row.phase === "queued" || row.phase === "processing") && row.error)) && <button onClick={() => void controller.retry(row.id)}>{tr.retry}</button>}
      {["failed", "expired"].includes(row.phase) && <button onClick={() => void controller.retry(row.id)}>{tr.upload.startNew}</button>}
      {["finalized", "failed", "expired", "conflict", "skipped"].includes(row.phase) && <button disabled={!!snapshot.resolvingId} onClick={() => controller.dismiss(row.id)}>{tr.upload.dismiss}</button>}
    </div>
    {row.phase === "conflict" && <ConflictControls key={JSON.stringify(row.status?.conflicts)} row={row} />}
    {selectFile && <div className="upload-reselect"><label htmlFor={`${row.id}-file`}>{label}: {row.filename}</label>
      <input id={`${row.id}-file`} type="file" accept={formats} onChange={event => {
        const selected = event.currentTarget.files?.[0]; event.currentTarget.value = "";
        if (!selected) return;
        if (row.phase === "failed" || row.phase === "expired" || !row.status) void controller.retry(row.id, selected);
        else void controller.resume(row.id, selected);
      }} /></div>}
  </li>;
}

export function UploadPanel() {
  const { snapshot, controller } = useUploads();
  return <section className="summary-sheet upload-panel" aria-labelledby="upload-heading">
    <h2 id="upload-heading">{tr.upload.title}</h2>
    <p>{tr.upload.intro}</p>
    <div className="upload-picker"><label htmlFor="upload-files">{tr.upload.choose}</label>
      <input id="upload-files" type="file" multiple accept={formats} disabled={!snapshot.limits || snapshot.limitsError}
        aria-describedby="upload-formats upload-recovery" onChange={event => {
          const files = Array.from(event.currentTarget.files ?? []); event.currentTarget.value = "";
          void controller.add(files);
        }} />
      <p id="upload-formats" className="muted">{tr.upload.formats}</p>
      <p id="upload-recovery" className="muted">{tr.upload.recoveryHelp}</p></div>
    {snapshot.limits && <p className="muted">{tr.upload.fileLimit}: {bytes(snapshot.limits.max_file_bytes)} · {tr.upload.packageLimit}: {bytes(snapshot.limits.max_package_bytes)}</p>}
    {snapshot.limitsError && <div role="alert" className="notice"><p>{tr.upload.limitsFailed}</p>
      <button onClick={() => void controller.initialize(new AbortController().signal)}>{tr.retry}</button></div>}
    {!snapshot.storageAvailable && <p role="status" className="notice">{tr.upload.storageUnavailable}</p>}
    {snapshot.rows.length ? <ul className="upload-rows">{snapshot.rows.map(row => <UploadItem key={row.id} row={row} />)}</ul>
      : <p className="muted">{tr.upload.empty}</p>}
  </section>;
}
