# Google Photos sync: repeatable retention passes

Keep starred photos, every album member, and anything without a verified local
original. Ambiguous matches and motion photos without paired local proof also
stay in Google. Originals arrive through periodic manual Takeouts; the owner has
accepted the independent Takeout backup without requiring its verification.
Sync moves eligible Google copies to Trash; it never permanently deletes them.

## Everyday use

1. Open PhotoFlow and a signed-in Google Photos tab in the same Chrome profile.
   Open the Google Photos connection panel. If needed, enter the Google account
   and choose **Connect Google Photos** using the existing extension.
2. Choose **Prepare sync** (or **Prepare fresh pass** after an interruption).
   PhotoFlow reads the entire current library, favorites and album memberships,
   then checks local original bytes and preserved Takeout provenance automatically.
   Preparation does not change Google photos.
3. Review **Keep in Google Photos** and **Move to Google Trash** counts. Choose
   **Move … photos to Trash** to authorize exactly that review. Keep the Mac awake,
   online, with Chrome and the signed-in Google Photos tab open.
4. Watch progress in the same panel. **Pause sync** stops subsequent removals;
   the photo currently in flight may finish. Manual jobs, diagnostics and the old
   step-by-step workbench are below the divider in **Advanced & troubleshooting**.

## Eventual consistency and interruptions

A pass observes current state and makes Trash the final per-photo operation.
Local originals and Takeout provenance are rechecked before dispatch; Google
identity, stars and album membership are freshly checked immediately before
Trash. Newly protected items are retained. Only positive Trash verification is
counted as a verified removal.

If a request or acknowledgement is interrupted, the pass stops. Choose
**Prepare fresh pass** when ready. This performs a new complete inventory and
builds a new finite review; it does not replay an old worker job. A photo already
in Trash is absent from the library inventory. A photo still present is evaluated
again against current protection and local evidence. No job IDs, negative Trash
proofs, or per-write repair are required for routine retention sync.

Historical unknown retention outcomes and browser journals remain intact for
audit; they do not freeze future reviewed retention passes. Generic pilot writes
retain their stricter unknown-outcome guards. There is one active browser writer;
its live lock is never bypassed. A restarted retention writer may replace its
abandoned persisted lock after checking that unresolved records are retention
intents, while preserving every record. The same unknown intent is never replayed.

Reviews expire after 24 hours. Prepare a new review instead of editing timestamps,
hashes or deadlines. Existing production plans migrate to paused; deployment does
not resume them. The owner requested that tonight's sweep start as a fresh pass.

## Deployment and troubleshooting

- Production: `https://photos.lbsa71.net`, separate host `192.168.1.4`, service
  `photoflow-web`, checkout `/home/stefan/file_deduplicator`, venv
  `/opt/photoflow-web-venv`, library `/mnt/usb/PhotoLibrary`.
- Durable state: `/var/lib/photoflow-web/google-workers/workers.sqlite` and
  `/var/lib/photoflow-web/google-reconciliation/operations.sqlite`; immutable
  manifests are beside the latter. Inspect SQLite using `mode=ro`; do not change
  unknown flags or instantiate WorkerStore merely to inspect it.
- Preserve the existing extension installation, pairing and Chrome local storage.
  Reload the updated unpacked extension; do not reinstall or choose Forget pairing.
- Web sessions survive service restarts but expire after 12 hours. Web login and
  extension pairing are separate. Reconnect the worker if needed; reconnecting
  alone never starts or resumes removals.
- Technical diagnostics and legacy reconciliation remain in Advanced. They are
  unnecessary to start a new normal retention pass. Do not resume an expired old
  coordinator or claim its unknown result as verified success.
- Private historical checkpoint and handoff live in `.local/qualification/` on
  the development Mac. They are dated snapshots; inspect live state when needed.

No production sweep is started by deployment or qualification. Start tonight's
fresh pass through the ordinary UI when the owner is ready.
