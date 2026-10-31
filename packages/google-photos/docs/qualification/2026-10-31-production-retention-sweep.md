# Production retention sweep preparation — 2026-10-31

The owner requested keeping every starred Google item, every member of any Google
album, and every item without a verified local original. The owner explicitly
asserted an existing Takeout backup and waived verification of that backup.
[ADR 0009](../../../../apps/web/spec/adr/0009-owner-approved-google-retention-sweep.md)
records that policy. Backup evidence is not falsely upgraded to verified.

## Inventory contract fix

The page-111 validation failure was traced to a colon-containing dedup key.
Companion and server now use a distinct bounded dedup-key contract: nonempty
letter/digit/underscore/hyphen segments separated by colons, up to 256 characters.
Media identifiers and photo URL rules are unchanged. Empty segments, percent
encoding, punctuation, whitespace, controls and oversized values remain rejected.
Account-bound local associations use the same contract; differing identities
remain distinct and cannot silently match.

## Policy and deployed state

Read-only manifests include the keep rules, policy version, owner-asserted Takeout
backup requirement and `backupVerified: false` within the reviewed canonical hash.
Remote-only items are explicitly kept, with no automatic download-then-Trash.
Candidate references remain blocked pending current content and identity evidence.
The backup waiver removes only the backup-verification gate.

Server code through `f46c647` was installed on the existing production host.
The existing companion installation was rebuilt/reloaded without clearing pairing
or journals. The served 0.4.0 ZIP was replaced with the matching build and inspected
to confirm both the dedup contract and owner-approved policy. Production health
returned HTTP 200 after the normal catalog rebuild. The restart invalidated the
web login; a fresh sign-in was requested before browser qualification resumes.

Tests: 141 package tests and 133 backend tests pass. The selected-policy synthetic
extension run completed 36 jobs, with immutable download, idempotent commit,
original import/deduplication and unknown-write reconciliation without replay;
all 141 Google requests were synthetic.

After sign-in, the narrow retry of the formerly rejected page succeeded with 50
returned items through both deployed contracts. One replacement whole-account
read-only preparation was started. It saved 57 complete library pages before the
session-fix restart and continued to 62 afterward without starting another full
preparation. This proves continuation, not full inventory completeness.

## Web session restart fix

The application previously kept web sessions only in a process-local dictionary.
Every deployment restart therefore invalidated them regardless of activity.
`d3a23c0` replaces that with private SQLite state containing hashed bearer-token
keys, account/CSRF/session timestamps, and no passwords or raw session tokens.
The original 30-minute idle and 12-hour maximum limits remain unchanged. Each
process revalidates persisted accounts before accepting a session, and roles
continue to be checked dynamically. Logout revocation is durable; an in-flight
request cannot recreate a revoked session.

All 138 backend tests pass, including restart/CSRF preservation, account revocation,
both expiry limits, private permissions, credential exclusion and concurrent
revocation behavior. Production was updated, returned health HTTP 200, and created
its session directory/database with permissions 0700/0600. The first cutover cannot
recover old RAM-only sessions, so one final sign-in was requested. Preservation of
a real owner's session over a subsequent production restart remains to be observed;
the restart tests used synthetic accounts.

## Whole-account inventory and recovery qualified

The replacement read-only preparation completed the library, favorites, album
list and every album's member pages. It enumerated 11,443 Google items, 277
favorites and 16 albums, against 24,272 active local records (including duplicate
review records). Its immutable private manifest's canonical SHA-256 was checked
independently and matched the app's review screen.

The snapshot classified 3,109 remote items as keep and 8,334 as blocked
review-trash candidates. All 100 remote items without a local candidate were kept.
A candidate reference is not verified availability or removal permission. The
7,307 local publication candidates also remain held. The complete manifest has
only one executable quota read; it has no Trash or upload operation.

Enumeration stopped on the deliberately empty private test album. Its Google UI
showed “No items,” while `snAcKc` returned null items, an explicit empty cursor,
the exact album identity and an observed `[0,0]` context sentinel. The qualified
parser accepts only this bounded empty form. Missing/changed context, nonterminal
cursors, nonzero sentinels and wrong identities remain errors. A fresh live read
then succeeded with zero items.

The same stopped preparation was explicitly resumed using `59c4548`: completed
pages were reused, only its unfinished read received a new attempt-scoped worker
request, and old failed jobs remained intact. The manifest records that successful
request's actual key. Commit keys and mutation replay rules are unchanged.

The worker now prunes only old server-acknowledged delivery history while keeping
recent duplicates and every unacknowledged result. A 250-job regression proves
bounded history and no replay of recent deliveries. Durable mutation journals are
independent of this cache. This removes the former 100-job interruption during
long inventories.

All 143 package tests and 140 backend tests pass. The final synthetic extension
run completed 36 jobs with 141 fixture Google requests and no real Google traffic.
After the deployment restart, the real owner's login was still valid; native
Chrome and a refreshed tab binding confirmed access without another sign-in.

A five-photo preservation/verification manifest used only items with existing
local candidates. Its first direct-original transfer stopped with a controlled
HTTP failure (`DOWNLOAD_TRANSPORT` in server diagnostics); the other four were
not dispatched. The owner then clarified that periodic manual Takeouts are the
download workflow and requested no further focus on automatic downloads. No
replacement download or Google mutation was queued.

Recovery receipts were tightened in `cc47c12`: they require an account-, media-,
dedup-revision- and hash-matching local association. Changed Google observations
are preserved as distinct provenance rather than silently conflated. Transport
failures now report only allowlisted exception classes, without signed URLs.
All 143 backend tests pass; the synthetic extension check still completed its
36 jobs. The deployed service is healthy. Direct-original transport remains
unqualified on this host and is not a prerequisite for the manual Takeout workflow.

## Read-only local Takeout audit

A separate filesystem audit checked all 8,334 blocked candidates against the
completed manifest's frozen local record revisions. It changed no original or
sidecar and made no Google requests. For each unambiguous candidate it checked
the current filesystem fingerprint, sidecar SHA-256/revision, full original-byte
SHA-256, exact embedded Google photo URL, matching Takeout title/original filename,
and the preserved Takeout document's raw hash/content. Local files and sidecars
were rechecked around the read. Conflicting candidate hashes remained ambiguous.

Results: 8,333 candidates have verified unchanged local bytes and matching
preserved Takeout documents; one has ambiguous local content and remains kept.
The verified group includes 649 known motion-photo items whose companions still
need separate proof. The remaining 7,684 have no positive motion flag; that does
not itself prove companion absence. All 100 remote items without local candidates
remain kept by the full manifest.

The private audit explicitly says `remoteBytesCompared: false` and
`authorizesTrash: false`. It proves local Takeout evidence, not current Google
byte equality, companion completeness, ownership or production execution authority.
The failed optional download batch has not upgraded any retention fact.

## Owner-authorized executable sweep

The owner subsequently instructed that the policy be changed and the actual
Trash sweep run. ADR 0009 now accepts current local SHA-256 plus preserved exact
Takeout URL/title provenance as the local-original evidence. It does not require
fresh Google downloads or independent backup verification. Items without positive
motion markers are eligible under this explicit policy; missing markers are not
reported as verified companion absence. The 649 positive motion items and the
ambiguous local match remain retained.

The implementation derives a separate immutable executable manifest from the
completed account inventory. It issues exact account/target/local-hash/manifest
capabilities distinct from disposable pilot scopes. Current local evidence is
reverified at browser dispatch; fresh star and album state is checked by the
extension before each write. Newly protected photos receive kept receipts. A
single write is journaled before sending and positive exact Trash membership is
required before continuing. Unknown outcomes stop the plan; read-only recovery
can resolve positive Trash evidence without replaying the write. There is no
permanent-delete capability, upload or automatic download in this scope.

The implementation is covered by local-evidence, authority-binding, protection,
identity, unknown-outcome, reconciliation and durable-history regression tests.
Real execution receipts and private target lists remain outside Git. Production
execution results will be recorded separately after deployment.

Validation for the executable path: 153 backend tests, 156 package tests and 24 UI
unit tests pass. The selected-account synthetic HTTPS/WSS extension test completed
40 jobs and 151 fixture Google requests, including full inventory, preserved
Takeout preparation, hash-bound commit and verified production-scope Trash. It
made no real Google requests. Contract synchronization and production builds pass.
