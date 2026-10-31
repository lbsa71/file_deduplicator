import { requireThat } from "./errors.js";
export const JOB_PROTOCOL_VERSION = 1;
export const JOBS = Object.freeze({
  "inventory-counts": Object.freeze({
    version: 1,
    effect: "read",
    phases: Object.freeze([
      "checking",
      "library",
      "favorites",
      "albums",
      "verifying",
      "complete",
      "failed",
    ]),
    validateInput: (input) =>
      requireThat(
        input &&
          typeof input === "object" &&
          !Array.isArray(input) &&
          Object.keys(input).length === 0,
        "Invalid job input",
        "INPUT",
      ),
    validateResult: (result) =>
      requireThat(
        result &&
          Object.keys(result).length === 5 &&
          result?.complete === true &&
          result.retentionReady === false &&
          ["photos", "favorites", "albums"].every(
            (k) =>
              Number.isInteger(result[k]) &&
              result[k] >= 0 &&
              result[k] <= 1000000,
          ) &&
          result.favorites <= result.photos,
        "Invalid counts result",
      ),
  }),
});
export const capabilities = () =>
  Object.entries(JOBS).map(([operation, spec]) => ({
    operation,
    version: spec.version,
  }));
