export function canStartSync(sync, now = Date.now() / 1000) {
  const r = sync?.review;
  return (
    sync?.state === "review" &&
    /^[a-f0-9]{32}$/.test(r?.manifestId) &&
    /^[a-f0-9]{64}$/.test(r?.sha256) &&
    Number.isInteger(r?.trash) &&
    r.trash > 0 &&
    Number.isInteger(r?.keep) &&
    r.keep >= 0 &&
    Number.isFinite(r?.expiresAt) &&
    r.expiresAt > now
  );
}
export function syncPresentation(sync, now = Date.now() / 1000) {
  const prepare = { action: "prepare", label: "Prepare sync" };
  const states = {
    idle: {
      title: "Make room in Google Photos",
      description:
        "Prepare a review of the photos already preserved in this library.",
      ...prepare,
    },
    preparing: {
      title:
        sync?.phase === "local"
          ? "Checking local copies"
          : "Reading Google Photos",
      description: "Your photos stay in place while the review is prepared.",
      action: null,
    },
    pausing: {
      title: "Pausing sync",
      description:
        "The current photo may finish. No further removals will start.",
      action: null,
    },
    paused: {
      title: "Sync paused",
      description:
        "Start a fresh pass when ready. Photos already in Trash are excluded; remaining photos are checked again.",
      ...prepare,
      label: "Prepare fresh pass",
    },
    preparation_failed: {
      title: "Preparation stopped",
      description:
        "Prepare a fresh review. No photos were changed by this preparation.",
      ...prepare,
    },
    expired: {
      title: "Prepare an updated review",
      description:
        "The previous review has expired. Photos already in Trash will be excluded from the new inventory.",
      ...prepare,
    },
    running: {
      title: "Sync in progress",
      description: "Keep this Mac online with Chrome and Google Photos open.",
      action: null,
    },
    complete: {
      title: "Sync complete",
      description:
        "The reviewed photos were processed. Protected photos stayed in Google.",
      ...prepare,
    },
  };
  if (sync?.state === "review") {
    if (sync.review?.expiresAt <= now) return states.expired;
    if (sync.review?.trash === 0)
      return {
        title: "Everything is kept",
        description:
          "There are no verified, unprotected photos to move to Trash.",
        ...prepare,
      };
    if (canStartSync(sync, now))
      return {
        title: "Review your sync",
        description: "Only the reviewed photos will move to Google Trash.",
        action: "commit",
        label: `Move ${sync.review.trash.toLocaleString()} ${sync.review.trash === 1 ? "photo" : "photos"} to Trash`,
      };
  }
  return (
    states[sync?.state] || {
      title: "Checking sync status",
      description: "",
      action: null,
    }
  );
}
