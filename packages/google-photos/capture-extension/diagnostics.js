const messages = {
  PAIR_ENDPOINT:
    "Enter a valid HTTPS PhotoFlow server address without a path, credentials, query or fragment.",
  PAIR_PERMISSION:
    "Allow Chrome access to the selected PhotoFlow server, then pair again.",
  PAIR_CODE: "Enter a fresh pairing code created by this PhotoFlow server.",
  PAIR_TAB:
    "Select a signed-in Google Photos tab in Chrome, then open this extension and pair again.",
  PAIR_SESSION: "Sign in to Google Photos in Chrome before pairing.",
  PAIR_FETCH:
    "PhotoFlow could not be reached. Open the selected endpoint in Chrome and check its certificate warning and that the local server is running. Then use a fresh pairing code.",
  PAIR_HTTP:
    "PhotoFlow rejected pairing. Create a fresh code on the selected endpoint for the same Google account and try again.",
  PAIR_REPLY:
    "PhotoFlow returned an invalid pairing reply. Pairing was not saved.",
  ORIGIN: "Open the Google Photos tab before checking reads.",
  SESSION: "Google Photos read-session data is unavailable (SESSION).",
  ACCOUNT: "The Google Photos account changed during the read (ACCOUNT).",
  BODY: "Google Photos returned no readable response body (BODY).",
  SIZE: "The Google Photos response exceeded the read limit (SIZE).",
  TRANSPORT: "The Google Photos read transport failed.",
  PROTOCOL:
    "The Google Photos response did not match the supported protocol (PROTOCOL).",
  HTTP: "Google Photos returned a non-success HTTP status (HTTP).",
  INPUT: "Read inspection stopped because its input was invalid (INPUT).",
  UNQUALIFIED: "The requested operation is not an approved read (UNQUALIFIED).",
  CIRCUIT_OPEN:
    "The read client stopped after an earlier failure (CIRCUIT_OPEN).",
};
const stages = {
  fetch: "The Google Photos fetch failed",
  body: "Reading the Google Photos response body failed",
  decode: "Decoding the Google Photos response failed",
};
const reasons = new Set([
  "AbortError",
  "TypeError",
  "RangeError",
  "ReferenceError",
  "SecurityError",
  "SyntaxError",
  "UnknownError",
]);

export function sanitizeReadDiagnostic(value) {
  if (!value || !Object.hasOwn(messages, value.code)) return null;
  return {
    code: value.code,
    ...(Object.hasOwn(stages, value.stage) ? { stage: value.stage } : {}),
    ...(reasons.has(value.reason) ? { reason: value.reason } : {}),
  };
}

export function readFailureMessage(value) {
  const diagnostic = sanitizeReadDiagnostic(value);
  if (!diagnostic) return null;
  if (diagnostic.code === "TRANSPORT" && diagnostic.stage)
    return `${stages[diagnostic.stage]}${diagnostic.reason ? ` (${diagnostic.reason})` : ""}.`;
  return messages[diagnostic.code];
}
