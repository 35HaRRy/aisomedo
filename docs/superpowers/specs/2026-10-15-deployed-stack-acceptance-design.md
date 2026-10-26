# Deployed-stack acceptance suite — issue #40

## Intent and success criteria

Prove that an administrator can publish a Dojo Paylaşım Paketi through the
built web application and deployed services, both from a scheduled Yayın Zamanı
and from a manual publication request. The two workflows must exercise real
PostgreSQL, persisted media, schema initialization, FastAPI, the worker,
FFmpeg rendering, and the production web gateway.

The user selected browser-driven coverage and approved this design in chat.
Only external Meta and notification delivery, plus the clock, are controlled.
Passing means both workflows reach a confirmed Tamamlanmış Paket, with one
external publication each and the same immutable video reviewed and published.

## Approach and boundaries

Extend production Compose with an acceptance-only override, using the existing
backend, worker, and gateway image builds. Avoid a copied deployment definition.
Use existing Playwright tooling with a separate deployed-stack configuration;
the existing mocked browser suite remains independent.

HTTP-only acceptance was rejected because it misses browser integration.
A separate hand-built stack was rejected because it can drift from production.

This suite covers two successful publication paths, not the full domain matrix.
Existing tests retain responsibility for conflicts, recovery, stale approvals,
Android UI, and provider failure combinations. Real Instagram, Firebase delivery,
public DNS, certificate issuance, and Android devices are outside scope.

## Stack and isolation

Each invocation owns a uniquely named Compose project, fresh named database and
media volumes, synthetic credentials, and isolated fixture services. The runner
passes a dedicated environment file explicitly and never reads `ops/.env` or
uses `dojo-prod` resources. Test images are identified explicitly so an old
local `latest` image cannot silently substitute for the code under test.

The gateway serves the production web build and proxies real API and signed
media requests. A test-local HTTPS origin and trusted test certificate allow
signed video delivery without disabling production URL validation. Fixture
network routing resolves that origin locally; no public DNS or real account
credentials are required. Browser and fake Meta both trust the test certificate.

Fixtures must not send traffic to real Meta or notification providers. Fake
services fail on unexpected requests rather than inventing successful replies.
Readiness and all asynchronous assertions have finite deadlines.

## Test-only composition

Reuse existing publishing clock, notifier, and Meta HTTP adapter seams.
Acceptance-only bootstrap code selects a shared controllable clock, a notifier
that delivers to the collector, and the real HTTP Meta publisher targeting the
fake endpoint. Backend and worker use consistent time and external wiring.
Business operations still run through their ordinary production services.

Test controls belong only to fixture services and acceptance bootstrap files;
they are not added to the production HTTP API. Clock advancement changes the
clock observed by the normal worker loop; it does not call due-work methods
directly or write completed lifecycle rows into PostgreSQL.

Operator-only bootstrap may issue pairing codes and configure consent policy
through existing CLI/domain entry points. Browser actions perform pairing,
configuration, consent acceptance, upload, publication requests, and review
approval. A synthetic notification recipient may be registered through the
normal authenticated registration API, since a browser cannot register FCM as
an Android device. External connection fixture setup may establish synthetic
account credentials through existing connection seams; OAuth is not under test.
None of these setup operations may seed a review, render, or publication result.

## External fixtures and evidence

The fake Meta endpoint implements the Graph requests exercised by the real
publisher: container creation, processing status, publication, and confirmation.
It fetches the signed video URL over HTTP(S), records its byte digest and
caption, and confirms ingestion before reporting readiness. Persisted fixture
records expose container/publication identifiers and request counts to tests.

The notification collector records recipient and payload for actual notifier
calls. Each workflow must produce a review notification identifying its review
or occurrence. Notification receipt is not substituted for browser review checks.

The browser fetches the authenticated review preview and hashes its full video
bytes. Compare that digest with the fake Meta download, and verify the reviewed
caption equals the external publication caption. Real rendering must produce
playable, nonempty video, not just a successful render-status response.

## Browser workflows

Use two independently identifiable packages and publication records. The cases
may share one isolated stack and installation setup, but each uploads its own
media and establishes its own publication preconditions.

### Scheduled publication

1. Pair, complete required setup, and configure a Dojo Yayın Planı in the UI.
2. Upload real fixture media to the Aktif Paket and wait for finalization.
3. Advance controlled time across the configured due boundary.
4. Wait for the normal worker to create the Yayın İncelemesi and its notification.
5. Open the review in the browser, verify caption and playable immutable preview,
   then approve through the confirmation UI.
6. Wait for confirmed publication; verify a Tamamlanmış Paket, matching video
   bytes/caption, external identifiers, and exactly one external publish command.

### Manual publication

1. Upload distinct real media to the next Aktif Paket.
2. Request manual publication through the UI before the next recurring due time.
3. Wait for the review and notification; verify preview/caption and approve.
4. Assert the same confirmation, digest, and exactly-once evidence as above.
5. Verify manual publication did not move the recurring plan's next due time.

After completion, allow another worker turn and confirm publication counts
remain unchanged. Completion evidence must include public API/UI state and the
documented completed-folder contract on the real shared media volume; private
SQL table layout and private event class names are not assertion contracts.

## CI, diagnostics, and verification

Run this suite as a required CI check before image publication/deployment,
reusing the existing verified image builds where practical. Missing Docker,
Chromium, media tools, fixture readiness, or tests must fail required CI rather
than turn into a green skipped suite. Document one local invocation and its
prerequisites; report unavailable local execution explicitly.

On failure retain Playwright trace/screenshot, bounded Compose logs and service
status, and fake-service evidence. Use synthetic tokens only and avoid logging
cookies, credential headers, or signed URL query secrets. Cleanup runs on success
and failure and removes only the invocation's project-owned resources; cleanup
failure must be visible.

During implementation run focused fixture/wiring checks and typechecking, then
both real deployed workflows and existing affected suites. Before completion,
run the full repository test suites available in the environment, review the
diff against this specification and repository standards, and commit only this
issue's changes on the current branch. Record any unavailable verification
without claiming it passed.
