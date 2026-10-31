# Inventory read failure and safe diagnostics, 2026-10-31

Starting `origin/main`: `7920ef65357663e2704688e95d35ad74afcbda54`.
Account alias: `personal-account-A`. Chrome 156.0.8078.74 on Windows;
capture through the correctly installed repository-built unpacked extension.

## Live observations

The operator reported that **Check connection** returns the account after loading
the built directory. Native UI inspection confirmed that the extension status,
capture start/stop and sanitized capture download work. The earlier missing-worker
installation is resolved; see [its report](2026-10-31-source-installation.md).
**Read inventory counts** still fails. No photo mutations were performed.

One explicit inventory attempt was recorded passively. The sanitized export has
four entries, zero pending entries and `complete: false`. The first library read
is a POST to `/_/PhotosUi/data/batchexecute`, RPC `lcxiM`. HTTP 200 response
headers were observed, followed by failed network completion and an omitted
response body. The request has the expected positional array structure. Its
page-size number is coarsened by sanitization and is not evidence that the
original request used that number. No cursor or terminal page was obtained.

After stopping capture, a separate explicit read was inspected through DevTools
Network. The filtered HAR has one entry: the same RPC, HTTP 200, approximately
1.08 seconds, response size 332,706 bytes, `net::ERR_ABORTED`, and no response
text. Service-worker router metadata names the network as the matched and actual
source; `fetchedViaServiceWorker` is false. These fields establish an aborted
read, not its cause. DevTools was closed afterward. It was never opened while
the extension recorder was attached. No captured request was replayed.

Both traces and the private HAR remain under the ignored `captures/2026-10-31/`
directory. No response body was available to pass through the parser. There is
no live parser fixture, verified pagination, complete inventory, favorite/album
coverage or retention-ready snapshot from these attempts.

## Diagnostic correction

The old popup replaced read errors with one generic message. Four failing tests
first demonstrated missing fetch/body phase diagnostics, loss of safe network
cancellation evidence and suppression of an allowlisted read error at the popup.
The focused run had 29 passes and four failures before implementation.

The transport now returns only a fixed stage and allowlisted exception name on
failure. The worker forwards fixed error codes, and the popup formats them using
static messages. Exception messages, stack traces, URLs, session values and raw
payloads never become diagnostic text. Unknown codes keep the generic message.
The passive recorder preserves a supplied boolean cancellation flag and one of
four fixed network error codes; arbitrary network error text is omitted.

No endpoint, request format, size limit, timeout, retry policy, parser contract,
extension permission or production mutation capability changed. This update
improves diagnosis; it does not establish or repair the cause of the live abort.

## Verification

- The focused Node tests passed all 33 tests after the correction.
- `npm run build:capture --prefix packages/google-photos` passed.
- The actual extension test passed on Chromium 156.0.8078.4 with Windows
  Node 22.23.4. A synthetic failed response stream reached the popup as a fixed
  response-body/TypeError message without its private exception text or another
  network request. Source-directory rejection, successful reads, capture download,
  incomplete oversized capture and stalled-command timeout checks also passed.
- The full package suite passed all 73 tests on Linux Node 22.23.4, with no skips.
- These successes use synthetic or sanitized fixtures, not the live library.
  Native Windows journal qualification still has the previously documented two
  private-directory failures; its guard remains unchanged.

## Remaining qualification

The tested build is ready for a manual extension reload and one focused live
read to identify the failure phase. Browser control blocks the extension
management page, so the operator must perform Reload. A parser change requires a
complete, reviewed response body and a failing fixture; an HTTP 200 header is
insufficient evidence.

No disposable remote items were created. Mutation qualification, browser uploads
and upload-ID correspondence still require synthetic media in an isolated test
account/library. The personal library remains read-only.
