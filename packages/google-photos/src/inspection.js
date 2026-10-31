import { GooglePhotosClient } from "./client.js";
import { CaptureSanitizer } from "./capture.js";
import { identifier, requireThat } from "./errors.js";

function selectedId(value, kind) {
  requireThat(
    typeof value === "string" && value.length <= 8192,
    "Invalid selection URL",
    "INPUT",
  );
  const url = new URL(value);
  requireThat(
    url.origin === "https://photos.google.com" &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash,
    "Invalid selection URL",
    "INPUT",
  );
  const match = url.pathname.match(
    new RegExp(`^/(?:u/\\d+/)?${kind}/([A-Za-z0-9_-]+)$`),
  );
  requireThat(match, "Invalid selection path", "INPUT");
  return identifier(match[1]);
}
// A deliberately small read qualification, not an inventory or retention plan.
export async function inspectSelection(selection, transport) {
  const account = identifier(selection.account);
  const albumId = selectedId(selection.albumUrl, "album");
  const mediaKey = selectedId(selection.photoUrl, "photo");
  const sanitizer = new CaptureSanitizer();
  const evidence = {
    schemaVersion: 1,
    kind: "google-photos-selection-inspection",
    complete: false,
    entries: [],
  };
  let calls = 0,
    bytes = 0;
  const client = new GooglePhotosClient({
    account,
    maxPages: 2,
    maxItems: 500,
    transport: async (request) => {
      requireThat(++calls <= 4, "Inspection request limit", "INPUT");
      const response = await transport(request);
      const entry = {
        rpc: request.rpc,
        input: sanitizer.value(request.data),
        response: sanitizer.response(
          {
            status: response?.status,
            mimeType: "application/json",
            headers: {},
          },
          response?.body,
        ),
      };
      bytes += new TextEncoder().encode(JSON.stringify(entry)).length;
      requireThat(
        bytes <= 4 * 1024 * 1024,
        "Inspection evidence limit",
        "SIZE",
      );
      evidence.entries.push(entry);
      return response;
    },
  });
  try {
    const members = await client.albumItems(albumId);
    const basic = await client.item(mediaKey);
    const details = await client.details(mediaKey);
    requireThat(
      basic.dedupKey === details.dedupKey,
      "Conflicting detail identity",
    );
    const matches = members.items.filter(
      (item) => item.dedupKey === basic.dedupKey,
    );
    evidence.complete = evidence.entries.every(
      (e) => !e.response.bodyOmitted && !e.response.parseError,
    );
    return {
      summary: {
        albumMembers: members.items.length,
        matchingDedupKeys: matches.length,
        matchingMediaKeys: matches.filter(
          (item) => item.mediaKey === basic.mediaKey,
        ).length,
        detailsAgree: true,
        complete: true,
        retentionReady: false,
      },
      evidence,
    };
  } catch (error) {
    return {
      summary: { complete: false, retentionReady: false },
      evidence,
      diagnostic: {
        code: [
          "ACCOUNT",
          "HTTP",
          "TRANSPORT",
          "SIZE",
          "INPUT",
          "PROTOCOL",
        ].includes(error?.code)
          ? error.code
          : "PROTOCOL",
      },
    };
  }
}
