# Contributing to PhotoFlow

Keep the service compact, inspectable, and safe to rerun. Originals and portable
sidecars are authoritative; indexes and caches must remain rebuildable.

## Development and verification

Use strict TDD for behavior changes: write a failing behavioral test, implement
the smallest coherent change, then refactor with the tests passing. Inject
filesystem, clock, identifiers, network transport, and external tools at their
boundaries. Test deterministic domain logic directly. Automated tests use synthetic media
and isolated accounts/libraries. Live mutation qualification defaults to disposable
fixtures. An owner may explicitly authorize a finite, exact-target pilot on their
backed-up personal account after accepting the risks; record that authorization
and configure the account and selected-target policy explicitly. A backup alone
never grants permission, and this exception does not enable unattended cleanup.

From the repository root:

```sh
make test
make test-web PYTHON=/path/to/python-with-web-dependencies
make build-web
```

See each application's README for dependency installation and adapter/browser
checks. Run checks appropriate to the change; documentation-only changes need
link and diff checks, not a full media-processing run. Explain what changed,
what was verified, and any remaining limitations.

## External integrations must fail closed

This is a project requirement, including for Google Photos and any third-party
client library. Do not make optimistic calls: do not guess identifiers, request
formats, unsupported operations, or missing facts, and do not continue dependent
writes after an error or an unverified result. A library returning without an
exception is not proof of success.

- **Validate before sending.** Allowlist operations and endpoints. Validate
  account/library identity, identifier namespaces, exact targets, input types,
  capabilities, and current preconditions. Keep decisions separate from the
  adapter that executes them. Never fall back from explicit targets to an entire
  collection or from a failed narrow operation to a broader one.
- **Validate what comes back.** Check transport status, RPC identity, framing,
  required fields, types, per-item status, and correspondence to the requested
  targets. Runtime schemas are required at untrusted boundaries; static types
  or casts alone do not validate a response. Ignore unknown additional fields
  only when they cannot affect the decision; reject incompatible structure.
- **Unknown is not false, empty, or absent.** Missing favorite/album/match fields,
  malformed JSON, failed lookups, and authorization failures must not become
  `false`, `[]`, or "not found". Optional-field absence has meaning only under
  an explicitly tested protocol contract. In uncertainty, preserve content and
  stop the affected plan.
- **Prove enumeration completeness.** Validate each page and continuation token,
  detect cursor loops, and distinguish a valid terminal page from a malformed
  response. Failed or cancelled pagination must return an explicit incomplete
  result or raise; never pass a partial list off as a complete inventory. No
  retention/removal decision may rely on incomplete favorites or album data.
- **Classify retries by operation.** Schema, identity, and capability failures
  stop immediately. Reads may retry documented transient errors with bounded
  backoff and timeouts. Mutations must not inherit a generic retry loop. A lost
  response after sending a write means an unknown outcome; persist that state
  and reconcile before any retry. Repeated writes require a proved idempotency
  contract or verified evidence that the original write did not happen.
- **Journal and verify mutations.** Persist intent before sending a write,
  including account, target identity/content revision, operation, and decision
  inputs. Bind execution to a finite plan and revalidate its preconditions.
  Check the resulting remote state before recording completion. An ambiguous or
  partial result stops further mutations in that plan and remains recoverable;
  never claim a whole batch succeeded because its HTTP request succeeded.
- **Limit failure propagation.** Start destructive integrations with one target
  in flight, reversible trash operations, and no permanent-delete capability.
  A protocol failure disables dependent mutations until the cause is diagnosed
  and the adapter is requalified. An error can occur after a remote side effect;
  postcondition checks cannot undo that fact or guarantee provider correctness.
- **Pin and isolate dependencies.** Record the reviewed version/commit and retain
  required upstream attribution when adapting code. Do not load auto-updating
  third-party mutation clients into production. Keep undocumented protocols in
  a small replaceable adapter; keep credentials out of logs, fixtures, sidecars,
  and the repository.

Tests must cover malformed and misleading successful responses, wrong RPC/account
or target IDs, unknown flags, incomplete pages, expired sessions, partial writes,
lost acknowledgements, and changed inputs between planning and execution. Assert
that prohibited follow-up calls were never sent, not merely that an error was
logged. Verify a new adapter against controlled fixtures and a disposable live
test set, or an explicitly owner-authorized personal-account pilot, before enabling
that operation in production. Keep live qualification distinct from synthetic tests.

## Preservation and provenance

Preserve original bytes and source documents. Keep human decisions, imported
observations, and current external state distinct. A filename or perceptual
match is not proof that two originals are interchangeable. Missing or corrupt
metadata is not evidence that a remote photo does not exist. Do not infer
deletion permission from a normal ingestion run or from a failed backup lookup.

Cloud upload and cleanup proposals are described in
[ADR 0003](apps/web/spec/adr/0003-google-photos-reconciliation.md). The standalone
library/capture package and initial read-only WSS worker are implemented. Live
count enumeration is qualified; other operations and production cloud mutations
remain gated. Follow [ADR 0004](apps/web/spec/adr/0004-desktop-google-worker.md)
when adding job types and collecting diagnostic evidence.

Typed job contracts and qualification suites follow
[ADR 0005](apps/web/spec/adr/0005-google-job-qualification.md).
[ADR 0006](apps/web/spec/adr/0006-account-authorized-google-pilots.md) records the
owner-authorized personal-account policy. An enabled pilot is never a substitute
for separately qualifying production mutations; journaling, exact targets,
postcondition checks and unknown-outcome stops remain mandatory.
