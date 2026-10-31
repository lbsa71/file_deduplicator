# Verified frame-length incompatibility, 2026-10-31

Starting `origin/main`: `de7f00cb47a7b3bb089e108622f1881808633521`.
Browser: Chrome 156.0.8078.74 on Windows. Account alias: `personal-account-A`.

## Live evidence and cause

After the operator reloaded the rejected-read diagnostic build, one explicit
**Read inventory counts** attempt stopped with `PROTOCOL`. Its downloaded
`readInspection` identified `RPC_FRAME_LENGTH` and retained the sanitized returned
payload. No passive recording was active for this attempt. This evidence comes
from the value delivered to the parser, independently of Chrome's earlier
`net::ERR_ABORTED` Network events.

The first `lcxiM` response had HTTP 200 status and a 500-row library page with a
string continuation cursor. The observed framing measurements were:

| Frame          | Declared length | UTF-16 string units | UTF-8 bytes |
| -------------- | --------------: | ------------------: | ----------: |
| Library RPC    |          332530 |              332528 |      332605 |
| First trailer  |              57 |                  55 |          55 |
| Second trailer |              28 |                  26 |          26 |

Every declared length equals the JavaScript string length plus two. The existing
decoder accepted UTF-8 byte length or byte length plus one, so it rejected these
frames. The first frame also has different UTF-16 and UTF-8 lengths; changing a
byte-only offset would not resolve the observed Unicode case. The precise text
was redacted and is not reproduced here.

The sanitized 500-row payload passed the existing library-page/item parser when
checked independently of framing. It remained nonterminal. No subsequent page,
favorites list or album list was obtained by that failed attempt. This proves a
framing incompatibility; it does not prove a complete library inventory or
establish why Chrome previously reported cancelled network completion.

## Correction and regression evidence

A failing behavioral test first reproduced the rejected length convention with
a reviewed reduced live payload and entirely synthetic Unicode envelope text.
The decoder now also accepts an exact UTF-16 string-length-plus-two declaration.
The existing byte-length forms remain supported. Other lengths still fail;
RPC identity, JSON, payload shape, pagination and account guards remain intact.
No request format, endpoint, timeout, retry or mutation policy changed.

The fixture at
[`test/fixtures/live/library-first-page.sanitized.json`](../../test/fixtures/live/library-first-page.sanitized.json)
retains one actual sanitized row and the nonterminal cursor. Its
[provenance and redactions](../../test/fixtures/live/README.md) explain aliases,
number coarsening, row reduction and synthetic Unicode. The complete original
export remains ignored and private. Reconstructed test frames use recalculated
lengths, not the original lengths of now-redacted data.

- Before implementation, the Unicode/trailer regression failed with
  `Invalid RPC frame length`.
- The focused framing and client tests passed all ten tests afterward.
- The full package suite passed all 78 tests on Linux Node 22.23.4, no skips.
- `npm run build:capture --prefix packages/google-photos` passed.
- The actual extension test passed on Chromium 156.0.8078.4 and Windows
  Node 22.23.4 with the observed framed response convention, synthetic Unicode,
  successful reads, passive download, failure diagnostics, export/body limits,
  source-folder rejection and command timeout checks.
- Corrupt frame lengths, wrong RPC IDs, malformed payloads and duplicate RPC
  results reject after one read; no continuation request is sent.

The framing correction is verified against the captured result and synthetic
Chromium responses. A rebuilt-extension live check is pending manual Reload,
which browser automation cannot perform on the extension-management page.
Successful pagination, favorites, albums, membership and details remain to be
qualified. No retention-ready inventory or live mutation qualification is claimed.

No personal photos or albums were changed. No disposable remote items were
created. Mutation testing still requires synthetic media in an isolated library.
