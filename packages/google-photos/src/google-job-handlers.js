import { JOBS, photoKey } from "./jobs.js";
import { ToolkitPilot } from "./toolkit-pilot.js";
export function createGoogleJobHandlers({
  readerFactory,
  writeFactory,
  journal,
  countsHandler,
}) {
  return Object.fromEntries(
    Object.keys(JOBS).map((operation) => [
      operation,
      async (account, context) => {
        const input = context.job.input;
        JOBS[operation].validateInput(input);
        if (operation === "inventory-counts" && countsHandler)
          return countsHandler(account, context);
        const reader = await readerFactory(account, context);
        if (
          JOBS[operation].effect === "write" ||
          operation === "reconcile-write"
        ) {
          const pilot = new ToolkitPilot({
            account,
            reader,
            journal,
            write: writeFactory(account, context),
            phase: context.phase,
          });
          return operation === "reconcile-write"
            ? pilot.reconcile(input.originalJobId)
            : pilot.execute(context.job);
        }
        if (operation !== "inventory-counts") await context.phase("reading");
        const kinds = {
          "library-page": "inventory",
          "favorites-page": "favorites",
          "albums-page": "albums",
          "album-members": "albumItems",
          "trash-page": "trash",
        };
        if (kinds[operation]) return reader.page(kinds[operation], input);
        if (operation === "photo-details")
          return {
            photo: await reader.observation(photoKey(input.photoUrl)),
            retentionReady: false,
          };
        if (operation === "storage-quota")
          return { ...(await reader.quota()), retentionReady: false };
        if (operation === "hash-candidates") {
          const result = await reader.hashCandidates(input.hashes);
          return {
            items: result.items,
            absenceProven: false,
            retentionReady: false,
          };
        }
        if (operation === "download-link") {
          const key = photoKey(input.photoUrl);
          await reader.downloadLink(key);
          return { mediaKey: key, available: true, retentionReady: false };
        }
        if (operation === "inventory-counts") {
          await context.phase("library");
          const library = await reader.inventory();
          await context.phase("favorites");
          const favorites = await reader.favorites();
          await context.phase("albums");
          const albums = await reader.albums();
          return {
            photos: library.items.length,
            favorites: favorites.items.length,
            albums: albums.items.length,
            complete: true,
            retentionReady: false,
          };
        }
      },
    ]),
  );
}
