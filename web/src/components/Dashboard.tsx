import type {
  DashboardOut,
  DashboardSlotOut,
  OneoffDecisionOut,
} from "../api/openapi";
import { useEffect, useId, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { formatDate, statusLabel, tr } from "../i18n";
import { useLivePhase } from "../liveProvider";
import { CollapsiblePanel } from "./CollapsiblePanel";
import { workspaceHref } from "../demo/routing";

function OneoffDateEditor({
  slot,
  regular,
  enabled,
  onRefresh,
  onDecision,
}: {
  slot: DashboardSlotOut;
  regular?: string;
  enabled: boolean;
  onRefresh: () => void;
  onDecision: (slot: DashboardSlotOut, action: "review" | "skip") => void;
}) {
  const [confirmSkip, setConfirmSkip] = useState(false);
  const [editing, setEditing] = useState(false),
    [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false),
    [error, setError] = useState<string | null>(null);
  const [time, setTime] = useState(() =>
    new Date(new Date(slot.due_at).getTime() + 3 * 3600000)
      .toISOString()
      .slice(0, 16),
  );
  const flight = useRef<AbortController | null>(null),
    id = useId();
  useEffect(() => () => flight.current?.abort(), []);
  const dueAt = `${time}:00+03:00`;
  const valid =
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(time) &&
    Date.parse(dueAt) > Date.now() &&
    (!regular || Date.parse(dueAt) < Date.parse(regular));
  async function save() {
    if (
      !enabled ||
      !valid ||
      error ||
      flight.current ||
      slot.occurrence_id == null ||
      Date.parse(slot.due_at) <= Date.now()
    )
      return;
    const controller = new AbortController();
    flight.current = controller;
    setBusy(true);
    try {
      await api.changeOneoffDate(
        slot.occurrence_id,
        { expected_due_at: slot.due_at, new_due_at: dueAt },
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setSaved(true);
        setEditing(false);
        onRefresh();
      }
    } catch (failure) {
      if (!controller.signal.aborted)
        setError(
          failure instanceof ApiError && failure.status === 400
            ? tr.oneoffDate.invalid
            : tr.oneoffDate.changed,
        );
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      flight.current = null;
    }
  }
  return (
    <div>
      {!editing && (
        <div className="upload-actions">
          <button
            className="primary"
            disabled={!enabled || busy || saved}
            onClick={() => onDecision(slot, "review")}
          >
            {tr.oneoffDate.review}
          </button>
          <button
            disabled={!enabled || busy || saved}
            onClick={() => setConfirmSkip(true)}
          >
            {tr.review.skip}
          </button>
          <button
            disabled={!enabled || busy || saved}
            onClick={() => setEditing(true)}
          >
            {tr.oneoffDate.edit}
          </button>
        </div>
      )}
      {confirmSkip && (
        <div className="review-confirmation">
          <p>{tr.review.skipWarning}</p>
          <div className="upload-actions">
            <button
              disabled={!enabled || busy || saved}
              onClick={() => {
                setConfirmSkip(false);
                onDecision(slot, "skip");
              }}
            >
              {tr.review.confirm.skip}
            </button>
            <button disabled={busy} onClick={() => setConfirmSkip(false)}>
              {tr.oneoffDate.cancel}
            </button>
          </div>
        </div>
      )}
      {editing && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <label htmlFor={id}>{tr.oneoffDate.label}</label>
          <input
            id={id}
            type="datetime-local"
            required
            value={time}
            aria-describedby={`${id}-help`}
            disabled={!enabled || busy}
            onChange={(event) => {
              setTime(event.target.value);
              if (error === tr.oneoffDate.invalid) setError(null);
            }}
          />
          <p id={`${id}-help`} className="muted">
            {tr.oneoffDate.help}
          </p>
          {regular && (
            <p>
              {tr.review.nextRegular}: {formatDate(regular)}
            </p>
          )}
          <button disabled={!enabled || !valid || busy || !!error}>
            {busy ? tr.settingsPage.saving : tr.oneoffDate.save}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setEditing(false)}
          >
            {tr.oneoffDate.cancel}
          </button>
        </form>
      )}
      {saved && <p role="status">{tr.oneoffDate.saved}</p>}
      {error && (
        <>
          <p role="alert">{error}</p>
          <button onClick={onRefresh}>{tr.oneoffDate.refresh}</button>
        </>
      )}
    </div>
  );
}

export function PendingActions({ data }: { data: DashboardOut }) {
  if (!data.pending_actions.length) return null;
  return (
    <CollapsiblePanel className="pending-section" title={tr.pending}>
        <ul className="action-list">
          {data.pending_actions.map((action) => (
            <li key={`${action.occurrence_id}-${action.review_id}`}>
              <div>
                <h3>{statusLabel(action.review_status ?? action.state)}</h3>
                <p>{formatDate(action.due_at)}</p>
              </div>
              <a
                className="action-link"
                href={
                  workspaceHref(action.review_id
                    ? `#/package?review=${action.review_id}`
                    : "#/package")
                }
              >
                {action.review_id ? tr.reviewSummary : tr.openPackage}
              </a>
            </li>
          ))}
        </ul>
    </CollapsiblePanel>
  );
}

export function ConnectionSummary({ data }: { data: DashboardOut }) {
  return (
    <section className="connections" aria-labelledby="connections-title">
      <h2 id="connections-title">{tr.systems}</h2>
      <dl>
        <div>
          <dt>{tr.instagram}</dt>
          <dd>
            <span className={`status status-${data.instagram.health}`}>
              {statusLabel(data.instagram.health)}
            </span>
            <small>
              {data.instagram.username
                ? `@${data.instagram.username}`
                : tr.noAccount}
            </small>
          </dd>
        </div>
        <div>
          <dt>{tr.worker}</dt>
          <dd>
            <span className={`status status-${data.worker.status}`}>
              {statusLabel(data.worker.status)}
            </span>
            {data.worker.phase && (
              <small>{statusLabel(data.worker.phase)}</small>
            )}
          </dd>
        </div>
      </dl>
      <p className="muted">{tr.workerHelp}</p>
    </section>
  );
}

const openReview = (id: number) => {
  window.location.hash = workspaceHref(`#/package?review=${id}`);
};

export function Dashboard({
  data,
  stale = false,
  onRefresh = () => {},
  onOpenReview = openReview,
}: {
  data: DashboardOut;
  stale?: boolean;
  onRefresh?: () => void;
  onOpenReview?: (id: number) => void;
}) {
  const slots = data.next_slots ?? (data.next_slot ? [data.next_slot] : []);
  const phase = useLivePhase();
  const [oneoff, setOneoff] = useState<OneoffDecisionOut | null>(null);
  const [deciding, setDeciding] = useState(false),
    [decisionError, setDecisionError] = useState<string | null>(null);
  const decisionFlight = useRef<AbortController | null>(null);
  const decisionSnapshot = useRef<DashboardOut | null>(null);
  const openedReview = useRef(false);
  const enabled = !stale && navigator.onLine && phase === "live";
  useEffect(() => () => decisionFlight.current?.abort(), []);
  useEffect(() => {
    if (
      !enabled ||
      !oneoff ||
      oneoff.status !== "pending" ||
      openedReview.current
    )
      return;
    const actions = data.pending_actions.filter(
      (item) => item.occurrence_id === oneoff.occurrence_id,
    );
    if (
      data !== decisionSnapshot.current &&
      !actions.length &&
      !slots.some((slot) => slot.occurrence_id === oneoff.occurrence_id)
    ) {
      setOneoff(null);
      setDecisionError(tr.reviewGone);
      return;
    }
    const action = actions.find((item) => item.state === "review_ready");
    if (!action || action.review_id == null) return;
    if (
      oneoff.package_folder &&
      (action.package_folder !== oneoff.package_folder ||
        data.package?.folder_name !== oneoff.package_folder)
    ) {
      setDecisionError(tr.review.changedPackage);
      return;
    }
    openedReview.current = true;
    onOpenReview(action.review_id);
  }, [data, oneoff, enabled, onOpenReview]);
  async function decide(slot: DashboardSlotOut, action: "review" | "skip") {
    if (
      !enabled ||
      decisionFlight.current ||
      oneoff?.status === "pending" ||
      oneoff?.occurrence_id === slot.occurrence_id ||
      decisionError ||
      slot.occurrence_id == null ||
      Date.parse(slot.due_at) <= Date.now()
    )
      return;
    const controller = new AbortController();
    decisionFlight.current = controller;
    setDeciding(true);
    try {
      const result = await api.decideOneoff(
        slot.occurrence_id,
        { expected_due_at: slot.due_at, action, confirmed: action === "skip" },
        controller.signal,
      );
      if (!controller.signal.aborted) {
        if (
          result.occurrence_id !== slot.occurrence_id ||
          result.status !== (action === "skip" ? "skipped" : "pending")
        )
          throw new ApiError(0);
        decisionSnapshot.current = data;
        setOneoff(result);
        onRefresh();
      }
    } catch {
      if (!controller.signal.aborted) {
        setDecisionError(tr.oneoffDate.changed);
        onRefresh();
      }
    } finally {
      decisionFlight.current = null;
      if (!controller.signal.aborted) setDeciding(false);
    }
  }
  const regular = slots
    .filter(
      (slot) => slot.kind === "regular" && Date.parse(slot.due_at) > Date.now(),
    )
    .sort((a, b) => Date.parse(a.due_at) - Date.parse(b.due_at))[0]?.due_at;
  const [requested, setRequested] = useState(false),
    [occurrence, setOccurrence] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const flight = useRef(false);
  async function requestReview() {
    if (flight.current) return;
    flight.current = true;
    setRequested(true);
    try {
      setOccurrence((await api.manualPublish()).id);
    } catch {
      setFailed(true);
    }
  }
  return (
    <>
      <header className="page-heading">
        <h1 data-tour="dashboard-overview">{tr.dashboard}</h1>
        <p>{tr.dashboardIntro}</p>
      </header>
      <PendingActions data={data} />
      {oneoff && !decisionError && (
        <p role="status" className="notice">
          {oneoff.status === "skipped"
            ? tr.review.done.skip
            : tr.review.preparing}
        </p>
      )}
      {decisionError && (
        <div role="alert" className="notice">
          <p>{decisionError}</p>
          <button
            onClick={() => {
              setOneoff(null);
              setDecisionError(null);
              onRefresh();
            }}
          >
            {tr.oneoffDate.refresh}
          </button>
        </div>
      )}
      <div className="dashboard-columns">
        <div className="publishing-summary">
          <section>
            <h2>{tr.packageTitle}</h2>
            <h3>{data.package?.folder_name ?? tr.noPackage}</h3>
            <p>
              {data.package
                ? statusLabel(data.package.status)
                : tr.noPackageHelp}
            </p>
            <a href={workspaceHref("#/package")}>{tr.openPackage}</a>
            <p>{tr.manualHelp}</p>
            <button
              disabled={
                requested ||
                data.manual_review_allowed === false ||
                data.pending_actions.length > 0 ||
                slots.some(
                  (slot) => slot.kind === "manual" || slot.kind === "oneoff",
                ) ||
                !navigator.onLine
              }
              onClick={() => void requestReview()}
            >
              {tr.manualReview}
            </button>
            {occurrence !== null && (
              <p>
                <a
                  href={workspaceHref(`#/package?occurrence=${occurrence}${data.package ? `&folder=${encodeURIComponent(data.package.folder_name)}` : ""}`)}
                >
                  {tr.manualContinue}
                </a>
              </p>
            )}
            {failed && <p role="alert">{tr.manualUncertain}</p>}
          </section>
          <section>
            <h2>{tr.nextSlot}</h2>
            {slots.length === 0 ? (
              <h3 className="slot-date">{tr.noSlot}</h3>
            ) : (
              <ul className="action-list" aria-label={tr.nextSlot}>
                {slots.map((slot) => (
                  <li key={`${slot.kind}-${slot.due_at}`}>
                    <div>
                      <h3 className="slot-date">{formatDate(slot.due_at)}</h3>
                      <p>{statusLabel(slot.kind)}</p>
                      {slot.kind === "oneoff" &&
                        slot.occurrence_id != null &&
                        Date.parse(slot.due_at) > Date.now() && (
                          <OneoffDateEditor
                            key={`${slot.occurrence_id}-${slot.due_at}-${data.generated_at}`}
                            slot={slot}
                            regular={regular}
                            enabled={
                              enabled &&
                              !deciding &&
                              oneoff?.status !== "pending" &&
                              oneoff?.occurrence_id !== slot.occurrence_id &&
                              !decisionError
                            }
                            onRefresh={onRefresh}
                            onDecision={(slot, action) =>
                              void decide(slot, action)
                            }
                          />
                        )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <small>{tr.timezone}</small>
          </section>
        </div>
        <ConnectionSummary data={data} />
      </div>
    </>
  );
}
