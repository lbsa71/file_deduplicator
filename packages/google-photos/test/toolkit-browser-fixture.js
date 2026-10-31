import { item, album, envelope, ACCOUNT } from "./fixtures.js";
export function toolkitBrowserFixture() {
  const state = {
    favorite: false,
    archived: false,
    trashed: false,
    member: false,
    description: "",
    timestamp: 1700000000000,
    timezone: 0,
    location: null,
    albums: [["album-a", "PhotoFlow test existing"]],
    writes: [],
    failNextWrite: false,
    originalSize: 100,
  };
  let calls = 0;
  const photo = () => {
    const row = item("media-a", state.favorite);
    row[13] = state.archived;
    return row;
  };
  const albumRow = ([id, title]) => {
    const row = album(id);
    row.at(-1)[72930366][1] = title;
    return row;
  };
  const details = () => {
    const row = Array(32).fill(null);
    row[0] = "media-a";
    row[1] = state.description;
    row[2] = "photoflow-test-fixture.jpg";
    row[3] = state.timestamp;
    row[4] = state.timezone;
    row[5] = state.originalSize;
    row[11] = "dedup-media-a";
    row[13] = state.location ? [state.location] : null;
    row[19] = state.member ? [albumRow(state.albums[0])] : [];
    return row;
  };
  return {
    state,
    get calls() {
      return calls;
    },
    async route(route) {
      const request = route.request(),
        url = new URL(request.url());
      if (!url.pathname.endsWith("/batchexecute"))
        return route.fulfill({
          contentType: "text/html",
          body: `<h1>Synthetic Google Photos</h1><script>window.WIZ_global_data=${JSON.stringify({ oPEP7c: ACCOUNT, FdrFJe: "PRIVATE_SESSION", cfb2h: "build", eptZe: "/_/PhotosUi/", SNlM0e: "PRIVATE_CSRF" })}</script>`,
        });
      calls++;
      const rpc = url.searchParams.get("rpcids");
      const data = JSON.parse(
        JSON.parse(
          new URLSearchParams(request.postData()).get("f.req"),
        )[0][0][1],
      );
      let result;
      let write = true;
      switch (rpc) {
        case "lcxiM":
          result = data[0]
            ? [[item("media-b", true)], null]
            : [[photo()], "next"];
          write = false;
          break;
        case "EzkLib":
          result = [
            [item("media-b", true), ...(state.favorite ? [photo()] : [])],
            null,
          ];
          write = false;
          break;
        case "Z5xsfc":
          result = [state.albums.map(albumRow), null];
          write = false;
          break;
        case "snAcKc": {
          const b = item("album-b");
          b[3] = "dedup-media-b";
          const a = photo();
          a[0] = "album-scoped-a";
          result = [null, [b, ...(state.member ? [a] : [])], null, [data[0]]];
          write = false;
          break;
        }
        case "VrseUb":
          result = [photo()];
          write = false;
          break;
        case "fDcn4b":
          result = [details()];
          write = false;
          break;
        case "zy0IHe":
          result = [state.trashed ? [photo()] : [], null];
          write = false;
          break;
        case "EzwWhf":
          result = [null, null, null, null, null, null, [12, 100, null, 10]];
          write = false;
          break;
        case "pLFTfd":
          result = ["https://photos.google.com/download/fixture"];
          write = false;
          break;
        case "swbisb":
          result = [data[0].map((hash) => [hash, photo()])];
          write = false;
          break;
        case "Ftfh0":
          state.favorite = data[1][0] === 1;
          break;
        case "w7TP3c":
          state.archived = data[0][0][1][0] === 1;
          break;
        case "XwAOJf":
          state.trashed = data[1] === 1;
          break;
        case "AQNOFd":
          state.description = data[1];
          break;
        case "DaSgWe":
          state.timestamp = data[0][0][1] * 1000;
          state.timezone = data[0][0][2] * 1000;
          break;
        case "EtUHOe":
          state.location = data[1][0] === 1 ? null : data[1][1];
          break;
        case "E1Cajb":
          if (data[0][0] !== "media-a") throw Error("Wrong album-add identity");
          state.member = true;
          break;
        case "ycV3Nd":
          if (data[0][0] !== "album-scoped-a")
            throw Error("Wrong album-scoped removal identity");
          state.member = false;
          break;
        case "OXvT9d": {
          const id = "new-album-" + state.albums.length;
          state.albums.push([id, data[0]]);
          result = [[id]];
          break;
        }
        default:
          throw Error("Unexpected synthetic RPC " + rpc);
      }
      if (write) {
        state.writes.push(rpc);
        if (state.failNextWrite) {
          state.failNextWrite = false;
          return route.abort("failed");
        }
        result ??= [true];
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope(rpc, result),
      });
    },
  };
}
