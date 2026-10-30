import { requireThat } from "./errors.js";
export function decideRetention(facts) {
  const bools = [
    "localVerified",
    "backupVerified",
    "companionsVerified",
    "localFavorite",
    "remoteFavorite",
    "localCuratedAlbum",
    "remoteCuratedAlbum",
    "identityVerified",
    "remoteComplete",
  ];
  for (const key of bools)
    requireThat(
      facts[key] == null || typeof facts[key] === "boolean",
      `Invalid ${key}`,
      "INPUT",
    );
  const result = (action, ...reasons) => ({ action, reasons });
  if (!["missing", "verified"].includes(facts.metadata))
    return result(
      "review",
      "Google metadata is invalid, ambiguous, or unknown",
    );
  if (!["none", "pending", "unknown", "uploaded"].includes(facts.uploadState))
    return result("review", "Upload state is unknown");
  if (facts.uploadState === "unknown" || facts.uploadState === "pending")
    return result(
      "review",
      "Resolve the outstanding upload before further operations",
    );
  if (
    !["present", "absent"].includes(facts.remotePresence) ||
    facts.identityVerified !== true ||
    facts.remoteComplete !== true
  )
    return result("review", "Remote presence or identity is unproved");
  if (bools.some((k) => facts[k] == null))
    return result("review", "Required evidence is unknown");
  const wanted =
    facts.localFavorite ||
    facts.remoteFavorite ||
    facts.localCuratedAlbum ||
    facts.remoteCuratedAlbum;
  if (facts.remotePresence === "absent") {
    if (facts.uploadState === "uploaded")
      return result(
        "review",
        "Previously uploaded media is now absent; reconcile instead of uploading again",
      );
    if (facts.localVerified !== true || facts.companionsVerified !== true)
      return result(
        "review",
        "Local original and companion media are not verified",
      );
    return wanted || facts.metadata === "missing"
      ? result("upload", "Publish selected media or obtain Google metadata")
      : result("local-only", "No cloud retention reason");
  }
  if (wanted) return result("keep", "Favorite or curated album membership");
  if (!facts.localVerified || !facts.companionsVerified)
    return result("keep", "The complete original is not verified locally");
  if (facts.metadata === "missing")
    return result(
      "await-metadata",
      "Retain until matching Takeout metadata is imported",
    );
  if (!facts.backupVerified)
    return result("keep", "Independent backup is not verified");
  return result(
    "review-trash",
    "Verified locally and independently backed up; no retention reason",
  );
}
