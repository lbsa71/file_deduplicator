# Running and resuming a production Google retention sweep

The current Google sync is a reviewed retention sweep. Keep starred photos, all
album members, and anything without a verified local original. Known motion
photos without paired local proof and ambiguous matches stay kept. The owner
accepts the independent Takeout backup without verification; original ingestion
comes from periodic manual Takeouts. This workflow does not upload photos or
permanently delete them.

## Start a fresh sweep in the web app

1. Open PhotoFlow and a signed-in Google Photos tab in the same Chrome profile.
   Open the Google connection panel. Connect the existing extension if needed;
   connecting alone does not start a sweep.
2. Expand **Prepare and commit reconciliation**. Leave selected photo URLs empty,
   leave the non-vital pilot checkbox unchecked, and select **Prepare dry-run
   manifest**. This reads the full inventory, favorites and album membership.
3. After completion, select **Inspect prepared manifest**, then **Prepare Takeout
   Trash sweep**. Local originals and preserved Takeout documents are checked.
4. Inspect the new executable manifest and its keep/Trash counts. Check **I
   reviewed this manifest and authorize its listed executable operations**, then
   select **Commit reviewed manifest** when execution is authorized.

The paired desktop executes one target at a time. Current local evidence and
fresh Google protections are checked before each removal, and exact membership
in Trash is verified afterward. A new positive star or album membership keeps
that target. Job progress counts processed operations; verified Trash receipts
and unchanged/kept receipts must be counted separately.

## Recover an interrupted run

Read the current durable state before issuing commands. On this workstation the
private checkpoint and session handoff are in `.local/qualification/`:

- `production-resume-checkpoint.json`
- `RESUME-PRODUCTION-SWEEP.md`

These files contain private identifiers and are deliberately ignored by Git.
Production databases and the installed extension's browser journal are the
sources of truth; the checkpoint is a dated snapshot.

If the private files are absent in a fresh checkout, use read-only SQLite
connections (`mode=ro`) on the production state to discover the latest production
`google.commit` and its hash-verified manifest. Identify production manifests by
`capabilities.productionRetention`, not simply the newest partial job: old download
or pilot jobs may also be partial. Read the paired owner's unknown worker jobs
from the worker database. Do not instantiate `WorkerStore` just to inspect state:
its constructor performs restart recovery. Do not change database flags manually.

1. Restore network access and open Chrome with the existing paired extension and
   signed-in Google Photos tab. **Worker status** shows the saved endpoint and
   pairing. If needed use **Reconnect worker**, preserving the pairing and journal.
2. Sign in to PhotoFlow in that same browser profile. Web sessions survive server
   restarts but have a 12-hour maximum lifetime. The web login and Google worker
   credentials have separate lifetimes.
3. If a worker job is `unknown` / `UNKNOWN_OUTCOME`, resolve it before any further
   writes. In **Operation workbench and qualification suite**, select **Reconcile
   unknown write**, enter the exact stopped worker job ID as
   `{"originalJobId":"<unknown-worker-job-id>"}`, then **Queue selected operation**.
   This reads the browser journal and current Google Trash state. It does not
   replay the write. Require a verified result and the original worker job's
   reconciled success receipt before continuing.
4. If positive exact Trash evidence cannot resolve that intent, stop and inspect
   the journal/current item. Do not erase the journal, clear an unknown database
   flag, use the preflight retry path, or blindly resend the removal.
5. If the reviewed manifest is still valid, select **Resume interrupted commit**
   on the exact production coordinator job. Its completed steps and stable worker
   intents are reused; completed writes are not issued again.

**Retry failed preflight** is a different path, limited to diagnosed PROTOCOL
failures before sending. It retains the same worker ID, archives the failure and
uses a new lease; the browser journal independently prevents write replay. It
cannot be used for a sent or unknown write.

## Expired manifest

Manifests have a 24-hour expiry. Do not edit their timestamps, canonical hashes,
worker deadlines or completed-step records to bypass it.

After resolving any unknown write, prepare a fresh full inventory and Takeout
Trash manifest using the fresh-sweep steps above. The library inventory excludes
items already in Google Trash. Re-check the new target list, review it and commit
only when the owner is ready to resume. Keep the old coordinator and all receipts
as history. A fresh plan can also retain photos whose protection or local evidence
has changed since the previous review.

## Execution and deployment

- Production is `https://photos.lbsa71.net`, hosted on `192.168.1.4`, separate from
  the Mac and localhost development app. Service: `photoflow-web`; checkout:
  `/home/stefan/file_deduplicator`; venv: `/opt/photoflow-web-venv`.
- Private state is `/var/lib/photoflow-web/google-workers/workers.sqlite` and
  `/var/lib/photoflow-web/google-reconciliation/operations.sqlite`. Immutable
  manifests are in the latter directory. The library is `/mnt/usb/PhotoLibrary`.
- Preserve the existing unpacked extension installation and Chrome profile. Do
  not use **Forget pairing** or remove browser data during outcome recovery.
- Keep the Mac awake, online and Chrome open for execution. A sleep inhibitor
  does not provide network connectivity or prevent every hardware sleep mode.
  The account's unresolved-write guard stops dependent removals after a loss.
- Transport idleness closes with reconnectable code 1001; invalid authentication
  or protocol data still closes with 1008. Peer disconnects do not trigger another
  close on an already disconnected socket. No transport recovery automatically
  resumes an unknown write.

For a new coding session, read this runbook, the private handoff/checkpoint and
`CONTRIBUTING.md`, inspect live state, and wait for the owner's request to resume.
