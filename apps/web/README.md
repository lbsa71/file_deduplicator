# PhotoFlow Web

React photo browser and Python API backed by the existing PhotoFlow library.
The public installation is served at **https://photos.lbsa71.net/** through the
existing Cloudflare Tunnel, with a publicly trusted HTTPS certificate. Sign in
with an allowed Linux account's local password.

The direct LAN address **https://192.168.1.4:8443/** remains available with its
self-signed certificate. The public hostname does not require trusting that LAN
certificate.

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

## Current limits and remaining specification work

The [complete specification](spec/README.md) remains the target. This deployment is
an initial implementation, not certification of every acceptance gate:

- Timeline pages currently use bounded offset pagination, not frozen cursor
  snapshots. Bulk selection covers explicitly selected records.
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
- Dates are currently entered as ISO strings; explicit precision objects, richer
  location editing, field-specific search filters, virtualized timelines, and full
  keyboard/touch/accessibility coverage remain work.

Back up originals, sidecars, folder intent, relocation mappings and trash manifests.
The SQLite catalog and thumbnail cache are disposable. Do not remove source JSON
merely because its associated image has moved.
