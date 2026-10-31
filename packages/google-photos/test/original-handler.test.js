import test from "node:test";
import assert from "node:assert/strict";
import { createGoogleJobHandlers } from "../src/google-job-handlers.js";

const photo = {
  namespace: "library-media",
  mediaKey: "media-a",
  dedupKey: "dedup-a",
  favorite: null,
  trashTimestamp: null,
  companion: true,
  filename: "original.jpg",
  size: 100,
};
test("known motion-photo companions stop before requesting a download link or transferring", async () => {
  let links = 0,
    transfers = 0;
  const handler = createGoogleJobHandlers({
    readerFactory: async () => ({
      observation: async () => photo,
      downloadLink: async () => {
        links++;
        return { url: "https://photos.google.com/download/fixture" };
      },
    }),
    importOriginal: async () => {
      transfers++;
    },
  })["download-original"];
  await assert.rejects(
    handler("account", {
      job: { input: { photoUrl: "https://photos.google.com/photo/media-a" } },
      phase: async () => {},
      isActive: () => true,
    }),
    (error) => error.code === "PRECONDITION",
  );
  assert.equal(links, 0);
  assert.equal(transfers, 0);
});
