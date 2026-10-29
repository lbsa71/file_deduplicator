# PhotoFlow Web

React photo browser and Python API backed by the existing PhotoFlow library.
The Ubuntu installation is served at **https://192.168.1.4:8443/**. Sign in with
an allowed Linux account's local password. This LAN installation uses a self-signed
certificate; trust `/etc/photoflow-web/tls.crt` on your client or provision a trusted
certificate before normal use outside this LAN.

The current application provides timeline/search/favorites/duplicate browsing,
real folder navigation, multi-file uploads with resumable chunks, original and
metadata downloads, selected-original ZIP exports, editable sourced metadata,
manual moves, persistent user-folder creation/rename, photo/folder trash and
restore, reconciliation jobs, five thumbnail levels, and native video playback.
Unplayable codecs retain their original download and a poster where supported.

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
