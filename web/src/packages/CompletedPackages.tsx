import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CompletedPackageOut, PackageArtifactOut } from "../api/openapi";
import { tr } from "../i18n";
import { useSession } from "../session";
import { useLiveData } from "../useLiveData";

function ArtifactLinks({ artifacts }: { artifacts: PackageArtifactOut[] }) {
  const copy = tr.packageManagement;
  return <ul className="artifact-links">{artifacts.map(artifact => <li key={artifact.artifact_ref}>
    {artifact.url && artifact.available ? <a href={artifact.url}>{artifact.kind === "original" ? copy.originalDownload : artifact.kind === "processed" ? copy.processedDownload : copy.renderDownload} — {artifact.filename}</a>
      : <span>{artifact.filename} — {copy.fileMissing}</span>}
  </li>)}</ul>;
}
export function CompletedPackages({ onBack }: { onBack(): void }) {
  const copy = tr.packageManagement, list = useLiveData(api.completedPackages);
  const { invalidate } = useSession();
  const [folder, setFolder] = useState(""), [detail, setDetail] = useState<CompletedPackageOut | null>(null);
  const [error, setError] = useState(false), [retry, setRetry] = useState(0);
  useEffect(() => {
    if (list.data && !list.data.some(p => p.folder_name === folder)) setFolder(list.data[0]?.folder_name ?? "");
  }, [list.data, folder]);
  useEffect(() => {
    setDetail(null); setError(false);
    if (!folder) return;
    const controller = new AbortController();
    void api.completedPackage(folder, controller.signal).then(value => {
      if (!controller.signal.aborted) setDetail(value);
    }).catch(failure => {
      if (controller.signal.aborted) return;
      if (failure instanceof ApiError && failure.status === 401) invalidate();
      else setError(true);
    });
    return () => controller.abort();
  }, [folder, retry, invalidate]);
  const render = detail?.artifacts.find(a => a.kind === "render");
  return <section className="summary-sheet completed-packages" aria-labelledby="completed-title">
    <div className="package-section-heading"><h2 id="completed-title">{copy.completed}</h2><button onClick={onBack}>{copy.backActive}</button></div>
    <p className="muted">{copy.readOnly}</p>
    {list.error && <div role="alert" className="notice"><p>{copy.historyError}</p><button onClick={list.retry}>{tr.retry}</button></div>}
    {!list.data && !list.error && <p role="status">{tr.loading}</p>}
    {list.data && !list.data.length && <p>{copy.noCompleted}</p>}
    {!!list.data?.length && <label className="completed-picker">{copy.chooseCompleted}<select value={folder} onChange={event => setFolder(event.target.value)}>{list.data.map(p => <option key={p.id} value={p.folder_name}>{p.folder_name}</option>)}</select></label>}
    {error && <div role="alert" className="notice"><p>{copy.historyError}</p><button onClick={() => setRetry(retry + 1)}>{tr.retry}</button></div>}
    {folder && !detail && !error && <p role="status">{tr.loading}</p>}
    {detail && <div className="completed-detail"><h3>{detail.folder_name}</h3>
      {render?.preview_url && <video className="completed-render" src={render.preview_url} controls playsInline preload="metadata" aria-label={copy.finalPreview} />}
      <ArtifactLinks artifacts={detail.artifacts.filter(a => a.kind === "render")} />
      {detail.caption && <p className="completed-caption">{detail.caption}</p>}
      <ul className="package-media-list">{[...detail.media].sort((a, b) => {
        const x = detail.order.indexOf(a.media_id), y = detail.order.indexOf(b.media_id);
        return (x < 0 ? Infinity : x) - (y < 0 ? Infinity : y);
      }).map(media => <li key={media.media_id}><h3>{media.filename}</h3>
        {media.status === "removed" && <p className="muted">{copy.removed}</p>}
        {media.preview_url && (media.content_type.startsWith("video/") ? <video className="completed-media-preview" src={media.preview_url} controls playsInline preload="metadata" aria-label={`${media.filename} ${copy.preview}`} /> : <img className="package-photo-preview" src={media.preview_url} alt={`${media.filename} ${copy.preview}`} loading="lazy" />)}
        <ArtifactLinks artifacts={media.artifacts} />
      </li>)}</ul>
    </div>}
  </section>;
}
