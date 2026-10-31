const MAX_BODY = 1024 * 1024;
const SAFE_NETWORK_ERRORS = new Set([
  "net::ERR_ABORTED",
  "net::ERR_FAILED",
  "net::ERR_TIMED_OUT",
  "net::ERR_BLOCKED_BY_CLIENT",
]);
const SAFE_HEADERS = new Set([
  "content-type",
  "content-length",
  "x-goog-upload-command",
  "x-goog-upload-offset",
  "x-goog-upload-protocol",
  "x-goog-upload-status",
  "x-goog-upload-chunk-granularity",
  "x-goog-upload-size-received",
]);
const ALLOWED_HOSTS = new Set([
  "photos.google.com",
  "photoslibrary.googleapis.com",
  "photosdata-pa.googleapis.com",
  "upload.google.com",
  "upload.video.google.com",
  "clients6.google.com",
]);
const SAFE_WORDS = new Set(["wrb.fr", "generic", "di", "af.httprm"]);
const rpcPattern = /^[A-Za-z0-9]{4,12}$/;
export class CaptureSanitizer {
  #names = new Map();
  #rpcs = new Set();
  #tokenBytes = 0;
  alias(value) {
    if (!this.#names.has(value)) {
      if (
        value.length > 4096 ||
        this.#tokenBytes + value.length > 4 * 1024 * 1024 ||
        this.#names.size >= 50000
      )
        throw new Error("Capture alias budget exceeded");
      this.#tokenBytes += value.length;
      this.#names.set(value, `opaque-${this.#names.size + 1}`);
    }
    return this.#names.get(value);
  }
  value(value, depth = 0) {
    if (depth > 60) throw new Error("Capture nesting limit");
    if (typeof value === "string")
      return value === "" || SAFE_WORDS.has(value) || this.#rpcs.has(value)
        ? value
        : this.alias(value);
    if (value === null || typeof value === "boolean") return value;
    // Preserve small protocol enums; remove coordinates, dimensions and times.
    if (typeof value === "number")
      return Number.isInteger(value) && value >= 0 && value <= 32
        ? value
        : 1000;
    if (Array.isArray(value)) return value.map((v) => this.value(v, depth + 1));
    if (value && typeof value === "object")
      return Object.fromEntries(
        Object.entries(value).map(([k, v]) => [
          /^\d+$/.test(k) ? k : this.alias(k),
          this.value(v, depth + 1),
        ]),
      );
    return null;
  }
  headers(headers = {}) {
    return Object.fromEntries(
      Object.entries(headers)
        .filter(([k]) => SAFE_HEADERS.has(k.toLowerCase()))
        .map(([k, v]) => [k.toLowerCase(), String(v).slice(0, 200)]),
    );
  }
  request(request) {
    const url = new URL(request.url);
    const rpcs = (url.searchParams.get("rpcids") ?? "")
      .split(",")
      .filter((s) => rpcPattern.test(s));
    rpcs.forEach((v) => this.#rpcs.add(v));
    const pathname = url.pathname
      .split("/")
      .map((v) =>
        [
          "",
          "_",
          "PhotosUi",
          "data",
          "batchexecute",
          "upload",
          "uploads",
          "v1",
          "mediaItems:batchCreate",
          "u",
          "0",
          "1",
          "2",
        ].includes(v)
          ? v
          : this.alias(v),
      )
      .join("/");
    const result = {
      host: url.hostname,
      path: pathname,
      queryKeys: [...new Set([...url.searchParams.keys()])].filter(
        (k) => !["at", "f.sid", "rapt"].includes(k),
      ),
      method: request.method,
      headers: this.headers(request.headers),
      rpcIds: rpcs,
      bodyOmitted: true,
    };
    if (
      typeof request.postData === "string" &&
      request.postData.length <= MAX_BODY &&
      url.pathname.endsWith("/batchexecute")
    ) {
      try {
        const wrapped = JSON.parse(
          new URLSearchParams(request.postData).get("f.req"),
        );
        if (!Array.isArray(wrapped?.[0])) throw new Error();
        result.rpcRequests = wrapped[0].map((row) => {
          if (!rpcPattern.test(row[0]) || typeof row[1] !== "string")
            throw new Error();
          this.#rpcs.add(row[0]);
          return { rpc: row[0], data: this.value(JSON.parse(row[1])) };
        });
        result.bodyOmitted = false;
      } catch {
        result.parseError = true;
      }
    }
    return result;
  }
  response(response, body) {
    const result = {
      status: response.status,
      mimeType: response.mimeType,
      headers: this.headers(response.headers),
      bodyOmitted: true,
    };
    if (
      typeof body !== "string" ||
      body.length > MAX_BODY ||
      !/(json|javascript|text\/plain)/i.test(response.mimeType ?? "")
    )
      return result;
    try {
      const lines = body
        .replace(/^\)\]\}'(?:\r?\n)?/, "")
        .split(/\r?\n/)
        .filter((s) => s.trim() && !/^\d+$/.test(s.trim()));
      const responses = [];
      for (const line of lines) {
        const json = JSON.parse(line);
        if (
          Array.isArray(json) &&
          json.some((v) => Array.isArray(v) && v[0] === "wrb.fr")
        ) {
          for (const row of json)
            if (row[0] === "wrb.fr") {
              if (!rpcPattern.test(row[1]) || typeof row[2] !== "string")
                throw new Error();
              this.#rpcs.add(row[1]);
              responses.push({
                rpc: row[1],
                data: this.value(JSON.parse(row[2])),
              });
            }
        } else if (response.mimeType.includes("json"))
          result.json = this.value(json);
        else throw new Error();
      }
      if (responses.length) result.rpcResponses = responses;
      if (responses.length || Object.hasOwn(result, "json"))
        result.bodyOmitted = false;
    } catch {
      result.parseError = true;
      delete result.json;
      delete result.rpcResponses;
    }
    return result;
  }
}

const READ_RULES = new Map([
  ["Invalid response size", "RESPONSE_SIZE"],
  ["Invalid RPC frame length", "RPC_FRAME_LENGTH"],
  ["Invalid RPC JSON", "RPC_JSON"],
  ["Invalid RPC envelope", "RPC_ENVELOPE"],
  ["Invalid RPC record", "RPC_RECORD"],
  ["Unexpected RPC identity or error", "RPC_IDENTITY"],
  ["Missing RPC payload", "RPC_PAYLOAD"],
  ["Invalid RPC payload JSON", "RPC_PAYLOAD_JSON"],
  ["Missing RPC payload structure", "RPC_PAYLOAD_STRUCTURE"],
  ["Expected exactly one RPC response", "RPC_RESPONSE_COUNT"],
  ["Invalid page items", "PAGE_ITEMS"],
  ["Invalid continuation token", "PAGE_CURSOR"],
  ["Invalid favorite", "FAVORITE_FLAG"],
  ["Invalid trash timestamp", "TRASH_TIMESTAMP"],
  ["Ambiguous media extension fields", "MEDIA_EXTENSIONS"],
  ["Invalid album fields", "ALBUM_FIELDS"],
  ["Invalid album count", "ALBUM_COUNT"],
  ["Invalid shared flag", "ALBUM_SHARED_FLAG"],
]);

// Evidence from an explicit read's returned value, separate from passive Network
// events. It can diagnose a rejected response, never prove a complete inventory.
export function sanitizeReadEvidence(request, response, error) {
  const evidence = { kind: "google-photos-read-failure", complete: false };
  const rule = READ_RULES.get(error?.message);
  if (rule) evidence.rule = rule;
  const body = response?.body;
  evidence.response = { bodyOmitted: true };
  if (Number.isInteger(response?.status))
    evidence.response.status = response.status;
  if (
    typeof body !== "string" ||
    new TextEncoder().encode(body).length > MAX_BODY
  )
    return evidence;
  const sanitizer = new CaptureSanitizer();
  evidence.response = sanitizer.response(
    { status: response.status, mimeType: "application/json" },
    body,
  );
  if (rpcPattern.test(request?.rpc) && Array.isArray(request?.data))
    evidence.request = {
      rpc: request.rpc,
      data: sanitizer.value(request.data),
    };
  const lines = body
    .replace(/^\)\]\}'(?:\r?\n)?/, "")
    .split(/\r?\n/)
    .filter((line) => line.trim());
  evidence.framing = {
    xssiPrefix: body.startsWith(")]}'"),
    totalBytes: new TextEncoder().encode(body).length,
    lines: lines.slice(0, 16).map((line, index) => ({
      utf8Bytes: new TextEncoder().encode(line).length,
      utf16Units: line.length,
      ...(body.startsWith(")]}'") &&
      /^\d{1,8}$/.test(line.trim()) &&
      Number(line.trim()) <= MAX_BODY + 1 &&
      lines[index + 1]?.trim().startsWith("[")
        ? { declaredLength: Number(line.trim()) }
        : {}),
    })),
    omittedLines: Math.max(0, lines.length - 16),
  };
  if (new TextEncoder().encode(JSON.stringify(evidence)).length > MAX_BODY)
    return {
      kind: evidence.kind,
      complete: false,
      ...(rule ? { rule } : {}),
      response: { bodyOmitted: true },
    };
  return evidence;
}

// Uses only passive CDP Network notifications and getResponseBody. Never
// intercepts, modifies, replays, or sends page requests.
export class PassiveRecorder {
  #send;
  #now;
  #sanitizer = new CaptureSanitizer();
  #pending = new Map();
  #entries = [];
  #complete = true;
  #maxEntries;
  #maxBytes;
  #bytes = 0;
  #reading = 0;
  #saturated = false;
  constructor({
    send,
    now = Date.now,
    maxEntries = 1000,
    maxBytes = 8 * 1024 * 1024,
  }) {
    this.#send = send;
    this.#now = now;
    this.#maxEntries = maxEntries;
    this.#maxBytes = maxBytes;
  }
  invalidate() {
    this.#complete = false;
  }
  #append(entry) {
    const size = JSON.stringify(entry).length;
    if (this.#bytes + size > this.#maxBytes) {
      this.#complete = false;
      this.#saturated = true;
      return;
    }
    this.#bytes += size;
    this.#entries.push(entry);
  }
  async event(method, params) {
    const id = params.requestId;
    if (method === "Network.requestWillBeSent") {
      let url;
      try {
        url = new URL(params.request.url);
      } catch {
        return;
      }
      if (
        url.protocol !== "https:" ||
        !ALLOWED_HOSTS.has(url.hostname) ||
        !["XHR", "Fetch", "Other"].includes(params.type)
      )
        return;
      if (
        this.#saturated ||
        this.#entries.length + this.#pending.size + this.#reading >=
          this.#maxEntries ||
        this.#bytes >= this.#maxBytes
      ) {
        this.#complete = false;
        return;
      }
      if (this.#pending.has(id)) {
        this.#complete = false;
        this.#pending.delete(id);
      }
      const capturedRequest = this.#sanitizer.request(params.request);
      if (
        url.pathname.endsWith("/batchexecute") &&
        capturedRequest.bodyOmitted
      ) {
        capturedRequest.captureError =
          "RPC request body unavailable or invalid";
        this.#complete = false;
      }
      this.#pending.set(id, { at: this.#now(), request: capturedRequest });
      return;
    }
    const entry = this.#pending.get(id);
    if (!entry) return;
    if (method === "Network.responseReceived") {
      entry.response = this.#sanitizer.response(params.response);
      return;
    }
    if (method === "Network.loadingFailed") {
      entry.failed = true;
      if (SAFE_NETWORK_ERRORS.has(params.errorText))
        entry.networkError = params.errorText;
      if (typeof params.canceled === "boolean")
        entry.canceled = params.canceled;
      this.#complete = false;
      this.#pending.delete(id);
      this.#append(entry);
      return;
    }
    if (method !== "Network.loadingFinished") return;
    this.#pending.delete(id);
    if (!entry.response) this.#complete = false;
    this.#reading++;
    if (
      entry.response &&
      /(json|javascript|text\/plain)/i.test(entry.response.mimeType ?? "")
    ) {
      if (params.encodedDataLength <= MAX_BODY) {
        try {
          const body = await this.#send("Network.getResponseBody", {
            requestId: id,
          });
          if (!body.base64Encoded)
            entry.response = this.#sanitizer.response(
              entry.response,
              body.body,
            );
        } catch {
          entry.response.captureError = "Response body unavailable";
        }
      }
      if (entry.response.bodyOmitted) {
        entry.response.captureError ??=
          "Structured response body unavailable or invalid";
        this.#complete = false;
      }
    }
    this.#append(entry);
    if (entry.response?.parseError) this.#complete = false;
    this.#reading--;
  }
  export() {
    return structuredClone({
      schemaVersion: 1,
      kind: "google-photos-sanitized-capture",
      complete:
        this.#complete && this.#pending.size === 0 && this.#reading === 0,
      entries: this.#entries,
      pending: this.#pending.size + this.#reading,
    });
  }
}
