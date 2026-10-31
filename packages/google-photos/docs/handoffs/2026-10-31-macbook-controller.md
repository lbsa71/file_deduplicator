# PhotoFlow handoff: MacBook browser controller

Continue as the primary session. Stefan is moving work off the Ubuntu session to
`MACBOOK PhotoFlow Browser Controller`, thread
`01a19114-075a-7122-adde-e89be4ada1d8`. Direct cross-host thread reads and messages
failed with `thread not loaded`; no coordination message was delivered. Use this
repository and the user for handoffs rather than assuming cross-session messaging.

## Objective and authorization

Finish live qualification of the typed Google Photos desktop worker against the
deployed PhotoFlow server. Pair/connect the actual local extension, exercise reads,
then methodically qualify finite mutation pilots and fix observed incompatibilities
with failing regression tests. Keep the standalone library extractable from the
monorepo. Commit and push findings/code to main, preserving unrelated work.

Stefan explicitly authorized controlled pilots on his personal Google account,
reporting a recent full Takeout backup. A separate Google test account is OPTIONAL.
This supersedes the earlier isolated-account-only requirement. Do not ask for that
authorization again. Backups are not proof that protocol calls are correct or a
transactional rollback of sharing, album, metadata or account state. Potential
throttling/sign-in challenges and undocumented API changes were discussed.

Keep exact account/target binding, strict schemas, bounded reads, durable intents,
postcondition checks, and unknown-outcome stops. No permanent deletion or automatic
library-wide retention cleanup. An uncertain write must be reconciled by reads,
never blindly retried. Google login/session values remain in the desktop browser;
Ubuntu receives a separate PhotoFlow worker credential, not Google cookies.

## Verified state at handoff (2026-10-31)

- Repository: https://github.com/lbsa71/file_deduplicator, branch main.
- Implementation deployed/pushed: `0ae994ef015f2be02ba7b9b358b8edd14264533f`.
  Later commits may contain this handoff or other work: fetch and inspect main.
- Public app: https://photos.lbsa71.net ; public `/healthz` returned 200.
- Companion: https://photos.lbsa71.net/tools/google-photos-worker-0.3.1.zip .
  Use 0.3.1, job protocol 2. Version 0.3.0 lacks selected-personal-target support.
- Latest read-only server check found ONE paired worker, ZERO queued/running jobs,
  and ZERO unknown jobs. Earlier messages saying no account was paired are stale.
  Check current UI/worker status before re-pairing or revoking anything.
- No pilot account is configured in the systemd environment. Reads can run after
  pairing; writes remain gated until that exact account is allowlisted below.
- This Ubuntu session executed NO real Google mutations. Its browser tests
  intercepted all Google requests with synthetic responses. Do not report these
  as live Google qualification.
- Earlier live browser work qualified complete inventory/favorites/album-list
  enumeration: 11,431 photos, 277 favorites, 15 albums. Those are historical counts,
  not a retention-ready inventory. Other operations still need live qualification.

## Read first

1. `CONTRIBUTING.md` (strict TDD and fail-closed boundaries).
2. `apps/web/spec/adr/0006-account-authorized-google-pilots.md` (current authority,
   configuration, target policies and suite side effects).
3. `apps/web/spec/adr/0005-google-job-qualification.md` (job catalogue and recovery;
   its isolated-only requirement is superseded by ADR 0006).
4. `apps/web/spec/adr/0004-desktop-google-worker.md` (connection/investigation
   architecture; its original inventory-only protocol is superseded).
5. `packages/google-photos/docs/qualification/2026-10-31-job-suite.md` and the
   live-read-success/framing-correction/selected-inspection notes beside it.
6. `packages/google-photos/test/fixtures/live/README.md` before handling live evidence.

## Browser and connection procedure

Preserve the MacBook checkout and any uncommitted work. Fetch main and fast-forward
or use an isolated checkout as appropriate. Do not reset or overwrite another
session's work. Install the served ZIP, or build with
`npm ci && npm run build:capture` inside `packages/google-photos`.

Only `packages/google-photos/dist/capture-extension/` is installable from source.
The neighboring `capture-extension/` contains source templates and lacks required
runtime imports. For the ZIP, load the extracted folder containing `manifest.json`.
Rebuilding does not reload an installed extension. Chrome extension management may
block automation; if necessary ask Stefan only for the manual Load unpacked/Reload
click. Permissions are unchanged from 0.2. Do not leave duplicate older copies active.

Open the existing signed-in Google Photos tab and extension popup; use Check
connection to obtain its exact observed account identifier. Do not infer it from
the email or Linux username. In PhotoFlow's administrator Google connection panel,
check whether the existing pairing is already this browser/account. Reuse it if
working. Otherwise generate a short-lived pairing code and paste it into the
extension's Pair with PhotoFlow field while the Google tab is selected. Pairing
queues an initial read-only inventory job. The extension opens outbound WSS to
`wss://photos.lbsa71.net/api/v1/google/worker`; no inbound desktop access is needed.

## Enabling the already-authorized personal pilot on Ubuntu

Use the existing approved SSH connection if available. The previous session's
filesystem path does not imply the Mac session can access that host. If SSH is
unavailable, report this exact remaining configuration step; do not weaken the
account guard or upload Google credentials to bypass it.

On Ubuntu, configure a systemd drop-in for `photoflow-web` with the exact paired
account identifier (keep actual account identifiers out of Git):

```ini
[Service]
Environment="PHOTOFLOW_GOOGLE_PILOT_ACCOUNT=<exact paired account identifier>"
Environment="PHOTOFLOW_GOOGLE_PILOT_TARGET_POLICY=selected"
```

Reload systemd and restart the service after checking for active jobs. Preserve
existing unit/drop-in settings. Default policy is `fixtures`; the legacy
`PHOTOFLOW_GOOGLE_TEST_ACCOUNT` remains an alias, with the new setting taking
precedence. No configured account means no writes. A configuration change cannot
broaden old queued intents; policy is snapshotted per job. The UI must report the
selected-target policy and enabled pilot operations for the matching account.

## Live test sequence

1. Confirm connection and count enumeration first. Then use the operation workbench
   for a finite read suite on a selected photo URL and private album ID. Preserve
   raw Takeout URLs already available in managed sidecars under
   `sources[].documents[].document.url`; verify identity correspondence rather than
   guessing Google ID namespaces. A terminal page is not a complete account scan.
2. Prefer an expendable image in the personal account and a private pilot album.
   A synthetic image in this same account is fine; a separate account is not
   required. Record before-state if using an existing valuable photo. Never infer
   which existing photo to mutate solely from a filename/hash candidate.
3. Qualify one write and its read-back first (for example favorite-set); deliberately
   restore its prior value with a separate verified job when appropriate. Then
   expand to other operation types or the finite prepared suite. Every write still
   requires explicit submission confirmation in the UI, within the user's existing
   authorization. Do not turn pilot authorization into unattended retention cleanup.
4. Review the complete prepared suite before dispatch. It ends with favorite/archive
   OFF, description CLEARED, membership REMOVED from the selected album, and the
   image restored from Trash. It does NOT restore every original value. Optional
   timestamp changes persist; optional location tests clear manual location. Newly
   created test albums remain. Optional metadata input defaults to `{}`.
5. On failure, correlate job ID/attempt/version/phase across PhotoFlow's Download job
   diagnostics and the extension's Download worker diagnostics. View private job
   results only in the authenticated UI. Reduce sanitized evidence into a reviewed
   regression fixture, add a failing test, fix the adapter, and requalify the read
   before dependent writes. Never loosen validation to obtain apparent success.
6. Unknown outcomes block further writes account-wide, including after re-pairing.
   Use `reconcile-write` with the original job ID. Preserve the extension's local
   journal; clearing storage or re-pairing does not prove a write did not happen.
   An uncertain album creation without a returned ID cannot be resolved just by title.

## Operations and limits

22 typed job types are implemented in `src/job-catalog.js` and mirrored into Python:

- Reads: inventory-counts, library-page, favorites-page, albums-page, album-members,
  photo-details, trash-page, storage-quota, hash-candidates, download-link,
  reconcile-write.
- Pilot writes: favorite-set, archive-set, trash, restore, album-create, album-add,
  album-remove, description-set, timestamp-set, location-set, location-clear.

Selected policy permits ordinary image filenames and sizes and explicitly selected
PRIVATE albums. Shared-album membership remains excluded. Newly created albums must
still start `PhotoFlow test `. No video uploads or Takeout automation are required.
`download-link` verifies availability only: it does not transfer bytes. Image-upload
jobs and binary download transfers are NOT implemented. They require separate
adapters and qualification. Counts and opaque hash candidates cannot authorize
retention/removal. Production retention mutation gates remain separate.

Toolkit reference is pinned to 3.3.0, commit
`6db9ab355e4797327e4078cf87a2b6994d36cf73`; retain upstream MIT attribution.

## Code and verification

Library: `packages/google-photos/src/{job-catalog,jobs,client,protocol,browser,
toolkit-pilot,browser-journal,google-job-handlers,worker,job-diagnostics}.js`.
Extension wiring: `capture-extension/{background,desktop}.js`.
Server: `apps/web/photoflow_web/{google_workers,google_contracts}.py`.
UI: `apps/web/ui/src/{google,google-job-console}.jsx` and `google-jobs.js`.

Last implementation checks: 120 package tests, 76 web tests, 24 UI tests passed.
Actual Chromium extension + local HTTPS/WSS tests passed under BOTH policies:
28 jobs / 22 operation types / 122 intercepted requests each, including a lost
acknowledgement reconciled without replay. These are synthetic, not live results.

```sh
node --test packages/google-photos/test/*.test.js
npm run check:contracts --prefix packages/google-photos
npm test --prefix apps/web/ui
PYTHONPATH=apps/web:apps/photoflow python -m unittest discover -s apps/web/tests
npm run build:capture --prefix packages/google-photos
npm run build --prefix apps/web/ui -- --outDir ../photoflow_web/static --emptyOutDir
PHOTOFLOW_TEST_PYTHON=/path/to/web-venv/bin/python npm run test:worker --prefix packages/google-photos
PHOTOFLOW_TEST_PILOT_POLICY=selected PHOTOFLOW_TEST_PYTHON=/path/to/web-venv/bin/python npm run test:worker --prefix packages/google-photos
```

Use Node 22 for Playwright tooling (Node 20+ required), Chromium and OpenSSL. The two
worker browser tests share loopback port 8099 and must run sequentially. Most core
package tests also run on Node 18. Inject environment boundaries; don't use real
Google traffic in automated regression tests. Contract metadata is generated with
`tools/sync-job-contracts.mjs`; keep Python/JS validation and capabilities consistent.

Chrome injection can omit null object properties: `background.js` passes a JSON
string to the self-contained page handler to preserve exact null bindings. Keep
this fix. Browser journals use canonical key ordering and SHA-256 checksums; don't
remove checks to accommodate corrupt state. Google's observed RPC framing uses
UTF-16 length plus two and strictly validated trailing `e` records. Read the framing
qualification note before changing the parser.

## Ubuntu operations and reporting

Checkout: `/home/stefan/file_deduplicator`. App service: `photoflow-web`; installed
venv `/opt/photoflow-web-venv`; state `/var/lib/photoflow-web`; Google queue
`google-workers/workers.sqlite` under that state. Preserve this private queue state
and browser journal. Photo library: `/mnt/usb/PhotoLibrary`; don't use it as a test
fixture. Ubuntu has working authenticated `gh`/Git and passwordless sudo. Browser
session access and SSH from the Mac must be checked separately, not assumed.

Deploy reviewed server changes using the existing package/service setup. The app
binds 127.0.0.1:8090 behind nginx/cloudflared. Restart startup rebuilds the library
index and may produce roughly a minute of 502s. Wait for public health 200 before
claiming deployment success. Extension ZIPs are installed beneath the installed
package's `static/tools/`; source `dist` and built static assets are ignored build
outputs. Rebuild/release and manually reload the desktop extension for client fixes.

Record each operation as passed, failed, blocked, or unknown, with controlled error
codes and remaining limits. Commit only reviewed sanitized evidence, code, tests
and documentation. Never commit credentials, real media IDs/URLs, account identifiers,
private captures/HARs or personal screenshots. Push commits to main. Report the
commit, local extension version, server state and next concrete qualification step.
