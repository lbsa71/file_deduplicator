# Selected album/photo inspection tooling — 2026-10-31

Starting main: c71fddb73816fae0ce26c3f24ee063c9ba0d9911.
The previous live count qualification remains valid for its documented scope.
This change provides the next probe; no new live Google calls were performed.

The built popup now accepts an expected account, one album URL and one library
photo URL. Its background handler checks the actual page account before photo
requests. The bounded probe reads album membership, basic photo details and
extended photo details, checking that both detail methods agree on dedup identity.
It reports matching dedup-key counts separately from matching media-key counts,
without asserting that namespaces are interchangeable. No retention decision can
use this probe: every summary includes retentionReady=false.

Limits: two album pages, 500 accepted members, four requests, 4 MiB sanitized
returned evidence, plus existing transport/body limits. No automatic retry.
Rejected input sends no photo requests. Wrong accounts, pagination overflow and
conflicting detail identities stop dependent reads. Popup waiting is bounded by
120 seconds; timeout does not cancel a read already submitted to Chrome.

Returned evidence is available through Download capture under readInspection.
One sanitizer instance preserves aliases across this inspection's requests and
responses. Account and input URLs are not stored in popup preferences. Sanitized
evidence remains in extension session storage until replaced/session termination;
raw results are not exported. Evidence completeness is independent of successful
read completion and remains false if a body is omitted or cannot be sanitized.

Verification: failing tests preceded implementation. All 86 package tests pass
on Linux Node 22.23.4. Actual Chromium 156.0.8078.4 extension test passes: the real
popup performs three fixture-backed selected reads, reports one matching dedup
key with a different album media key, and exports sanitized results. Nine total
synthetic requests occur, including the six existing smoke-test interactions;
no recorder request replay or real Google traffic occurs. Existing timeout,
source-installation rejection, capture download and limit checks also pass.

## Next live action

1. Pull main in the Windows worktree and run npm run build:capture from the package.
2. Manually reload the existing unpacked extension, retaining its current permissions.
3. In Google Photos, run Check connection and copy its account value into Expected
   Google account. Paste a deliberately selected album URL and a library photo URL.
   A Takeout-preserved photo URL is useful for testing source-to-browser identity.
4. Click Inspect selected album and photo once. Choose a small album (at most
   500 members, preferably fitting one page). Shared/album-scoped photo URLs are
   rejected; use the standalone library photo URL.
5. Download capture and review readInspection. Record successful contracts or
   sanitized failure evidence; report identifier correspondence without guessing.

Personal account remains read-only. Live details/membership/Takeout URL mapping
are still pending. Browser writes, image upload qualification and WSS job delivery
are separate remaining work. No user photo, album or favorite state was changed.
