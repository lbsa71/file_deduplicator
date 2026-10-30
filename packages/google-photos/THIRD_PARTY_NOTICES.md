# Third-party notices

Protocol request layouts, positional response field knowledge, and sanitized
test-fixture shapes are adapted from Google Photos Toolkit by xob0t, version
3.3.0, commit `6db9ab355e4797327e4078cf87a2b6994d36cf73`:

https://github.com/xob0t/Google-Photos-Toolkit

Upstream files: `src/api/api.ts`, `src/api/parser.ts`, `src/windowGlobalData.ts`,
and `tests/fixtures/parser/*.json`. Fixture strings/identities have been replaced
with synthetic aliases and collection pages truncated to two items. Raw account
credentials, URLs, names and original filenames are not retained. Upstream's
request retry, pagination, batch execution and capture wrappers are not used.

Copyright (c) 2024 xob0t. Licensed under the MIT License, reproduced in
[LICENSE](LICENSE). PhotoFlow additions are also provided under that license.

Google Photos and Chrome are Google trademarks. This is an independent,
unofficial integration; Google does not support the undocumented protocol.
