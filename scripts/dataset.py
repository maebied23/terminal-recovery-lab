"""Inspect or explicitly reseal locally edited input files. Does not mutate runs."""

import argparse
import hashlib
import json
from app.datasets import ROOT, PACKS, load_pack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "seal"))
    parser.add_argument("pack", choices=PACKS)
    args = parser.parse_args()
    path = ROOT / args.pack / "manifest.json"
    original = path.read_text()
    try:
        if args.action == "seal":
            manifest = json.loads(original)
            for key, folder in (
                ("base_files", ROOT / "baseline-shift"),
                ("files", path.parent),
            ):
                manifest[key] = {
                    name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                    for name in manifest[key]
                }
            path.write_text(json.dumps(manifest, indent=2) + "\n")
        pack = load_pack(args.pack)
    except Exception:
        if args.action == "seal":
            path.write_text(original)
        raise
    print(
        json.dumps(
            dict(
                pack=args.pack,
                digest=pack["digest"],
                counts=pack["counts"],
                status="valid",
                observations=len(pack["receipts"]),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
