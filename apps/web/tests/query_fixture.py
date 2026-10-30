"""Disposable HTTPS fixture for query-smoke.mjs; never opens the real library.

Run with source packages on PYTHONPATH and built static assets present. The
temporary library, TLS key, catalog and thumbnails are removed on shutdown.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from PIL import Image

from photoflow.adapters import LocalFileSystem
from photoflow.metadata import resolve
from photoflow.model import Record, encoded
from photoflow_web.app import create_app
from photoflow_web.core import atomic

USER = "fixture"
PASSWORD = "fixture-local-only"
COUNT = 108


def prepare(base):
    root = base / "library"
    atomic(
        root / ".photoflow/library.json",
        {"schema_version": 2, "library_id": "query-fixture"},
    )
    filesystem = LocalFileSystem(str(root))
    manifest = []
    for index in range(COUNT):
        ident = str(uuid.uuid5(uuid.NAMESPACE_URL, f"photoflow-query-fixture/{index}"))
        year = 2009 if index % 2 == 0 else 2010
        relative = f"photos/{year}/06/{ident}.jpg"
        photo = root / relative
        photo.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 48), (index * 2, index, 255 - index)).save(
            photo, quality=95
        )
        people = [
            name
            for name, included in (
                ("Viktor", index % 3 in (0, 1)),
                ("Ellen", index % 3 in (0, 2)),
            )
            if included
        ]
        record = Record.create(ident, "query-fixture", relative).data
        record["sources"][0]["original_filename"] = f"fixture-{index:03}.jpg"
        source = {
            "title": f"fixture-{index:03}.jpg",
            "people": [{"name": name} for name in people],
            "photoTakenTime": {
                "timestamp": str(
                    int(datetime(year, 6, 15, tzinfo=timezone.utc).timestamp())
                )
            },
            "favorited": index % 4 == 0,
            "fixture_unknown_field": f"preserve-{index}",
        }
        record["sources"][0]["documents"] = [
            {
                "kind": "takeout",
                "relative_path": f"inbox/fixture-{index:03}.jpg.json",
                "sha256": hashlib.sha256(encoded(source)).hexdigest(),
                "document": source,
            }
        ]
        record["overrides"] = {"tags": ["Original"], "albums": ["Family"]}
        record["resolved"] = resolve(Record(record))
        record["file"]["sha256"] = hashlib.sha256(photo.read_bytes()).hexdigest()
        signature = filesystem.stat(relative)
        record["file"]["fingerprint"] = signature.to_dict()
        record["file"]["size_bytes"] = signature.size
        atomic(photo.with_name(photo.name + ".photo.json"), record)
        manifest.append(
            {
                "id": ident,
                "path": relative,
                "sha256": record["file"]["sha256"],
                "people": people,
            }
        )
    atomic(base / "manifest.json", manifest)
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8098)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="photoflow-query-browser-") as temporary:
        base = Path(temporary)
        root = prepare(base)
        key, cert = base / "key.pem", base / "cert.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=IP:127.0.0.1,DNS:localhost",
            ],
            check=True,
            capture_output=True,
        )

        def auth(data):
            ok = data.get("username") == USER and (
                data.get("password") == PASSWORD
                or ("password" not in data and data.get("uid") == 12345)
            )
            return {"ok": ok, "uid": 12345}

        app = create_app(
            root,
            base / "state",
            auth=auth,
            role_resolver=lambda username: 2 if username == USER else 0,
        )
        print(
            json.dumps(
                {
                    "url": f"https://127.0.0.1:{args.port}",
                    "username": USER,
                    "password": PASSWORD,
                    "photos": COUNT,
                    "temporary": str(base),
                }
            ),
            flush=True,
        )
        try:
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=args.port,
                ssl_keyfile=str(key),
                ssl_certfile=str(cert),
                log_level="warning",
            )
        finally:
            original = json.loads((base / "manifest.json").read_text())
            changed = [
                item["id"]
                for item in original
                if hashlib.sha256((root / item["path"]).read_bytes()).hexdigest()
                != item["sha256"]
            ]
            if changed:
                raise AssertionError(f"Fixture original bytes changed: {changed}")
            print(
                "Fixture verified: all 108 original files retain their initial SHA-256.",
                flush=True,
            )


if __name__ == "__main__":
    main()
