import {
  ProtocolError,
  UnknownOutcomeError,
  identifier,
  requireThat,
} from "./errors.js";
import {
  PROTOCOL_VERSION,
  decodeEnvelope,
  mutationRequest,
} from "./protocol.js";
const sha = (value) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
export function validateQualification(q, account, operation, now) {
  requireThat(
    q?.account === account &&
      q.protocolVersion === PROTOCOL_VERSION &&
      Array.isArray(q.operations) &&
      q.operations.includes(operation) &&
      Number.isFinite(q.expiresAt) &&
      q.expiresAt > now &&
      sha(q.evidenceSha256),
    "Operation has no current account-bound qualification",
    "UNQUALIFIED",
  );
}
function canonicalPlan(input) {
  const { id, account, type, target, revision, sha256, value } = input ?? {};
  identifier(id, "operation ID");
  identifier(account, "account");
  identifier(revision, "revision");
  requireThat(sha(sha256), "Invalid content hash", "INPUT");
  const plan = {
    id,
    account,
    type,
    target: {
      namespace: target?.namespace,
      mediaKey: target?.mediaKey,
      dedupKey: target?.dedupKey,
    },
    revision,
    sha256,
  };
  if (type === "favorite") plan.value = value;
  mutationRequest(plan, plan.target);
  Object.freeze(plan.target);
  return Object.freeze(plan);
}
function checkIdentity(observed, plan) {
  requireThat(
    observed?.account === plan.account &&
      observed.mediaKey === plan.target.mediaKey &&
      observed.dedupKey === plan.target.dedupKey &&
      observed.revision === plan.revision &&
      observed.sha256 === plan.sha256,
    "Target identity or content revision changed",
    "PRECONDITION",
  );
}
function desired(observed, plan) {
  return plan.type === "favorite"
    ? observed.favorite === plan.value
    : observed.trashed === (plan.type === "trash");
}
function preconditions(observed, plan) {
  checkIdentity(observed, plan);
  requireThat(
    observed.owned === true,
    "Ownership is not established",
    "PRECONDITION",
  );
  requireThat(
    typeof observed.trashed === "boolean",
    "Trash state is unknown",
    "PRECONDITION",
  );
  if (plan.type === "favorite")
    requireThat(
      !observed.trashed && typeof observed.favorite === "boolean",
      "Favorite state is unknown or item is trashed",
      "PRECONDITION",
    );
  if (plan.type === "trash")
    requireThat(
      observed.favorite === false &&
        observed.curatedAlbum === false &&
        [
          "localVerified",
          "backupVerified",
          "companionsVerified",
          "metadataVerified",
        ].every((k) => observed[k] === true),
      "Cloud retention or preservation preconditions failed",
      "PRECONDITION",
    );
}

export class MutationExecutor {
  #account;
  #transport;
  #journal;
  #inspect;
  #now;
  #qualification;
  #failed = false;
  constructor({
    account,
    transport,
    journal,
    inspect,
    now = Date.now,
    qualification,
  }) {
    this.#account = identifier(account, "account");
    this.#transport = transport;
    this.#journal = journal;
    this.#inspect = inspect;
    this.#now = now;
    this.#qualification = qualification;
    requireThat(
      typeof transport === "function" &&
        typeof inspect === "function" &&
        journal,
      "Executor ports are required",
      "INPUT",
    );
  }
  async execute(input) {
    const plan = canonicalPlan(input);
    requireThat(
      plan.account === this.#account,
      "Wrong execution account",
      "ACCOUNT",
    );
    validateQualification(
      this.#qualification,
      this.#account,
      plan.type,
      this.#now(),
    );
    requireThat(
      !this.#failed,
      "Executor disabled after uncertain write",
      "CIRCUIT_OPEN",
    );
    const release = await this.#journal.lock(this.#account);
    let sent = false;
    try {
      const existing = await this.#journal.get(plan.id);
      if (existing) {
        requireThat(
          equal(existing.plan, plan),
          "Operation ID reused for a different intent",
          "INTENT_CONFLICT",
        );
        if (existing.state === "verified" || existing.state === "unchanged")
          return existing;
      }
      requireThat(
        (await this.#journal.pending(this.#account)).length === 0,
        "Unresolved operations require reconciliation",
        "UNRESOLVED",
      );
      const before = await this.#inspect(plan);
      preconditions(before, plan);
      if (desired(before, plan)) {
        const done = { plan, state: "unchanged", at: this.#now() };
        await this.#journal.put(done);
        return done;
      }
      await this.#journal.put({ plan, state: "prepared", at: this.#now() });
      // Durable 'sent' before the call: a crash here is conservatively unresolved.
      await this.#journal.put({ plan, state: "sent", at: this.#now() });
      validateQualification(
        this.#qualification,
        this.#account,
        plan.type,
        this.#now(),
      );
      sent = true;
      const request = mutationRequest(plan, plan.target);
      const response = await this.#transport({
        ...request,
        account: this.#account,
        operation: plan.type,
        mode: "write",
      });
      requireThat(
        response?.account === this.#account && response.status === 200,
        "Invalid mutation response",
      );
      decodeEnvelope(response.body, request.rpc);
      const after = await this.#inspect(plan);
      checkIdentity(after, plan);
      requireThat(desired(after, plan), "Remote postcondition is not verified");
      const result = { plan, state: "verified", at: this.#now() };
      await this.#journal.put(result);
      return result;
    } catch (error) {
      if (sent) {
        this.#failed = true;
        try {
          await this.#journal.put({ plan, state: "unknown", at: this.#now() });
        } catch {
          /* Existing sent intent remains unresolved if storage fails. */
        }
        throw new UnknownOutcomeError();
      }
      throw error;
    } finally {
      await release();
    }
  }
  async reconcile(id) {
    identifier(id, "operation ID");
    const release = await this.#journal.lock(this.#account);
    try {
      const record = await this.#journal.get(id);
      requireThat(
        record?.plan?.account === this.#account,
        "No matching account intent",
        "ACCOUNT",
      );
      const plan = canonicalPlan(record.plan);
      validateQualification(
        this.#qualification,
        this.#account,
        plan.type,
        this.#now(),
      );
      const after = await this.#inspect(plan);
      checkIdentity(after, plan);
      requireThat(
        desired(after, plan),
        "Outcome remains unresolved; no mutation was sent",
        "UNRESOLVED",
      );
      const result = {
        plan,
        state: "verified",
        at: this.#now(),
        reconciled: true,
      };
      await this.#journal.put(result);
      return result;
    } finally {
      await release();
    }
  }
}

// In-memory reference adapter for tests and previews. Production writes need a
// durable journal (FileJournal or another implementation of the same port).
export class MemoryJournal {
  #records = new Map();
  #locked = new Set();
  async lock(account) {
    requireThat(
      !this.#locked.has(account),
      "Account already has a writer",
      "BUSY",
    );
    this.#locked.add(account);
    return async () => {
      this.#locked.delete(account);
    };
  }
  async get(id) {
    return structuredClone(this.#records.get(id) ?? null);
  }
  async put(record) {
    this.#records.set(record.plan.id, structuredClone(record));
  }
  async pending(account) {
    return [...this.#records.values()]
      .filter(
        (r) =>
          r.plan.account === account &&
          !["verified", "unchanged", "reconciled", "uploaded"].includes(
            r.state,
          ),
      )
      .map((r) => structuredClone(r));
  }
  async findUpload(account, sha256) {
    return structuredClone(
      [...this.#records.values()].find(
        (r) =>
          r.plan.account === account &&
          r.plan.sha256 === sha256 &&
          r.state === "uploaded",
      ) ?? null,
    );
  }
}
