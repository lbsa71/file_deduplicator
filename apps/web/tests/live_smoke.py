"""Synthetic scratch-library integration; caller supplies a temporary PAM account."""

import io, json, os, time, uuid, sys, zipfile
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from photoflow_web.app import create_app

root = Path(sys.argv[1])
state = Path(sys.argv[2])
root.mkdir(parents=True, exist_ok=True)
(root / ".photoflow").mkdir()
(root / ".photoflow/library.json").write_text(
    json.dumps({"schema_version": 2, "library_id": str(uuid.uuid4())})
)
app = create_app(root, state)
with TestClient(app, base_url="https://testserver") as client:
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://testserver"},
        json={
            "username": os.environ["PHOTOFLOW_TEST_USER"],
            "password": os.environ["PHOTOFLOW_TEST_PASSWORD"],
        },
    )
    response.raise_for_status()
    headers = {"Origin": "https://testserver", "X-CSRF-Token": response.json()["csrf"]}

    def call(path, method="GET", body=None, revision=None):
        h = {**headers, **({"If-Match": revision} if revision else {})}
        r = client.request(method, "/api/v1" + path, json=body, headers=h)
        r.raise_for_status()
        return r.json()

    def wait(job):
        for _ in range(300):
            d = call("/jobs/" + job["job_id"])
            if d["state"] == "failed":
                raise AssertionError(d)
            if d["state"] == "succeeded":
                return d["result"]
            time.sleep(0.1)
        raise AssertionError("Job timeout")

    folder = call("/folders", "POST", {"name": "Family"})
    image = io.BytesIO()
    Image.new("RGB", (800, 600), "blue").save(image, "JPEG")
    original = image.getvalue()
    batch = uuid.uuid4().hex
    for name, data in [
        ("photo.jpg", original),
        (
            "photo.jpg.supplemental-metadata.json",
            json.dumps(
                {
                    "people": [{"name": "Test Person"}],
                    "photoTakenTime": {"timestamp": "1545600000"},
                }
            ).encode(),
        ),
    ]:
        upload = call(
            "/uploads", "POST", {"name": name, "size": len(data), "batch_id": batch}
        )
        r = client.put(
            "/api/v1/uploads/" + upload["id"] + "/chunks",
            headers={**headers, "Upload-Offset": "0"},
            content=data,
        )
        r.raise_for_status()
        call("/uploads/" + upload["id"] + "/finish", "POST", {})
    result = wait(call("/upload-batches/" + batch + "/process", "POST", {}))
    assert not result["errors"], result
    row = call("/photos")["items"][0]
    ident = row["id"]
    d = call("/photos/" + ident)
    assert d["resolved"]["people"] == ["Test Person"]
    wait(
        call(
            "/photos/" + ident + "/metadata",
            "PATCH",
            {"set": {"favorite": True}},
            d["revision"],
        )
    )
    d = call("/photos/" + ident)
    wait(
        call(
            "/photos/" + ident + "/placement",
            "POST",
            {"folder_id": folder["id"]},
            d["revision"],
        )
    )
    wait(call("/scans", "POST", {"mode": "reconcile"}))
    d = call("/photos/" + ident)
    assert d["file"]["relative_path"].startswith("folders/Family/")
    wait(call("/photos/" + ident, "DELETE", revision=d["revision"]))
    d = call("/photos/" + ident)
    wait(call("/trash/" + ident + "/restore", "POST", {}, d["revision"]))
    assert client.get("/api/v1/photos/" + ident + "/original").content == original
    wait(
        call(
            "/folders/" + folder["id"], "PATCH", {"name": "Renamed"}, folder["revision"]
        )
    )
    folder = call("/library")["folders"][0]
    (root / folder["path"] / "notes.txt").write_text("keep this file")
    wait(call("/folders/" + folder["id"], "DELETE", revision=folder["revision"]))
    wait(call("/trash/folders/" + folder["id"] + "/restore", "POST", {}))
    assert (root / "folders/Renamed/notes.txt").read_text() == "keep this file"
    export = wait(call("/exports", "POST", {"ids": [ident], "include_metadata": True}))
    data = client.get(export["download_url"])
    data.raise_for_status()
    archive = zipfile.ZipFile(io.BytesIO(data.content))
    assert any(name.endswith("photo.jpg") for name in archive.namelist())
    print(
        "Scratch exFAT/PAM/API: uploads + Takeout people, metadata edit, manual move + scan, trash/restore, folder rename/trash/restore, original download and ZIP export passed"
    )
