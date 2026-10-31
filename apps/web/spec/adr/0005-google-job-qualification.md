# ADR 0005: Typed Google jobs and isolated mutation qualification

Status: Accepted — 2026-10-31. Supersedes the inventory-only contract in ADR 0004.

[ADR 0006](0006-account-authorized-google-pilots.md) supersedes this ADR's
isolated-account-only requirement. The fixture policy below remains the default;
explicitly owner-authorized personal-account pilots may use selected targets.

## Decision

Implement the operations needed for reconciliation as explicit library handlers,
not a generic RPC executor. Reuse request layouts reviewed from Google Photos
Toolkit 3.3.0, commit `6db9ab355e4797327e4078cf87a2b6994d36cf73`.
Keep the existing production retention executor's qualification gates separate.
Passing a synthetic test does not qualify an undocumented Google operation live.

Protocol 2 pairs the server with extension 0.3.0. The serializable catalogue in
`packages/google-photos/src/job-catalog.js` defines operation/version, effect and
field metadata. `tools/sync-job-contracts.mjs` generates the packaged Python
catalogue; `npm run check:contracts` detects drift. Both runtimes validate input
and results independently. No arbitrary code, RPC name or endpoint is accepted.

| Read job | Purpose |
| --- | --- |
| inventory-counts | Complete library/favorite/album counts, never retention evidence |
| library-page, favorites-page, albums-page, trash-page | Bounded page with explicit continuation |
| album-members | Bounded album-scoped identities and continuation |
| photo-details | Inspect the library item referenced by a Takeout photo URL |
| storage-quota | Inspect validated storage totals |
| hash-candidates | Candidate lookup using opaque Google hashes; absence remains unproven |
| download-link | Verify availability of an original download reference; no byte transfer |
| reconcile-write | Read back an earlier journaled write; never replay it |

A terminal page is complete for that page request, not proof of a complete account
inventory. Full readers retain cursor-loop detection and limits. Album-scoped
media keys are distinct from library media keys. Album removal uses the observed
album-scoped key, never a guessed correspondence.

Pilot write jobs are favorite-set, archive-set, trash, restore, album-create,
album-add, album-remove, description-set, timestamp-set, location-set and
location-clear. There is no permanent-delete job. Image upload needs a separately
qualified transfer adapter; Toolkit supplies no upload contract for this release.
Video upload and Takeout automation remain outside scope. Download-link currently
returns availability, not a signed URL or a downloaded local original.

## What an isolated test account means

It is a real, separate Google account whose Photos library contains only disposable
synthetic fixtures. PhotoFlow does not create a Google account or infer that an
account is disposable. An operator signs into it on the desktop, pairs it normally,
and explicitly configures its exact observed account identifier on Ubuntu:

```ini
# sudo systemctl edit photoflow-web
[Service]
Environment="PHOTOFLOW_GOOGLE_TEST_ACCOUNT=<identifier shown by extension Check connection>"
```

Restart the service after changing that setting. Leaving it unset disables all
pilot writes. It must never contain the family account's identifier. It does not
contain Google credentials. Credentials and Google session values stay in Chrome.
The server checks its configured account against the paired account; the UI's
confirmation checkbox alone cannot enable writes.

This follows CONTRIBUTING.md's requirement for isolated mutation tests. These
undocumented APIs may change, and even a reversible write can affect the wrong
item if its protocol is misunderstood. A dedicated account contains that risk.
Normal PhotoFlow use does not require a second account; this is a qualification
phase before separately enabling production operations.

Use a small synthetic image named `photoflow-test-fixture.jpg` (or another supported
image extension), at most 10 MiB, and a private album whose title begins
`PhotoFlow test `. Obtain their actual photo URL and album ID using read jobs.
The filename/prefix checks are additional guards, not proof of a disposable account.

## Finite suites and recovery

The administrator workbench prepares a reviewable finite JSON suite before queueing.
A suite contains at most 32 jobs. The default read suite can run on the personal
account. The write suite requires the explicit isolated-account confirmation.
It exercises reversible state transitions on the selected fixture. It also creates
an empty test album and changes the fixture's timestamp; it does not restore every
original metadata value or automatically remove test albums. Optional location
inputs use latitude/longitude integers in E7 units and an explicitly supplied
Google place identifier. Do not invent identifiers for live tests.

Ubuntu journals every job and issues a short-lived scope bound to account, job,
operation and target. The extension validates this again before sending. It
persists a checksummed intent before a write, verifies the returned envelope and
then verifies the remote postcondition. A browser restart cannot silently steal
an interrupted writer lock. One account has one writer; unknown writes block
subsequent writes across suites and re-pairing. Independent reads may continue.

Connection loss, timeout, missing acknowledgement or failed postcondition after
sending means unknown outcome, never automatic retry. Reconcile-write can resolve
only an existing intent whose desired state is proven by reads. An uncertain album
creation without a returned ID remains unresolved; matching a title is insufficient.
Local journal loss requires inspection, not an optimistic retry. Browser journal
receipts and server queue state should be retained through qualification.

## Troubleshooting

Every job type reports bounded phases, controlled errors and sanitized RPC evidence.
Transport guard failures include a fixed rule code, not raw credentials or inputs.
The server diagnostic export contains summaries; the authenticated owner-only result
endpoint contains the selected operation's actual IDs/metadata for inspection.
Those private results must not be committed as public fixtures.

Compare job ID, attempt, version and phase across server and extension diagnostics.
Reduce a failed response to a reviewed fixture, write a failing test and correct the
adapter. Never relax a guard merely to make a live request succeed. The worker's
HTTPS/WSS browser test intercepts every Google request and exercises all registered
operations, including lost acknowledgements and read-only reconciliation. Live
qualification remains a separate, explicit activity.
