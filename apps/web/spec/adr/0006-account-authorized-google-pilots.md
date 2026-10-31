# ADR 0006: Account-authorized Google mutation pilots

Status: Accepted — 2026-10-31. Supersedes ADR 0005's isolated-account-only rule.

## Authorization and rationale

The library owner reports a recent full personal Google Photos Takeout backup and
explicitly authorizes changing the policy to permit controlled pilots on that
personal account. A separate Google account is therefore optional. This is an
owner decision, not an inference that any account with a backup is safe to change.
Automated tests continue to use synthetic data and intercepted Google responses.

Takeout provides exported media and metadata, not a tested transactional rollback
of Google's account state. Metadata changes, album relationships, comments and
sharing links may not be reconstructed identically by reimporting files. Google
also notes that exports can omit changes during archive creation:
https://support.google.com/photos/answer/3024190

Undocumented API changes may produce unexpected effects. Throttling or sign-in
challenges are possible operational risks; no promise is made about Google's
future treatment of unofficial automation. Backups do not protect credentials,
restore provider access, or prove a protocol call correct. We accept a bounded
personal-account pilot while retaining account, protocol and target validation.

## Configuration and boundaries

Use extension 0.3.1 or later, with job protocol 2. Configure the exact account
identifier reported by the extension, not an inferred email or the Linux username:

```ini
# sudo systemctl edit photoflow-web
[Service]
Environment="PHOTOFLOW_GOOGLE_PILOT_ACCOUNT=<paired account identifier>"
Environment="PHOTOFLOW_GOOGLE_PILOT_TARGET_POLICY=selected"
```

Restart the service after changes. Remove the account setting to disable writes.
`PHOTOFLOW_GOOGLE_TEST_ACCOUNT` remains a legacy account-setting alias; the new
setting takes precedence. Default target policy is `fixtures`; unknown policies
fail startup. An unconfigured or different paired account remains read-only.
Only administrators may submit jobs, and each write submission still requires
explicit confirmation. The confirmation authorizes a finite, inspectable plan.

| Policy | Photo targets | Album membership targets |
| --- | --- | --- |
| fixtures (default) | Supported images named photoflow-test-…, at most 10 MiB | Private albums named PhotoFlow test … |
| selected (explicit opt-in) | Supported images at explicit photo URLs, including personal filenames and sizes | Explicit private album IDs, regardless of title |

Both policies reject video targets and unknown identities. Shared albums remain
excluded from membership pilots. Newly created pilot albums still require the
`PhotoFlow test ` prefix. There is no permanent-delete capability, collection-wide
mutation target, Takeout automation, or new upload/download transfer implementation.
Production automatic retention/cleanup remains separately gated.

The server snapshots target policy with every queued intent and includes it in
its short-lived account/job/operation/target-bound scope. A configuration change
blocks previously queued writes whose policy no longer matches; it cannot silently
broaden their scope. The extension freezes and journals that policy with the exact
inputs. Missing policy in old scopes/receipts means fixtures, never selected.
The existing `testScope`/`testOnly` wire names denote qualification-only authority;
they no longer assert that the Google account itself is disposable.

## Execution and recovery remain strict

One write is in flight per account. Validate exact IDs and account identity,
complete required reads, persist intent, send once, validate the response and
verify the postcondition. Lost acknowledgements or uncertain postconditions remain
unknown and block subsequent writes until read-only reconciliation succeeds.
Changing accounts or re-pairing cannot erase that uncertainty. A policy/target
change under an existing intent ID is rejected. Cookies and session values stay
in the browser; logs and public fixtures must not expose personal identifiers.

The workbench defaults optional metadata inputs to `{}`. Prepared pilot suites
show every job before queueing. They set favorite/archive off at the end, clear
description, remove membership from the selected album and restore from Trash.
They do not restore the photo's initial state. Optional timestamp changes persist;
optional location tests clear the manual location. Created albums remain. Prefer
an expendable selected photo for the combined suite, or run individual operations
with deliberate desired values on valuable photos.

This policy change does not execute a Google mutation or qualify an operation live.
Record live results by operation, including failures and unknown outcomes, before
using the production retention executor.
