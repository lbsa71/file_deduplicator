# Selected-photo reconciliation review — 2026-10-31

Scope: read-only preparation, not retention policy qualification or cloud execution.

The local HTTPS app captured one new `photo-details` read for the previously
imported standalone image. It saved an account/library-bound review, dated remote
observation and local SHA-256/sidecar revision. The report showed one observation
captured, one local original verified and eight remaining evidence checks. No
additional original was downloaded and no Google mutation was requested.

After browser reload, the workbench restored the saved review. Refreshing local
verification updated its local-check timestamp while preserving the original
remote-read timestamp and without enqueueing another Google job. Private runtime
files and identifiers remain outside committed fixtures.

Verification: 121 backend tests and 24 UI tests pass. The synthetic extension E2E
passes under both fixture and selected-target policies: 31 completed jobs over 23
operation types, including review capture, reload/reopen and local refresh. Google
requests are intercepted and no real Google mutation is made by these tests.

Behavioral coverage includes finite targets, wrong namespace/account/owner, CSRF
and roles, interrupted setup without duplicate reads, restart, worker-database
loss, partial failures, unknown favorite/albums, stale observations, local byte
changes, hash budgets and changed sidecar revisions before report publication.

Remaining gates include complete account enumeration, curated-album intent,
current remote byte equality, account-bound Takeout metadata, independent backup,
companion preservation and remote ownership/sharing. Reports always retain
`retentionReady: false` and `collectionComplete: false`. Fresh remote reads require
a new review; local refresh does not make old remote evidence fresh.
