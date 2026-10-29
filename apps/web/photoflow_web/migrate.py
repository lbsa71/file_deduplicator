"""Opt in to writer features that older PhotoFlow binaries must reject."""

import argparse, json
from photoflow.adapters import LocalFileSystem
from photoflow.model import encoded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    args = parser.parse_args()
    fs = LocalFileSystem(args.root)
    with fs.lock():
        marker = json.loads(fs.read_bytes(".photoflow/library.json"))
        if marker["schema_version"] == 2:
            return
        if marker["schema_version"] != 1:
            raise ValueError("Unsupported library format")
        if fs.list_files(".photoflow/pending"):
            raise ValueError("Recover pending moves before migrating")
        fs.atomic_write(
            ".photoflow/preparation/pre-web-library-v1.json",
            encoded(marker),
            replace=False,
        )
        marker.update(
            schema_version=2,
            writer_capabilities=[
                "manual-placement",
                "web-operation-recovery",
                "persistent-folders",
                "trash",
            ],
        )
        fs.atomic_write(".photoflow/library.json", encoded(marker))


if __name__ == "__main__":
    main()
