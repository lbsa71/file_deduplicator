# Reviewed live fixtures

`library-first-page.sanitized.json` comes from the explicit `lcxiM` read result
exported by Chrome 156.0.8078.74 on 2026-10-31, using account alias
`personal-account-A`. It retains one row from a 500-row first page, the
continuation token and the third page field. The page is not terminal. Retaining
one row is a parser test reduction, not evidence of a one-item library.

All strings, including media/dedup identifiers, thumbnail URLs, cursor and time
strings, were replaced with aliases by the repository sanitizer. Aliases are
consistent within this fixture only. Large numbers and timestamps became 1000;
small numeric enums, booleans, nulls and array positions were preserved. No
credentials or account email are present. This fixture tests structure and
continuation semantics, not real sizes, dates or cross-capture identity.

The original first frame had declared length 332530, JavaScript string length
332528 UTF-16 units, and UTF-8 length 332605 bytes. Two ASCII trailer frames had
declared/string lengths 57/55 and 28/26. Each declared length was exactly the
string length plus two. The original full capture remains ignored and private.

`live-framing.test.js` wraps this reduced payload in newly calculated frames.
Its additional `synthetic-é-😀` envelope value is entirely synthetic: sanitization
replaced the original non-ASCII text. It tests UTF-16 versus UTF-8 accounting,
including an astral character, without reproducing any personal text. Original
frame lengths cannot be reused after aliases, number coarsening or row reduction.
