# Connection-check follow-up, 2026-10-31

Starting `origin/main`: `4783413d2317bc58d67c591b0f6a7b2dd6d83e52`.
This continues the [2026-10-30 qualification report](2026-10-30-browser-session.md).
The later [source-folder diagnosis](2026-10-31-source-installation.md) identifies
why the installed copy could not respond; the observations below describe the
earlier investigation before that folder mismatch was established.
The operator explicitly approved installing the capture extension for reads only,
installed the repository build manually, and reported that **Check connection**
remained on "Working…". No live photo changes were authorized or attempted.

## Live observations

- The PhotoFlow capture extension was present in the personal Chrome profile,
  which remains aliased as `personal-account-A`.
- Its popup opened with "Ready". One identity check changed it to "Working…"
  without producing a result during subsequent inspection and repository work.
- Chrome DevTools was open on the Google Photos tab. It was closed before a
  second identity check; the same pending state was observed. Closing DevTools
  alone therefore did not resolve the reported failure.
- The existing build had no deadline around tab lookup or extension messaging.
  Its background handler awaited script injection without an outer deadline.
  No live identity result or authenticated RPC response body was obtained.
- No capture was started and no inventory-count probe was run. No user media,
  albums, favorites or trash state was changed. No remote test items were created.

The exact Chrome/page condition preventing the original injection from settling
has not been established. This report does not claim that a missing session field,
DevTools, the page's Promise implementation, or a Google protocol change was
proved to be the cause.

## Focused fixes

The popup command boundary now has explicit deadlines: five seconds for status,
ten seconds for identity/export, fifteen seconds for capture start/stop, and five
minutes for inventory counts. The deadline includes tab lookup. A tab lookup that
finishes after expiry cannot send a late command. No command is retried.

Replies require an explicit successful envelope and an object result; identity
checks additionally validate the account identifier. Browser exception strings
and untrusted error payloads are replaced with a controlled error rather than
displayed. These checks do not turn unknown identity into an empty account.

The popup handles initialization failures, disables its controls while a command
is pending, and re-enables them after success or error. A timed-out capture
command explicitly has an unknown outcome: the timer does not cancel work already
sent to Chrome or detach a recorder. Its state must be checked before a repeat.

The serializable page evaluator returns identity synchronously, while network
reads still return a Promise and retain their original origin/account checks,
allowlist, response bounds and fetch timeout. Script injection requests immediate
execution rather than waiting for the default document-idle timing. Missing
session state still fails closed; no token or cookie is exported.

These changes remove avoidable waiting from an identity-only operation and bound
the popup even if browser injection never settles. They do not constitute live
read-client or mutation-transport qualification. Chrome documents both its
[Promise-result handling and injection timing](https://developer.chrome.com/docs/extensions/reference/api/scripting).

## Behavioral and browser verification

Failing tests were added before the corrections. They reproduced an indefinitely
pending connection check/tab lookup, a late lookup that could send after expiry,
malformed replies, and disclosure of an injected synthetic exception string.
Identity inspection also initially returned a Promise despite needing no network
operation. After the fix, the focused browser/command tests passed.

The actual-extension smoke test now clicks the popup's **Check connection** button
and checks its result, instead of testing only a direct runtime message. Because
the test hosts the popup as a tab, it supplies a synthetic active-Photos-tab
selection; this is not evidence about native popup targeting in the live profile.
The real extension background and scripting APIs still execute in the disposable
Chromium profile.

A second UI check substitutes a never-settling scripting call inside that test
profile, advances the popup clock past ten seconds, and verifies the timeout
message and re-enabled button. The total number of synthetic photo requests
remains six, including the existing oversized-body probe; neither identity check
sends or replays photo traffic. All Google Photos page requests are fixture-backed.

| Check                                                                        | Result                                                                                                                                                                                |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Focused `node --test` for `browser.test.js` and `extension-commands.test.js` | 12 passed after correction.                                                                                                                                                           |
| `npm test --prefix packages/google-photos`, WSL Linux, Node 22.23.4          | 69 passed, zero failed or skipped.                                                                                                                                                    |
| Full native Windows suite, Node 22.23.4                                      | 67 passed; the same two pre-existing `FileJournal` private-directory failures remain. No guard was removed or test skipped.                                                           |
| `npm run build:capture --prefix packages/google-photos`                      | Passed; rebuilt the already approved unpacked extension directory.                                                                                                                    |
| Actual extension smoke on Windows Node 22.23.4, Chromium 156.0.8078.4        | Passed: popup identity result, bounded stalled-injection error, normal capture, download read-back, oversized capture incompleteness, no synthetic secret leakage, no extra requests. |

The operator was asked to reload the unpacked extension from its existing build
folder before further live testing. The replacement build's live connection
outcome is pending. No live protocol fixture was added and no raw network log,
account email, media URL, credential or personal-photo screenshot was committed.

## Next step

Reload the unpacked extension on Chrome's extensions page, return to the loaded
Google Photos tab and run **Check connection** once. Record whether it returns a
validated identity, a controlled error, or the ten-second timeout. Keep DevTools
closed before any debugger capture. A successful identity check alone sends no
photo request and does not qualify library pagination or retention decisions.

Once connection and passive capture work, capture one focused read at a time and
review its sanitized structure before adding minimal live fixtures. Mutation
qualification remains blocked on an isolated test account/library; the personal
archive stays read-only.
