import { CaptureSanitizer, sanitizeReadEvidence } from "./capture.js";
import { JOBS, JOB_PROTOCOL_VERSION } from "./jobs.js";
import { requireThat } from "./errors.js";
export class JobDiagnostics {
  constructor(job, now = Date.now) {
    requireThat(JOBS[job.operation], "Unknown diagnostic job");
    this.job = {
      id: job.id,
      operation: job.operation,
      version: JOBS[job.operation].version,
      attempt: Number.isSafeInteger(job.attempt) ? job.attempt : 0,
    };
    this.now = now;
    this.events = [];
    this.entries = [];
    this.bytes = 0;
    this.limited = false;
    this.sanitizer = new CaptureSanitizer();
  }
  phase(phase) {
    requireThat(
      JOBS[this.job.operation].phases.includes(phase),
      "Unknown job phase",
    );
    if (this.events.length === 32) {
      this.events.shift();
      this.limited = true;
    }
    this.events.push({ phase, at: this.now() });
  }
  read(request, response) {
    this.lastRaw = { request, response };
    try {
      const entry = {
        rpc: request.rpc,
        input: this.sanitizer.value(request.data),
        response: this.sanitizer.response(
          {
            status: Number.isInteger(response?.status) ? response.status : 0,
            mimeType: "application/json",
            headers: {},
          },
          response?.body,
        ),
      };
      let bytes = new TextEncoder().encode(JSON.stringify(entry)).length;
      if (bytes > 512 * 1024) {
        entry.input = [];
        entry.response = { status: entry.response.status, bodyOmitted: true };
        bytes = new TextEncoder().encode(JSON.stringify(entry)).length;
        this.limited = true;
      }
      while (
        this.entries.length &&
        (this.entries.length >= 8 || this.bytes + bytes > 512 * 1024)
      ) {
        this.bytes -= new TextEncoder().encode(
          JSON.stringify(this.entries.shift()),
        ).length;
        this.limited = true;
      }
      this.bytes += bytes;
      this.entries.push(entry);
      if (entry.response.bodyOmitted || entry.response.parseError)
        this.limited = true;
    } catch {
      this.limited = true;
    }
  }
  failure(error) {
    const safe = sanitizeReadEvidence(
      this.lastRaw?.request,
      this.lastRaw?.response,
      error,
    );
    this.failureInfo = {
      code: [
        "ACCOUNT",
        "SESSION",
        "PROTOCOL",
        "TRANSPORT",
        "HTTP",
        "SIZE",
        "TIMEOUT",
        "CIRCUIT_OPEN",
        "INPUT",
      ].includes(error?.code)
        ? error.code
        : "PROTOCOL",
      ...(safe.rule ? { rule: safe.rule } : {}),
      ...(safe.framing ? { framing: safe.framing } : {}),
      ...(safe.envelopeRecords
        ? { envelopeRecords: safe.envelopeRecords }
        : {}),
    };
  }
  snapshot() {
    return {
      schemaVersion: 1,
      protocol: JOB_PROTOCOL_VERSION,
      kind: "google-photos-worker-diagnostics",
      job: this.job,
      events: [...this.events],
      entries: [...this.entries],
      limited: this.limited,
      retentionReady: false,
      ...(this.failureInfo ? { failure: this.failureInfo } : {}),
    };
  }
}
