#!/usr/bin/env python3
"""Download the held-out files listed in heldout.json into <dest>/<alias>/ and check each SHA-256.

These are real source files from public repos at pinned commits. Download and score them
only after the final port is frozen; keep them out of the development inputs.
Usage: python3 heldout-tools/fetch.py --dest <workspace>/heldout
Needs HTTPS access to raw.githubusercontent.com (urllib honors https_proxy).
"""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument(
    "--dest", type=Path, required=True, help="directory to write <alias>/<file> into"
)
dest = parser.parse_args().dest.resolve()
entries = json.loads((Path(__file__).resolve().parent / "heldout.json").read_text())
for e in entries:
    owner_repo = e["repo"].removeprefix("https://github.com/")
    url = f"https://raw.githubusercontent.com/{owner_repo}/{e['commit']}/{e['path']}"
    data = urllib.request.urlopen(url, timeout=60).read()
    assert hashlib.sha256(data).hexdigest() == e["sha256"], url
    out = (
        dest
        / e["alias"]
        / (owner_repo.split("/")[1] + "__" + e["path"].replace("/", "__"))
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
print(f"fetched {len(entries)} held-out files into {dest}")
