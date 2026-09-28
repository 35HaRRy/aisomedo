# Deployment and Single-Scheduler Leadership

Issue: #21 — Deployment and single-scheduler leadership

## Intent and approved deployment direction

Deploy Dojo Social Publishing reproducibly on one Linux VPS with PostgreSQL,
FastAPI, a Python worker, the built React frontend, durable media, and HTTPS.
Multiple worker processes must not emit duplicate due publication work.

The user approved a dedicated-domain deployment with bundled HTTPS and support
for an existing reverse proxy. Each installation lives at its domain root.

## Deployment architecture

Use one web gateway image containing the built frontend and Caddy. It serves
static assets with SPA fallback and proxies backend routes without rewriting
their paths. API and signed publication artifact requests must never fall
through to the SPA. Raw media volumes are not mounted into the gateway.

Provide a production Compose definition and explicit mode overrides:

- Dedicated-domain mode: Caddy owns ports 80/443, obtains and renews public TLS
  certificates, and persists certificate state in a named volume.
- Existing-proxy mode: the gateway listens on HTTP. A host-based proxy reaches
  a configurable loopback-bound port; a container-based proxy can instead join
  an explicitly configured external Docker network. The upstream proxy owns TLS.

Both modes use a configured public HTTPS origin for browser access, OAuth
callbacks, and signed artifact URLs. Frontend API requests are same-origin.
Forwarded client and scheme headers are accepted only from configured proxy
addresses/networks. Preserve secure cookies and correct client identity for
pairing throttling through the proxy chain.

Production PostgreSQL and backend have no published host ports. Persistent
named volumes retain database and media state across container recreation.
Backend and worker mount the same media volume at the same path. Document
volume lifecycle and existing-data migration explicitly; deploying production
must not silently substitute an empty volume for an existing installation.

Keep local development commands usable. Production configuration must include
required secrets, restart policies, dependency readiness, and health probes
needed to verify deployment. Serialize schema initialization before application
process startup rather than depending on concurrent create-all calls.

Build Python images from the committed lockfile and frontend from its package
lockfile. Include required media tooling wherever existing request/worker paths
actually execute it. Configuration examples contain placeholders, never real
credentials. Public-domain TLS verification requires DNS and a reachable VPS.

## Scheduler coordination

Keep orchestration behind the Dojo Publishing seam. Add a narrow coordination
boundary implemented with PostgreSQL advisory locking; do not add Redis or a
lease service.

Recommended leadership semantics are one elected scheduler per scheduling turn:
try a non-blocking transaction-scoped advisory lock, skip emission if another
worker holds it, and release it on commit/rollback. A worker can become the next
leader after the previous turn ends or its database session terminates. Stable
process identity across turns is not required.

All database writes that emit due work must use the transaction holding that
lock. A separate lock connection followed by unrestricted writes on another
connection is insufficient: a disconnected former leader must not keep emitting.
Adapt store transaction boundaries so existing per-method commits do not release
leadership prematurely. Exceptions roll back the emission turn; later ticks retry.

Keep long-running rendering and external HTTP requests outside the emission
transaction. Classify existing tick operations explicitly during implementation:
schedule evaluation emits work under leadership; job execution uses existing
atomic claims; reminder, token-maintenance, and reconciliation operations must
not become unintentionally concurrent merely because followers can run jobs.
Coordinate those singleton operations separately where needed.

Leadership is supplemented by database-backed idempotency:

- Repeated evaluation of the same regular due time creates one occurrence.
- One occurrence/revision pair creates at most one durable Yayın İncelemesi.
- A package/revision has at most one queued or processing render job, including
  when API and scheduler paths request that render concurrently.
- Failed/completed jobs do not permanently suppress legitimate explicit retries.
- Render enqueue audit events reflect jobs actually created.

Any required constraints/indexes need an explicit upgrade path for existing
databases, including preflight reporting of conflicting existing rows. Do not
silently delete historical jobs or reviews to satisfy a new constraint.

These guarantees concern scheduler work emission. Preserve existing publication
reconciliation for uncertain remote results; do not claim exactly-once effects
at an external publishing API.

## Errors and operation

Database unavailability or lost leadership prevents emission and is logged.
Workers retry on later turns without a tight loop. SIGTERM allows bounded clean
shutdown; abrupt worker/database-session death releases database coordination.

Document fresh installation, both proxy modes, required DNS/ports, environment
configuration, startup, health verification, worker scaling, restart, and
persistent-volume preservation. Automatic release deployment and rollback remain
owned by #39; broad monitoring and backups are covered by #22 and #23.

## Verification

Use real PostgreSQL integration tests for competing worker connections, repeated
ticks, lock-holder termination, exception rollback, and takeover. Assert durable
occurrence/review/job outcomes through the publishing seam. Include a slow-render
case where later ticks do not enqueue a second job for the same revision, plus
concurrent API/scheduler requests and allowed retry after failure.

Validate both Compose modes and gateway configurations; build backend, worker,
and frontend images. Verify frontend deep links, API routing, signed artifact
routing, forwarded headers, secure cookies, and isolation of backend/database
ports. Recreate containers and verify persisted database/media content remains.

A deployment smoke test exercises the assembled stack. Verify real public HTTPS
and certificate issuance on a configured VPS when available; distinguish that
evidence from local TLS/proxy tests in the completion report.

## Review status

Deployment direction approved in conversation. Written design, including
per-turn leadership semantics and durable deduplication, awaits user review.
