# PhotoFlow Web

React photo browser and Python API backed by the existing PhotoFlow library.
The public installation is served at **https://photos.lbsa71.net/** through the
existing Cloudflare Tunnel, with a publicly trusted HTTPS certificate. Sign in
with an allowed Linux account's local password.

The direct LAN address **https://192.168.1.4:8443/** remains available with its
self-signed certificate. The public hostname does not require trusting that LAN
certificate.

## Direct URLs

Views are addressable and survive refresh, browser Back/Forward, and opening a
copied link in another tab. Sign-in preserves the requested destination.

| URL | View |
| --- | --- |
| `/photos` | Timeline |
| `/photos/<record-id>` | A photo or video's viewer; the ID survives filesystem moves |
| `/folders/photos/2000/09` | An editable root-relative folder path in the URL |
| `/folders?path=photos%2F2000%2F09` | Supported query-form folder link |
| `/favorites`, `/duplicates`, `/trash`, `/activity` | Main views |
| `/photos?q=00010005`, `/favorites?q=Alma` | Search within a view |
| `/photos?offset=100` | A later page of results |
| `/login?next=%2Ffavorites` | Sign in and return to an internal destination |

Photo links also retain collection context in `view`, `path`, `q`, and `offset`
parameters when needed. Folder paths follow the current filesystem layout; photo
IDs provide stable links across moves. Navigation/photo/folder links support
native copy-link and open-in-new-tab behavior. The server serves the UI shell for
known routes; missing API endpoints and assets retain their 404 responses.

The current application provides timeline/search/favorites/duplicate browsing,
real folder navigation, multi-file uploads with resumable chunks, original and
metadata downloads, selected-original ZIP exports, editable sourced metadata,
manual moves, persistent user-folder creation/rename, photo/folder trash and
restore, reconciliation jobs, five thumbnail levels, and native video playback.
Unplayable codecs retain their original download and a poster where supported.

Takeout's `favorited` flag is imported into Favorites, while explicit user choices
take precedence. The viewer displays a cached grid preview immediately and keeps
it if the larger preview fails. JPEG/PNG/etc. previews use libvips; HEIC/HEIF uses
the bounded, single-threaded `pillow-heif` worker to avoid the system decoder's
HEIC stalls. All delivered still-image previews are WebP, so browser HEIC support
is not required. Decoder stability checks ignore normal access-time changes and
still reject content/identity changes during rendering and export.

Login uses the separate PAM broker; the HTTP process is unprivileged. Linux groups
`photoflow-readers`, `photoflow-editors`, and `photoflow-admins` grant increasing
roles. `stefan` is an administrator on the installed server. Restart invalidates
browser sessions. Credentials and session cookies are never stored in records.

## Operator commands

```bash
sudo systemctl status photoflow-web photoflow-auth
sudo journalctl -u photoflow-web -u photoflow-auth -n 100
sudo systemctl restart photoflow-web
```

The UI/API listens on loopback port 8090 behind the existing nginx HTTPS proxy on
8443. Systemd enables both services at boot. Configuration templates are under
[deploy/](deploy/); passwords/certificate keys do not belong in the repository.
Library: `/mnt/usb/PhotoLibrary`. Catalog/cache: `/var/lib/photoflow-web`.
Executable environment: `/opt/photoflow-web-venv`. Pinned ExifTool 13.59:
`/opt/photoflow-exiftool`. Installed packages and the privileged broker are root-owned.

The writer marker is now format 2. The original marker is preserved under
`.photoflow/preparation/pre-web-library-v1.json`. Use the updated CLI from this
checkout or `/opt/photoflow-web-venv/bin/photoflow`; older binaries refuse format 2.
The migration itself does not reorganize media. Do not downgrade the marker after
using manual placement/trash. Recover web intents with the updated writer.

## Public Cloudflare route

`cloudflared.service` uses `/etc/cloudflared/config.yml`. The existing `home-media`
tunnel also serves `photos.lbsa71.net` using `http://127.0.0.1:8091` as the origin.
The nginx origin template is [deploy/nginx-cloudflared.conf](deploy/nginx-cloudflared.conf).
It is bound only to loopback, sets the public Host/HTTPS scheme for CSRF checks,
and accepts Cloudflare's client IP only from the local tunnel connector. Login
throttling uses that client IP, with an additional nginx rate limit. Public
responses are marked private/no-store, including authentication failures and
protected media.

The Cloudflare DNS route points at the existing tunnel. The added ingress rule
precedes its final catch-all; the existing media/home-media routes are retained.
The pre-change configuration is backed up at `/etc/cloudflared/config.yml.pre-photos`.
Tunnel credentials and the account certificate remain outside this repository.
The routing pattern follows Cloudflare's [local tunnel configuration](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)
and [DNS route documentation](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/).

To remove public serving, remove the photos ingress and its DNS record, validate
the config with `cloudflared tunnel ingress validate`, and restart cloudflared.
Do not blindly restore the backup if other tunnel routes have changed since.

## Build, test, and update

### Local extension debugging on macOS

Install the dependencies and build the UI using the commands below, then run:

```sh
.venv/bin/python apps/web/dev.py
npm run build:capture --prefix packages/google-photos
```

Open `https://localhost:8099` in Chrome. The development runner creates a
self-signed localhost server certificate (`CA:FALSE`). Background HTTPS/WSS needs
a trusted certificate even when a page exception allows the app to load. On macOS,
explicitly trust this certificate for SSL in your user keychain (this changes local
certificate trust):

```sh
security add-trusted-cert -r trustRoot -p ssl -k "$HOME/Library/Keychains/login.keychain-db" .local/web/cert.pem
```

The certificate name is only `localhost`. Do not use `-s localhost`: Chrome ignores
macOS trust entries with that extra policy constraint. The certificate expires in
30 days; replacing it requires explicitly trusting its replacement. Keys and
certificates remain under `.local/`, outside Git.

Sign in as `dev` with password `local-development-only`. The server listens only
on loopback and uses a persistent, initially empty library and state under the
gitignored `.local/web/`. It uses development authentication instead of Linux PAM
and disables Google mutation pilot configuration. No real photo library is needed.

Load `packages/google-photos/dist/capture-extension/` as an unpacked extension,
or reload that same extension after each rebuild. Open PhotoFlow and a signed-in
Google Photos tab in the same Chrome profile. Allow extension access to localhost
if Chrome requests it. Expand **Connect Google Photos**, enter the Google account,
and click **Connect through installed extension**. The app creates and redeems the
code automatically using its current address and the matching Google account.
The in-app browser cannot use Chrome's installed extension.

macOS previews require `brew install vips` (and `ffmpeg` for video posters).
The decoder wrapper retains CPU, file-size and descriptor limits. Linux also
uses a 512 MiB address-space limit; macOS rejects that limit, so its supervisor
samples the decoder process tree's resident memory and terminates the group above
512 MiB or the wall deadline. Memory sampling is periodic, not a kernel allocation
limit. Imported originals now publish the final verified filesystem signature so
thumbnails can render immediately; an interrupted finalization replays its local
receipt without downloading again. Darwin file and directory publication uses
atomic `renamex_np(RENAME_EXCL)` and rejects occupied destinations.

The popup remains available for manual pairing with other HTTPS endpoints. Its
endpoint preference survives failed pairing and reopening. Existing pairings
remain bound to their original server until re-paired.

Restart the Python process after backend edits; rebuild the UI after frontend
edits. Rebuild and reload the extension after its code changes. Local runtime data
survives restarts. `download-link` probes availability; `download-original` imports
one JPEG, PNG or WebP original up to 16 MiB. Select **Download one original into
this library** in the operation workbench and supply a library photo URL.
The extension obtains a short-lived reference and sends it over authenticated
HTTPS; the server downloads without Google cookies. Signed references are never
stored in jobs, sidecars or logs. A single-member Google ZIP is read in memory,
with exact filename/size checks and no filesystem extraction. Motion photos with
companions, multi-file archives, redirects and unsupported formats stop the import.
Original bytes are validated and SHA-256 checked against local originals before
committing. Repeating a job returns its durable receipt; a new job rechecks bytes
and reports `already-present` without creating another original. Google observations
are preserved in the sidecar's `google_originals` field; this is not Takeout metadata
round-trip qualification. The transfer requires a current worker token, account,
running job, matching target and lease. A local import never authorizes cloud deletion.

In the same workbench, enter a library photo URL and click **Check local original**.
The check uses the currently paired account and the sidecar's explicit
`google_originals` associations. It rehashes mapped active originals and returns
links to verified local records. Unmapped IDs, trash, stale sidecars, changed bytes,
unavailable files and conflicting associations have distinct outcomes. Unmapped
does not prove absence: legacy Takeout URLs without account attribution are not
automatically associated. The disposable identity index is rebuilt from sidecars
with the catalog. Checks accept at most 100 explicit library-media targets, inspect
at most 100 candidate mappings per target, and hash at most 256 MiB per request;
larger checks remain deferred or ambiguous. The UI checks one selected photo.
This makes no Google requests and never treats a saved Google ID as proof of current
remote byte equality, complete backup, or cloud retention eligibility.

The worker smoke test covers rejected-code diagnostics, endpoint persistence,
page-based pairing, WSS, all typed jobs, and account-bound local verification using
synthetic Google responses.
It uses port 8100 alongside development on 8099. Set
`PHOTOFLOW_TEST_PAGE_TLS_ONLY=1` only to reproduce background TLS failures with its
untrusted disposable certificate; that diagnostic negative test is expected to fail.

### Standard build

Use Python 3.11+ and Node 22 for development/browser tests. Install system ExifTool,
libvips, ffmpeg, and PAM runtime libraries. Preserve the configured ExifTool version
when upgrading. From repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r apps/web/requirements.lock
.venv/bin/pip install -e apps/photoflow -e apps/web
(cd apps/web/ui && npm ci && npm run build -- --outDir ../photoflow_web/static --emptyOutDir)
PYTHONPATH=apps/web:apps/photoflow .venv/bin/python -m unittest discover -s apps/web/tests
python3 -m unittest discover -s apps/photoflow -t apps/photoflow
(cd apps/web/ui && npm test)
```

For the installed host, rebuild the UI, then install the two packages non-editably:

```bash
sudo /opt/photoflow-web-venv/bin/pip install --no-deps --force-reinstall ./apps/photoflow ./apps/web
sudo systemctl restart photoflow-web
```

Keep this environment root-owned: the PAM broker imports code from it. Updating
unit/proxy templates requires copying the changed files, `systemctl daemon-reload`,
`nginx -t`, and reloading/restarting the relevant services. First installation also
requires explicit account/group setup, PAM configuration, certificate provisioning,
and `photoflow-web-migrate ROOT`; review the templates for host-specific paths.

Browser smoke test: install Playwright's Chromium, then set
`PHOTOFLOW_TEST_USER`, `PHOTOFLOW_TEST_PASSWORD`, and optionally `PHOTOFLOW_TEST_URL`
in the process environment and run `node apps/web/ui/browser-smoke.mjs`. Use a
scratch/test account; screenshots are written to `/tmp`, never committed.
For direct-LAN tests only, set `PHOTOFLOW_TEST_INSECURE=1` for the self-signed
certificate. Public-host tests validate certificates normally. The optional
`PHOTOFLOW_TEST_RESOLVE` passes a Chromium host-resolution rule for testing a new
DNS record before local negative caches expire; it does not disable TLS validation.
`node apps/web/ui/routing-smoke.mjs` uses the same test credentials/environment to
check direct links, login return, refresh, new tabs, Back/Forward, folder paths,
search persistence, redirect safety, and missing-resource responses.

## Visual queries and batch maintenance

Place is an ordered hierarchy in each sidecar (`resolved.place`), for example
`["Stockholm", "Stockholms Kommun", "Sweden", "Europe"]`. The Place selector
matches any selected city, region, country or continent: `/photos?place=Stockholm&place=Norway`.
Counts include all hierarchy levels and overlap. Viewer details show the hierarchy,
approximate locality distance and GeoNames attribution. Manual place edits/reset
use the existing metadata and reviewed batch forms. Unchanged fields in the editor
do not become manual overrides.

Coordinates are reconciled from preserved embedded GPS and Takeout observations.
Disagreements over 250 metres are flagged for review; manual coordinates take
precedence. Missing coordinates, missing place names and conflicts are maintenance
filters. Offline ExifTool enrichment uses the expanded GeoNames database configured
by `PHOTOFLOW_GEODIR`; install the pinned database from
[ADR 0002](spec/adr/0002-place-hierarchies-and-offline-geocoding.md).
No external geocoding API receives photo locations. Nearest-settlement labels are
approximate and do not establish administrative boundary containment.

Backfill with `photoflow run ROOT --exiftool --places --geodir DIRECTORY --no-move`.
Place results persist in sidecars; `.photoflow/place-cache.json` is rebuildable.

The [accepted design](spec/adr/0001-visual-querying-and-saved-views.md) uses coordinated
People, Time, Favourite, Albums, Tags, media-type and missing-metadata filters.
People supports Any/All; dates have a histogram, keyboard range slider and exact
inputs. Facet values show contextual counts. Filter chips, browser Back/Forward,
photo links, refresh and login return all preserve queries.

Example: `/photos?person=Ellen&person=Viktor&people_mode=all&from=2009-01-01&to=2009-12-31`.
Save view creates a private Linux-account shortcut; Manage renames, replaces its
query, or deletes the shortcut. Saved views are live queries, independently of
Google album labels. Back up `.photoflow/views/` alongside the other library intent.

Select page retains explicit IDs and revisions across pages. Select all matching
captures the whole query for 30 minutes, including unloaded results. Changing the
query clears selection. Batch actions previews up to five before/after examples
and the full target count before applying add/remove/replace/reset labels,
favourites, capture dates, folder moves, trash or restore. Revision conflicts are
skipped and reported; the original source documents remain preserved. Batch plans
are single-use; an interrupted run requires a fresh reviewed selection. Admin
maintenance modes operate on the whole library and are separate from selection.

Rebuildable SQLite label/property indexes serve filtering without sidecar or
original reads. A scratch benchmark copied from 24,283 live catalog rows measured
warm medians of 10.4 ms for listing, 99.4 ms for facets, and 40.7 ms for a full ID
snapshot on this server; these are local measurements, not network latency promises.
Catalog rebuilds commit coherent batches of 64 records using a rollback journal,
allowing reads between batches. During a scan, results reflect the latest committed
incremental catalog rather than one whole-scan snapshot; a current batch may briefly
delay a read. The installed SQLite runtime predates the WAL-reset fix, so WAL is
deferred pending a patched runtime. Query measurements above were taken outside a
running scan.

Browser acceptance uses a disposable HTTPS fixture (never the real library):

```sh
make build-web
PYTHONPATH=apps/web:apps/photoflow .venv/bin/python apps/web/tests/query_fixture.py
# In another terminal, with Playwright Chromium installed and Node 20+:
node apps/web/ui/query-smoke.mjs
```

The fixture creates 108 distinct photos and checks original hashes on shutdown.
The browser exercises Any/All, date/favourite filters, query history, saved-view
CRUD and a reviewed batch across pagination.

## Current limits and remaining specification work

The [complete specification](spec/README.md) remains the target. This deployment is
an initial implementation, not certification of every acceptance gate:

- Timeline pages use bounded offset pagination. Select-all and batch operations
  freeze their own IDs/revisions; normal page navigation is not a frozen snapshot.
- Job statuses persist, but interrupted queued jobs are marked failed for explicit
  resubmission; full automatic job replay, cancel/retry UI, and SSE remain work.
- Folder subtree trash preserves unknown files and can be restored as a whole;
  it processes media occurrences in recoverable steps rather than one atomic
  multi-record transaction. Permanent purge is deliberately not exposed yet.
- Linux login/group authorization, same-origin CSRF, secure cookies and decoder
  limits are present. Full session-administration UI and the entire authentication
  fault matrix still need coverage.
- Watch notifications debounce for 60 seconds with daily reconciliation. They
  currently trigger full batch passes; targeted dependency processing, robust
  remount/overflow recovery and watcher-specific failure tests remain work.
- Thumbnails are generated on demand. Full LRU eviction (basic capacity eviction is present), persisted failure status,
  fully prioritized warming and the complete format/performance matrix remain
  work. The UI uses React JavaScript rather than the proposed TypeScript baseline.
- Capture-date editing uses ISO strings; explicit precision objects, richer
  location editing, virtualized timelines, and full
  keyboard/touch/accessibility coverage remain work.
- Date-offset correction, targeted thumbnail repair, failed-thumbnail filtering,
  and automatic expired selection/plan file cleanup remain work. Whole-library
  maintenance and missing-date/people/album filters are available now.

Back up originals, sidecars, folder intent, relocation mappings and trash manifests.
The SQLite catalog and thumbnail cache are disposable. Do not remove source JSON
merely because its associated image has moved.

## Google Photos desktop worker

Administrators now have a Google Photos connection control in the header. Install
[the companion ZIP](https://photos.lbsa71.net/tools/google-photos-worker-0.3.0.zip)
as an unpacked Chrome/Edge extension. Choose the folder containing manifest.json;
source installation is deliberately disabled. Existing installations must rebuild
and manually reload their unpacked extension. Version 0.3 uses job protocol 2 and must be loaded alongside the updated server;
its permissions are unchanged from 0.2.

Open Google Photos, use Check connection, and copy its account value into the
PhotoFlow connection panel. Create a pairing code there, paste it into the
extension while the Google tab is selected, and click Pair with PhotoFlow. A
single read-only inventory job is queued automatically. The warning clears after
successful validated reads. Read inventory counts submits another job; Disconnect
Google worker revokes the server credential. Forget pairing on this browser clears
local credentials only; use the PhotoFlow action to revoke server authorization.

The desktop initiates WSS over the existing HTTPS hostname, so it needs no inbound
network access. Google authentication stays in the desktop profile. Counts and
job states persist independently of photo scans. A closed browser leaves reads
queued; expired Google login needs attention in that browser. Pairing credentials
expire after 14 days. The first release requires a manual copy/paste pairing code;
connection is not automatically initiated merely by opening Google Photos.

For troubleshooting, download a job's server diagnostics in PhotoFlow and the
latest worker diagnostics from the extension. Correlate job ID/attempt/phase;
review sanitized data before sharing. These diagnostics do not prove remote
absence or authorize removal. See [ADR 0004](spec/adr/0004-desktop-google-worker.md)
for the protocol, storage, bounds and procedure for adding job types.

The operation workbench offers a prepared finite read suite, isolated write pilot
suite, individual typed jobs and private result inspection. Pilot writes are disabled
unless an operator explicitly configures a separate disposable Google account.
This is a real Google account with synthetic photos, not an account created by
PhotoFlow. See [ADR 0005](spec/adr/0005-google-job-qualification.md) for the full
catalogue, setup, test fixture conventions, suite effects and recovery procedure.
Production retention mutations, image-upload jobs and media download transfers
are not enabled by this workbench.

Developer verification (Node 22, Python web dependencies, OpenSSL and Chromium):

```sh
make build-web
npm run build:capture --prefix packages/google-photos
PHOTOFLOW_TEST_PYTHON=/path/to/web-venv/bin/python npm run test:worker --prefix packages/google-photos
```

The test launches a disposable HTTPS/WSS app on loopback port 8099 and a temporary
extension profile. It replaces the extension's origin only inside that temporary
build; the shipped extension remains pinned to photos.lbsa71.net. All Google
responses are synthetic. It neither opens nor modifies the real library.
