# Rejected read result diagnostics, 2026-10-31

Starting `origin/main`: `00829a60c32a3733f16524e3d2352fd43da205be`.
Chrome 156.0.8078.74, Windows, account alias `personal-account-A`.

The operator reloaded the diagnostic build and reported `PROTOCOL`, rather than
a fetch/body-stage error. Native inspection confirmed that message. One further
explicit inventory attempt was recorded passively, then stopped and downloaded.
The export has three entries, zero pending entries and `complete: false`.
Its `lcxiM` POST has HTTP 200 headers, no captured response body,
`networkError: net::ERR_ABORTED` and `canceled: true`. Unrelated identity/telemetry
responses were sanitized. The trace remains in the ignored capture directory.

This establishes both a parser rejection and Chrome reporting a cancelled
network completion. It does not identify a rejected field or establish why the
request is cancelled. The passive export cannot explain what value the client
actually parsed. No parser or request-format change is justified by that trace.

A separate ordinary UI read opened **Favorites** while recording. The page
rendered favorites. Its six-entry sanitized capture remains incomplete: two
`EzkLib` responses have HTTP 200 headers followed by `net::ERR_ABORTED`, with
response bodies omitted. An auxiliary `Ljdjxb` response was captured, but it is
not a favorites enumeration. This shows the network cancellation flag also
occurs during successful UI rendering; it cannot alone identify the injected
reader's failure. No pagination completeness or favorite-state parser contract
was established from this capture. The original full capture remains ignored.

The extension now retains a separate, bounded `readInspection` record for the
last failed explicit read. It uses the existing sanitizer on the value returned
to the client, independently of passive Network events. Download works even
without a preceding passive recording. A fixed rule code identifies recognized
parser checks; unknown exception text is omitted. The record includes sanitized
request/payload structure and original frame-length metadata, never raw text,
account values or credentials. Input and exported evidence are limited to 1 MiB.
It always says `complete: false`, has a distinct source kind, and is cleared by
the next explicit inspection or capture start. Aliases are consistent within the
record only. The exporter makes no additional network requests.
The combined serialized export still has an 8 MiB limit. A failing Chromium
regression first demonstrated that the added inspection could exceed it; the
export now stops instead of bypassing that limit.

Two new unit tests failed before implementation. The actual Chromium test also
failed because rejected-read evidence was absent. After implementation, both
unit tests passed and the actual extension test preserved a deliberately invalid
frame's fixed rule and sanitized payload without its private text or another
request. A further failing privacy test showed that an ordinary numeric JSON
value could be mistaken for frame-length metadata. Declared lengths are now
accepted only within a bounded, prefix-bearing framed-array structure.
All earlier extension checks passed. The full package suite passed all
76 tests on Linux Node 22.23.4, with no skips. Chromium 156.0.8078.4 on Windows
Node 22.23.4 was used for the synthetic extension test. The existing native
Windows journal privacy limitation remains unchanged.

The build is ready for manual reload and one focused live read. Use its sanitized
returned-result evidence to reproduce the exact parser rejection before changing
the contract. A sanitized payload changes string/number values and cannot reuse
the original frame length as an exact replay. Any regression fixture must explain
these redactions. Passive recording completeness and read-inspection evidence
remain separate; neither establishes complete account enumeration.

No photos or albums were changed, and no disposable remote items were created.
Favorites, albums, album members, details, pagination and mutations remain
unqualified. Mutation work requires synthetic media in an isolated test library.
