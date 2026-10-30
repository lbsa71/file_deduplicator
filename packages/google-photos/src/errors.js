export class ProtocolError extends Error {
  constructor(message, code = "PROTOCOL") {
    super(message);
    this.name = "ProtocolError";
    this.code = code;
  }
}
export class UnknownOutcomeError extends ProtocolError {
  constructor() {
    super(
      "Remote write outcome is unknown; reconcile before continuing",
      "UNKNOWN_OUTCOME",
    );
    this.name = "UnknownOutcomeError";
  }
}
export function requireThat(ok, message, code) {
  if (!ok) throw new ProtocolError(message, code);
}
export function identifier(value, label = "identifier") {
  requireThat(
    typeof value === "string" &&
      value.length > 0 &&
      value.length <= 4096 &&
      !/[\s\x00-\x1f]/.test(value),
    `Invalid ${label}`,
    "INPUT",
  );
  return value;
}
export function text(value, label) {
  requireThat(typeof value === "string", `Invalid ${label}`);
  return value;
}
export function array(value, label) {
  requireThat(Array.isArray(value), `Invalid ${label}`);
  return value;
}
export function knownBoolean(value, label) {
  if (value === undefined || value === null) return null;
  requireThat(typeof value === "boolean", `Invalid ${label}`);
  return value;
}
