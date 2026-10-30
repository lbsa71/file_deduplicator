# Browser qualification, 2026-10-30

Authenticated Google Photos UI access was confirmed after the operator completed
browser setup. The library was visible in both the in-app browser and native
Chrome; the in-app Favorites view also opened. Live protocol qualification
remains blocked: no authenticated RPC bodies were captured and no live mutation
was attempted. Computer Use stopped before capture-extension installation because
it could not verify the current Windows browser URL with enough confidence.
The actual capture extension was verified against synthetic browser traffic.

## Starting point and scope

- Starting `origin/main`: `475854c1b420f597a4f779ce09d72451dfc9958d`.
- Isolated branch: `codex/google-photos-browser-qualification`, created in a
  separate worktree after fetching origin. Existing checkout contents were kept.
- Read `CONTRIBUTING.md`, the package README and implementation, and ADR 0003.
- The package still has no runtime dependencies or PhotoFlow application imports.
  Browser mutations remain refused by the supplied transport. No qualification
  assertion, account credential, or production mutation capability was added.

## Browser capabilities actually checked

| Browser or surface                            | Observation                                                                                                                                                                                                                                                                                | Capture capability established                                                                                                                                                                                                                                                                                                            |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Codex in-app browser                          | Initially reached Google sign-in. After operator setup, the signed-in library and Favorites view opened for the existing personal account, aliased here as `personal-account-A`. No password or MFA was entered by the agent. The browser version was not exposed by the advertised tools. | Navigation, accessibility inspection and screenshots are available. Advertised browser capabilities were visibility and viewport; tab capabilities were page assets and WebMCP. No request/response-body, CDP, extension-loading or HAR-export capability was advertised. UI access did not establish network capture.                    |
| Installed Chrome `156.0.8078.74`              | Opened the existing personal profile after the operator cleared an unexpected Windows passkey permission prompt. Google Photos showed the same signed-in personal account and library.                                                                                                     | Authenticated UI access was confirmed. Before extension installation, an attempt to open a new Chrome tab was stopped by Computer Use because the current browser URL could not be verified sufficiently. No extension was installed and no live traffic was captured. Loading this extension in the personal profile remains unverified. |
| Installed Edge `156.0.4314.50`                | Executable version inspected; not launched.                                                                                                                                                                                                                                                | Not tested. No inference about its sign-in state or capture capability.                                                                                                                                                                                                                                                                   |
| Playwright Chromium `156.0.8078.4` on Windows | Loaded the repository-built unpacked extension in a fresh disposable profile. All fixture-page traffic was intercepted locally.                                                                                                                                                            | Actual extension debugger attachment, passive request/response recording, read-client evaluation, popup download and filesystem access were verified with synthetic data. This is not live Google qualification.                                                                                                                          |

After the synthetic test browser had closed, the running Chrome processes
advertised neither `--remote-debugging-port` nor `--remote-debugging-pipe`.
No existing loopback CDP endpoint was discovered or connected to. No debugging
port was enabled or exposed. This check does not prove that every possible
debugging connection is absent.

No supported way was found to run the package's network evaluator through the
in-app browser's documented read-only page evaluator. The successful synthetic extension test
does establish that `chrome.scripting` can run the package evaluator in that
isolated test browser. These are different capabilities.

The actual popup produced a JSON download, which the test saved to its disposable
profile directory and read back from the filesystem. Its contents matched the
extension export. Test profiles and downloads were removed by the existing test
cleanup; no user browser profile was copied, exported or deleted.

## Operations and protocol evidence

The signed-in account is referred to only as `personal-account-A`. No protocol
account identity was obtained from the package evaluator. Item links were visible
in the UI, but their values, account email and personal metadata were not exported
into this report or fixtures. No identifier correspondence was established.
Existing fixture identities and synthetic `PRIVATE_*` markers represent generated
test data. No new file was added under `test/fixtures/live/`: synthetic observations
must not be presented as live fixtures.

The following RPC names and structures come from the implementation and its
existing synthetic/pinned upstream fixtures, not authenticated browser evidence.
The source transport uses POST to `[/u/<index>]/_/PhotosUi/data/batchexecute`,
with the `rpcids` query parameter and an `f.req` form envelope carrying serialized
RPC arguments. Its session/account checks run inside the authenticated page;
this session did not exercise them against Google.

| Interaction                        | Source/fixture contract                                                                            | What was verified this session                                                                                                                                                                                                                                                                             |
| ---------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Library listing and pagination     | `inventory()`, `lcxiM`; validated row array and continuation token; includes archive.              | Actual extension read action accepted a synthetic single terminal page. Unit tests accepted multi-page enumeration and rejected a failed later page, repeated cursor, duplicate identity and incomplete structure. The live library screen opened, but no live pagination or completeness was established. |
| Favorites                          | `favorites()`, `EzkLib`; same bounded traversal contract.                                          | Actual extension parsed one synthetic favorite. Missing favorite flags remain unknown in unit fixtures; the live Favorites view opened, but no count or live flag semantics was qualified.                                                                                                                 |
| Album listing                      | `albums()`, `Z5xsfc`; album namespace, ID, title, nonnegative count and known/unknown shared flag. | Actual extension parsed one synthetic album. No live albums were read or changed.                                                                                                                                                                                                                          |
| Album membership                   | `albumItems()`, `snAcKc`; album-item namespace and matching album context.                         | Existing unit/upstream fixtures passed; wrong album identity is rejected. No live member enumeration or library-ID correspondence established.                                                                                                                                                             |
| Individual photo details           | `item()`, `VrseUb`; `details()`, `fDcn4b`; exact target identity required.                         | Synthetic `VrseUb` traffic was recorded; existing parser fixtures for both detail shapes passed. Missing membership remains unknown. No live photo was opened.                                                                                                                                             |
| Trash state                        | `trash()`, `zy0IHe`; optional trash timestamp remains unknown when absent.                         | Existing parser fixture passed. No live trash listing or state interpretation qualified.                                                                                                                                                                                                                   |
| Favorite, trash and restore writes | `Ftfh0` and `XwAOJf` source templates, guarded executor and durable intent.                        | Existing failure/recovery tests passed on Linux. No live mutation or automated browser write transport qualified.                                                                                                                                                                                          |
| Album add/remove                   | Not implemented by this package.                                                                   | No capture; exact request, response and postcondition contracts still needed.                                                                                                                                                                                                                              |
| Upload and ID mapping              | Official API uploader has separate synthetic tests; browser uploader is unimplemented.             | No live upload, upload-session sequence, token/media mapping or read-back evidence. The smoke test's `/upload` route is an artificial fixture, not an observed Google browser-upload endpoint.                                                                                                             |
| Hash candidates                    | `swbisb`; opaque values, candidate matches, `absenceProven: false`.                                | Existing unit coverage passed. No hash algorithm, SHA-256 relationship, lookup coverage or no-match semantics qualified live.                                                                                                                                                                              |

The source parser accepts null, empty or omitted trailing cursors as terminal
only after validating the row array. Favorite/shared flags and missing album
membership stay unknown. These are the current fixture contracts; their present
live Google behavior still requires capture. A first page, a UI count, or the
extension's inventory counts cannot establish a retention-ready inventory.

## Verified problems and focused corrections

### Omitted bodies could be labeled complete

Before the fix, seven synthetic cases could finish with `complete: true` despite
missing protocol evidence:

- Structured response exceeds the encoded 1 MiB threshold.
- Retrieved structured response exceeds the sanitizer's decoded size threshold.
- A structured body is returned base64-encoded and deliberately not decoded.
- The debugger result contains no structured text body.
- RPC request body is missing, oversized, or malformed.

Failing behavioral subtests were added first and reproduced each case. The
recorder now marks these captures incomplete and records a generic `captureError`
on the affected request or response. It still does not retrieve oversized
encoded bodies, replay requests, expose raw omitted bodies, or decode binary
uploads. Existing size/entry/export limits were retained.

An actual-extension probe supplied an oversized synthetic JSON RPC response.
One request was made, one incomplete entry was exported, its response body was
omitted with a capture error, and no request was replayed.

### Extension smoke test could stop before capture caught up

The baseline smoke test failed with four captured entries instead of five, then
passed on rerun. Further runs reproduced early stop with three entries. Its
`waitForFunction` predicate was asynchronous; the installed Playwright polling
implementation treated the returned Promise as truthy before the status value
was checked, so the asynchronous false result did not keep polling.

The smoke test now awaits each status request in Node and checks the resulting
count within a ten-second deadline. It also tests the actual popup download and
the oversized-response case. This changes test synchronization, not traffic
retries. The final runs passed on both Node 24 and Node 22 on Windows.
See [Playwright's waitForFunction reference](https://playwright.dev/docs/api/class-page#page-wait-for-function)
for the truthy-predicate contract; the installed implementation was also inspected.

## Commands and results

Commands below are relative to the worktree root unless noted. Node 22.23.4 was
installed in tool caches, leaving package dependencies unchanged. The Linux
archive was checked against the SHA-256 in Node's official release manifest.

| Command/check                                                                                                  | Result                                                                                                                                                                                                                              |
| -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `git fetch origin`, isolated `git worktree add ... -b codex/google-photos-browser-qualification origin/main`   | Started from the commit above.                                                                                                                                                                                                      |
| `npm ci --prefix packages/google-photos`                                                                       | Passed; two development packages installed, zero audit vulnerabilities reported.                                                                                                                                                    |
| Baseline `npm test --prefix packages/google-photos`, Windows Node 24.14.1                                      | 52 tests: 50 passed, two failed at `FileJournal.lock()` with `Journal directory must be private`.                                                                                                                                   |
| `node --test packages/google-photos/test/capture.test.js` before the implementation fix                        | Seven new failing scenarios reproduced; 9 failures including the two containing tests, 8 passes.                                                                                                                                    |
| Same focused capture test after the fix                                                                        | All 17 tests passed, including nested cases.                                                                                                                                                                                        |
| `npm test --prefix packages/google-photos`, WSL Ubuntu with Node 22.23.4 on PATH                               | All 61 tests passed; zero skipped, zero failures. Journal temporary directories used the Linux filesystem.                                                                                                                          |
| `npm exec --yes --package=node@22.23.4 -- node --test packages/google-photos/test/*.test.js`, native Windows   | 61 tests: 59 passed; the same two journal permission failures remained. No tests were skipped or guards weakened.                                                                                                                   |
| `npm run build:capture --prefix packages/google-photos`                                                        | Passed.                                                                                                                                                                                                                             |
| `npx --prefix packages/google-photos playwright install chromium`                                              | Completed successfully.                                                                                                                                                                                                             |
| `npm run test:browser --prefix packages/google-photos`, Windows Node 24.14.1                                   | Passed after synchronization correction. Five complete baseline entries, six total network calls including the separate limit probe, no synthetic secret markers exported, download read-back passed, oversized capture incomplete. |
| `npm exec --yes --package=node@22.23.4 -- node packages/google-photos/tools/browser-smoke.mjs`, native Windows | Passed with Chromium 156.0.8078.4 and the same assertions.                                                                                                                                                                          |

The native Windows `FileJournal` limitation remains explicit. Its current private
directory check and directory-sync implementation were not replaced with weaker
semantics. A Windows journal needs separate privacy, locking, replacement and
durability qualification; the in-memory journal is not a production substitute.

## Remaining blockers and next step

The operator completed browser setup after being asked to dismiss the unexpected
passkey prompt with **No**. Both browser surfaces subsequently showed signed-in
Google Photos. No isolated test account was confirmed, so the existing archive
was kept read-only.

Installation-time confirmation was requested for the built extension's
`activeTab`, `debugger`, `scripting` and `storage` permissions. Before installation,
Computer Use stopped a new-tab action because it could not establish the current
Windows browser URL confidently enough to enforce its policy. Browser actions
were stopped; no alternate control path was used to bypass that restriction.

Next, the operator can manually load the repository build at
`dist/capture-extension/` into the signed-in Chrome profile and use **Check
connection**, or resume browser setup when supported control is available. Then
capture one focused read at a time. Qualify library pagination, favorites, albums,
an album's members and exact item details against the parser before attempting
writes. Keep only reviewed, minimal sanitized fixtures, with aliases consistent
within each capture.

For write qualification, first provide an isolated test account/library. Then
create synthetic media with a recorded SHA-256 and size, upload exactly once,
map the resulting namespaces through read-back, and capture each reversible
favorite/album/trash/restore operation separately with postcondition checks.
Browser-upload initialization, transfer, finalization and token/media mappings
remain unknown. Do not infer any of them from the synthetic upload route or
official API tests. Never retry a write with an uncertain result.

No disposable remote media or albums were created or left behind. No raw HAR,
browser profile, live account email, media URL, personal-photo screenshot,
credential or token was added to the repository.
