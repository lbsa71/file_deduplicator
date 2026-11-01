# Eventual-consistency retention sync qualification

The normal flow is Connect → Prepare sync → review keep/Trash totals → Move the
reviewed photos to Trash. Inventory and local Takeout proof preparation are one
durable read-only workflow. Advanced manual jobs live below a divider.

Qualification uses a disposable HTTPS/WSS application, the actual built extension,
and intercepted synthetic Google responses. No real Google traffic or production
removal is part of this qualification.

Covered behavior:

- A lost Trash response stops that pass and preserves the unknown audit record.
- A fresh complete inventory excludes an already-trashed photo; no second removal
  is issued, and no per-write repair or job-ID entry is needed.
- A still-present photo is reviewed again and can be processed by a new scoped
  pass despite an older unknown retention receipt.
- Fresh stars, album membership and known motion companions retain the item.
- Missing, corrupt, stale or unproved local bytes do not authorize Trash. Missing
  local records do not prevent read-only inventory from producing a keep review.
- Same-intent replay, a live writer, unresolved generic pilot writes, wrong scope,
  changed identities and incomplete reads remain blocked.
- Pause is durable; old production plans migrate to paused. New approval is bound
  to the exact current manifest hash, and only one production pass may run.
- Keep totals include every non-executable remote candidate. Actual verified Trash
  and newly kept receipts are reported separately.
- Desktop and 390px mobile normal views were visually inspected.

Validation commands:

```
PYTHONPATH=apps/web:apps/photoflow .venv/bin/python -m unittest discover -s apps/web/tests
npm test --prefix apps/web/ui
npm test --prefix packages/google-photos
npm run check:contracts --prefix packages/google-photos
PHOTOFLOW_TEST_PYTHON="$PWD/.venv/bin/python" PHOTOFLOW_TEST_PILOT_POLICY=selected npm run test:worker --prefix packages/google-photos
```

The focused normal-user scenario can also run with `PHOTOFLOW_TEST_SYNC_ONLY=1`.
Private test logs and screenshots are in `.local/qualification/` and `/tmp/` on the
development Mac, deliberately excluded from Git. Version 0.4.1 updates the same
extension installation and preserves protocol 2, pairing and browser journals.

Production remains paused. Tonight's pass must start with a fresh review through
the normal panel. The old partial coordinator and receipts remain history.
