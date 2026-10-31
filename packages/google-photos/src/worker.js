import { identifier, requireThat } from "./errors.js";
import { JOBS, JOB_PROTOCOL_VERSION, capabilities } from "./jobs.js";
import { JobDiagnostics } from "./job-diagnostics.js";
const codes = new Set([
  "ACCOUNT",
  "SESSION",
  "PROTOCOL",
  "TRANSPORT",
  "HTTP",
  "SIZE",
  "TIMEOUT",
  "CIRCUIT_OPEN",
  "INPUT",
  "UNQUALIFIED",
  "PRECONDITION",
  "UNRESOLVED",
  "UNKNOWN_OUTCOME",
  "BUSY",
  "INTENT_CONFLICT",
]);
export class DesktopWorker {
  constructor({
    account,
    token,
    origin,
    connect = (url) => new WebSocket(url),
    runInventory,
    getAccount,
    saveReceipt,
    setInterval = globalThis.setInterval.bind(globalThis),
    clearInterval = globalThis.clearInterval.bind(globalThis),
    onClose = () => {},
    handlers,
    saveDiagnostics = async () => {},
  }) {
    this.account = identifier(account);
    this.token = identifier(token);
    const base = new URL(origin);
    requireThat(
      base.protocol === "https:" &&
        !base.username &&
        !base.password &&
        base.pathname === "/" &&
        !base.search &&
        !base.hash,
      "Invalid worker origin",
      "INPUT",
    );
    this.url = `wss://${base.host}/api/v1/google/worker`;
    Object.assign(this, {
      connect,
      runInventory,
      getAccount,
      saveReceipt,
      setInterval,
      clearInterval,
      onClose,
      saveDiagnostics,
    });
    this.handlers = handlers ?? { "inventory-counts": runInventory };
    this.seen = new Map();
    this.ready = false;
    this.lastJobFailed = false;
    this.authenticated = false;
    this.stopped = false;
  }
  start() {
    requireThat(!this.socket, "Worker already started", "INPUT");
    const socket = (this.socket = this.connect(this.url));
    let chain = Promise.resolve();
    socket.addEventListener("open", () =>
      this.send({
        type: "auth",
        token: this.token,
        account: this.account,
        protocol: JOB_PROTOCOL_VERSION,
        capabilities: capabilities().filter(
          (item) => typeof this.handlers[item.operation] === "function",
        ),
      }),
    );
    socket.addEventListener("message", (event) => {
      chain = chain
        .then(() => {
          requireThat(
            typeof event.data === "string" && event.data.length <= 16384,
            "Invalid worker message",
          );
          return this.receive(JSON.parse(event.data));
        })
        .catch(() => this.stop(1008));
    });
    socket.addEventListener("close", (event) => {
      this.authenticated = false;
      this.stopped = true;
      this.clearInterval(this.timer);
      this.onClose(event);
    });
    return this;
  }
  send(value) {
    if (!this.stopped && this.socket?.readyState === 1) {
      const encoded = JSON.stringify(value);
      requireThat(
        new TextEncoder().encode(encoded).length <= 256 * 1024,
        "Worker result exceeds limit",
        "SIZE",
      );
      this.socket.send(encoded);
    }
  }
  async receive(message) {
    requireThat(message && typeof message === "object", "Invalid job");
    if (message.type === "welcome") {
      requireThat(
        !this.authenticated &&
          message.account === this.account &&
          message.protocol === JOB_PROTOCOL_VERSION,
        "Wrong worker account",
        "ACCOUNT",
      );
      this.authenticated = true;
      await this.heartbeat();
      this.timer = this.setInterval(() => void this.heartbeat(), 20000);
      return;
    }
    requireThat(this.authenticated, "Worker not authenticated", "ACCOUNT");
    if (message.type === "heartbeat" || message.type === "receipt") return;
    requireThat(
      message.type === "job" &&
        Object.hasOwn(JOBS, message.operation) &&
        JOBS[message.operation]?.version === message.version &&
        typeof this.handlers[message.operation] === "function" &&
        message.account === this.account,
      "Unsupported worker job",
      "ACCOUNT",
    );
    JOBS[message.operation].validateInput(message.input);
    identifier(message.id);
    identifier(message.lease);
    const key = message.id + ":" + message.lease;
    if (this.seen.has(key)) {
      this.send(this.seen.get(key));
      return;
    }
    requireThat(
      this.seen.size < 100,
      "Reconnect to bound worker history",
      "SIZE",
    );
    const diagnostics = new JobDiagnostics(message);
    const phase = async (value) => {
      diagnostics.phase(value);
      await this.saveDiagnostics(diagnostics.snapshot());
      this.send({
        type: "progress",
        id: message.id,
        lease: message.lease,
        phase: value,
      });
    };
    let result;
    try {
      await phase("checking");
      requireThat(
        (await this.getAccount()) === this.account,
        "Google account changed",
        "ACCOUNT",
      );
      result = await this.handlers[message.operation](this.account, {
        phase,
        recordRead: (request, response) => diagnostics.read(request, response),
        isActive: () => this.authenticated && !this.stopped,
        job: message,
      });
      await phase("verifying");
      requireThat(
        (await this.getAccount()) === this.account,
        "Google account changed",
        "ACCOUNT",
      );

      JOBS[message.operation].validateResult(result);
      requireThat(
        new TextEncoder().encode(JSON.stringify(result)).length <= 240 * 1024,
        "Worker result exceeds limit",
        "SIZE",
      );
      await phase("complete");
      this.ready = true;
      this.lastJobFailed = false;
      result = { type: "result", id: message.id, lease: message.lease, result };
    } catch (error) {
      diagnostics.failure(error);
      this.ready = false;
      this.lastJobFailed = true;
      await phase("failed");
      result = {
        type: "result",
        id: message.id,
        lease: message.lease,
        error: codes.has(error?.code) ? error.code : "PROTOCOL",
      };
    }
    await this.saveDiagnostics(diagnostics.snapshot());
    await this.saveReceipt(result);
    this.seen.set(key, result);
    this.send(result);
  }
  async heartbeat() {
    try {
      this.ready =
        !this.lastJobFailed && (await this.getAccount()) === this.account;
    } catch {
      this.ready = false;
    }
    this.send({ type: "heartbeat", account: this.account, ready: this.ready });
  }
  stop(code = 1000) {
    this.stopped = true;
    this.authenticated = false;
    this.clearInterval(this.timer);
    this.socket?.close(code);
  }
}
