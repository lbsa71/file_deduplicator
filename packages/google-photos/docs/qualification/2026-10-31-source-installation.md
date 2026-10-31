# Source-folder installation diagnosis, 2026-10-31

Starting `origin/main`: `7e94f12e5016130c4f47966b4ddaf3476f353100`.
The operator reported that every operation timed out after installing and
reloading the capture extension. The popup's initial status-only handshake was
also observed timing out. That command does not inspect the Google Photos page
or send a photo request.

## Established cause

The live popup's extension ID matched the ID derived from the repository's raw
`packages/google-photos/capture-extension/` directory. It did not match the built
`packages/google-photos/dist/capture-extension/` directory.

This was checked against Chromium's
[unpacked-extension ID implementation](https://chromium.googlesource.com/chromium/src/+/main/components/crx_file/id_util.cc):
hash the normalized native path, using its Windows UTF-16 representation, and
encode the first 16 SHA-256 bytes with Chrome's extension-ID alphabet. The source
path matched exactly. Neither manifest supplies a key that would override this
path-derived identity. Only the known repository paths were used for this check;
no browser profile or credential export was required.

The raw source directory had a valid `manifest.json` and popup, but did not have
the `lib/` modules imported by `background.js`. Those modules are copied only
into the build output. Chrome could therefore expose the source popup while its
background worker could not load. Reloading that installed copy preserved its
source path. Changing Google account state or waiting longer could not provide
the missing files.

The operator then disabled the source copy and loaded
`packages/google-photos/dist/capture-extension/`. Its popup ID matched the built
directory and **Check connection** returned the account, as reported by the
operator. Native UI inspection subsequently confirmed working status, passive
capture start/stop and sanitized capture download. The missing-worker installation
is resolved. The inventory-count probe still fails as a separate read issue;
no complete inventory has been qualified and no photo changes were made.

## Packaging correction and tests

A failing Chromium test first reproduced that the incomplete source directory
exposed a loadable popup. The source manifest was then renamed to
`manifest.template.json`. The build generates `dist/capture-extension/manifest.json`
and copies the runtime files and `lib/` modules alongside it. The source directory
is consequently rejected as an extension instead of appearing installed with a
broken worker.

The browser smoke now first attempts to load the raw source in a fresh disposable
Chromium profile and requires its popup navigation to be rejected. It then loads
the actual built extension and runs the existing identity, timeout, passive
capture, download and size-limit checks. This uses synthetic traffic and separate
test profiles, not the signed-in personal library.

- Before the correction, the source-installation regression failed with
  "Missing expected rejection": its popup was accessible.
- `npm run build:capture --prefix packages/google-photos` passed after correction.
- Actual Chromium 156.0.8078.4 on Windows Node 22.23.4 passed the source-rejection
  check and all existing extension checks. The five complete fixture entries,
  separate oversized-response entry and six total fixture requests were retained.
- The full package suite passed all 69 tests on Linux Node 22.23.4, with no skips.
- The README now distinguishes the source and build directories and explains that
  Reload does not change which directory Chrome loaded.

The earlier command deadlines and controlled error handling remain useful, but
they did not fix the missing-worker installation. The synchronous identity probe
and injection-timing changes were not established as the cause of this failure.
No permission expansion or production mutation capability was added.

## Next step

Investigate the remaining inventory failure using focused read evidence. The
first passive trace contains an `lcxiM` POST with HTTP 200 headers followed by a
failed network completion and no captured response body. A separate DevTools
probe also reports `net::ERR_ABORTED`; its private, filtered HAR contains no
response text. Neither trace supports a parser correction or a completeness claim.
Keep the personal archive read-only; mutation testing still needs an isolated
test account/library.
