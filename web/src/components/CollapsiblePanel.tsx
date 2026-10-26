import { useId, useRef, useState, type ReactNode } from "react";
import { tr } from "../i18n";
import { MediaActionIcon } from "../packages/MediaActionIcon";

const panelState = new Map<string, boolean>();

export function CollapsiblePanel({ title, className = "summary-sheet", level = 2, actions, defaultExpanded = true, stateKey, children }: {
  title: string; className?: string; level?: 2 | 3; actions?: ReactNode; defaultExpanded?: boolean; stateKey?: string; children: ReactNode;
}) {
  const id = useId(), [expanded, setExpanded] = useState(() => stateKey && panelState.has(stateKey) ? panelState.get(stateKey)! : defaultExpanded);
  const setOpen = (next: boolean) => { if (stateKey) panelState.set(stateKey, next); setExpanded(next); };
  const body = useRef<HTMLDivElement>(null);
  const Heading = level === 3 ? "h3" : "h2";
  const label = `${title} ${expanded ? tr.panel.collapse : tr.panel.expand}`;
  return <section className={className} aria-labelledby={`${id}-title`}>
    <div className="panel-heading"><Heading id={`${id}-title`}>{title}</Heading>
      <div className="panel-actions">{expanded && actions && <div className="panel-tools">{actions}</div>}
        <button type="button" className="media-icon-button panel-toggle" aria-label={label} title={label} aria-expanded={expanded} aria-controls={`${id}-body`}
          onClick={() => {
            if (expanded) body.current?.querySelectorAll<HTMLMediaElement>("video, audio").forEach(media => { if (!media.paused) media.pause(); });
            setOpen(!expanded);
          }}><MediaActionIcon action={expanded ? "collapse" : "expand"} /></button>
      </div>
    </div>
    <div ref={body} id={`${id}-body`} hidden={!expanded}>{children}</div>
  </section>;
}
