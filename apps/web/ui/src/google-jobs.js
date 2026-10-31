export function readSuite(target) {
  const jobs = [
    "inventory-counts",
    "library-page",
    "favorites-page",
    "albums-page",
    "trash-page",
    "storage-quota",
  ].map((operation) => ({ operation, input: {} }));
  if (target.photoUrl)
    for (const operation of ["photo-details", "download-link"])
      jobs.push({ operation, input: { photoUrl: target.photoUrl } });
  if (target.albumId)
    jobs.push({
      operation: "album-members",
      input: { albumId: target.albumId },
    });
  if (target.hashes?.length)
    jobs.push({
      operation: "hash-candidates",
      input: { hashes: target.hashes },
    });
  return jobs;
}
export function pilotSuite(target, metadata = {}, stamp = Date.now()) {
  if (!target.photoUrl || !target.albumId)
    throw Error("Select a synthetic photo and private test album first.");
  const photoUrl = target.photoUrl,
    albumId = target.albumId;
  const jobs = [
    { operation: "album-create", input: { title: "PhotoFlow test " + stamp } },
  ];
  for (const operation of ["favorite-set", "archive-set"])
    for (const value of [true, false])
      jobs.push({ operation, input: { photoUrl, value } });
  for (const description of ["PhotoFlow pilot", ""])
    jobs.push({
      operation: "description-set",
      input: { photoUrl, description },
    });
  if (metadata.timestampSec !== undefined)
    jobs.push({
      operation: "timestamp-set",
      input: {
        photoUrl,
        timestampSec: metadata.timestampSec,
        timezoneSec: metadata.timezoneSec,
      },
    });
  if (metadata.location) {
    jobs.push({
      operation: "location-set",
      input: { photoUrl, ...metadata.location },
    });
    jobs.push({ operation: "location-clear", input: { photoUrl } });
  }
  for (const operation of ["album-add", "album-remove"])
    jobs.push({ operation, input: { photoUrl, albumId } });
  for (const operation of ["trash", "restore"])
    jobs.push({ operation, input: { photoUrl } });
  return jobs;
}
