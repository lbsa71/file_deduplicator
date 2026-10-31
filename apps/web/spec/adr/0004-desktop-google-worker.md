# ADR 0004: Desktop Google worker and investigation protocol

Status: Accepted; initial read-only worker implemented — 2026-10-31.

Ubuntu owns policy, pairing and durable jobs. The desktop extension opens an
outbound WSS connection and runs explicit operations inside its authenticated
Google Photos tab. Google cookies and page session values stay on the desktop.
First delivery runs inventory-counts only. Live Google enumeration was qualified
in the preceding browser investigation; the complete worker pipeline has synthetic
HTTPS/WSS browser coverage and still needs the user's desktop pairing.

## Connection and authority

An authenticated PhotoFlow administrator issues a 256-bit single-use pairing code,
valid five minutes and bound to the expected Google account. The extension reads
its actual account before exchanging the code over HTTPS. Ubuntu returns a
PhotoFlow-only worker token, expiring after 14 days, stored in trusted extension
local storage. Ubuntu stores only hashes of codes/tokens in private state.

WSS credentials travel in the first message, never the URL. Both pairing and WSS
require an extension Origin. The worker token, current administrator role and
account are checked before dispatch and on subsequent messages. Revocation wakes
and closes the connection. One connection is allowed for a paired account, and
one Google account is paired per Linux user. Pairing that account to another
Linux user is rejected. A new pairing invalidates prior credentials.

The first handshake pins protocol 1 and the exact operation/version capability
set supported by this release. Incompatible extensions stop; update both ends
when changing the contract. There is no generic JavaScript/RPC/URL execution job.
Only inventory-counts version 1 with an empty input is registered. Results must
contain exactly photos/favorites/albums integer counts, complete=true and
retentionReady=false. No retention decision may rely on these counts alone.

## Jobs and transport

Administrators create jobs through the authenticated same-origin/CSRF API. Pairing
also queues the initial inventory. A read queued during an outage waits for the
browser. WSS pushes available jobs immediately; no HTTP job polling is required.
The PhotoFlow UI refreshes connection/job status every five seconds.

Each dispatch has a job ID, fresh lease, attempt number, operation/version, input
and Google account. A result must match the active worker and current lease before
it can be committed. A job has a ten-minute attempt deadline; individual reads
retain existing transport/body/pagination limits. Duplicate pending submissions
coalesce. The worker serializes jobs and bounds its in-memory completed history.

Heartbeat messages every 20 seconds keep the socket/Chrome worker active. The
server ends a connection after 45 seconds without activity. Browser alarm events
provide a restart/reconnect opportunity every minute; network reconnect attempts
back off from one to 30 seconds. A policy/protocol rejection pauses reconnecting
until explicit user action or pairing. Browser shutdown/sleep still suspends work.

Only read jobs may be requeued automatically after connection loss or restart.
Old leases cannot complete a newer attempt. Effect classification has an unknown
outcome path for future writes, but adding any mutation requires its own durable
intent, postcondition/reconciliation and qualification work; the current worker
cannot execute one. Google account changes stop dependent reads. A disconnected
worker checks its active state before starting another photo request.

Large media bytes belong on authenticated HTTPS transfer endpoints when image
uploading is implemented. They do not belong in WSS job messages. Video uploads
and Takeout export/download automation are outside the agreed scope.

## Investigation and troubleshooting

Server state lives in PHOTOFLOW_STATE/google-workers/workers.sqlite, separately
from the rebuildable photo catalog. Directory permissions are 0700; database is
0600. Back up this state consistently if pairing/job history must survive loss
of the server state disk. Current deployment supports a single application process;
connection ownership and wake events are in memory, while jobs are durable.

Both ends expose structured diagnostics correlated by job ID. Ubuntu preserves the job's Google account association across re-pairing and exports an opaque account reference. It records
attempts, timestamps (epoch seconds), allowlisted phases and controlled error codes.
The UI offers an owner-scoped Download job diagnostics action. No tokens or Google
media identifiers appear in that export. Server events retain the latest 32 phases.

The extension's Download worker diagnostics exports the latest job's phases
(epoch milliseconds), operation/version, attempt, and sanitized returned RPC shapes.
One sanitizer maintains aliases within that job only. At most eight recent read entries
and 512 KiB of evidence are retained; body omission/parse failure sets limited=true.
A controlled parser-rule code and framing/tag summaries are retained on failure.
This is diagnostic evidence, never a complete account inventory. The bundle lives
in extension session storage and is replaced by the next job. The latest result
receipt is kept in trusted local storage. Credentials and arbitrary exception
strings are excluded. The worker-status command reports a controlled state and
numeric close code to help distinguish network loss from policy rejection.

For a failed job, first compare server and extension operation versions, job ID,
attempt and phase. A missing phase after dispatch points to execution/transport;
a failed library/favorites/albums phase narrows the affected reader. Inspect only
reviewed sanitized evidence before creating reduced regression fixtures. Missing
network bodies are not proof of the reason a strict parser rejected a response.

## Adding the next operation

1. Define the exact input/output contract, account/ID namespaces and effects.
2. Add failing behavioral tests and reduced, reviewed fixtures. Test missing,
   malformed, wrong-account and wrong-target results and prohibited follow-up calls.
3. Add the operation/version/input/result rules to packages/google-photos/src/jobs.js
   and JOB_SPECS in photoflow_web/google_workers.py. Capabilities must agree.
4. Register a specific extension handler with DesktopWorker. Inject transport,
   report allowlisted phases, record sanitized read returns, and enforce bounds.
5. Add server validation/persistence for that result and explicit inputs before
   exposing submission. Current inventory-only enqueue input is not a generic API.
6. Extend worker-smoke.mjs with the real extension and disposable HTTPS/WSS server,
   keeping every Google request fixture-backed. Test disconnect, duplicate delivery,
   stale leases and credential revocation where relevant.
7. Qualify the operation live, read-only on the personal account. Mutation pilots
   require disposable synthetic media in an isolated account/library and separate
   qualification before registering a production mutation capability.

## Validation

The store and HTTP/WSS tests use isolated temporary libraries and fake clocks.
The worker browser fixture tests pairing through the actual UI, Chrome extension
execution, WSS dispatch, two-page inventory, progress, validated result persistence
and diagnostic download. Eight synthetic Google requests complete two jobs, with
no real Google traffic. The earlier capture/selected-read smoke remains separate.

Deployment verification on 2026-10-31: the public health endpoint returns 200,
the worker status endpoint returns 401 without a PhotoFlow session, the companion
ZIP is served byte-for-byte, and WSS upgrades through Cloudflare/nginx before
rejecting an invalid worker credential with close code 1008. No real Google account
was connected by these deployment checks. Verification also passed 91 package
tests on Linux Node 22, 65 web tests, 22 UI logic tests, both Chromium scenarios,
and a standalone packed-package import check. The desktop pairing remains the
next live user action; no cloud mutations are enabled.
