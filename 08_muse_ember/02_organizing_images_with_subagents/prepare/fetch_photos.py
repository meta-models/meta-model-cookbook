#!/usr/bin/env python3
"""Download the recipe's photos (Open Images V7, CC BY 2.0) and put them in workspace/Photos/Inbox.

  python3 prepare/fetch_photos.py               # all 10,000 photos (~770 MB), a few minutes
  python3 prepare/fetch_photos.py --limit=160   # a small set for a quick first run
  python3 prepare/fetch_photos.py --reset       # start over: empty workspace/, then refill the Inbox

Photos are resized to 768 px (long side), named IMG_00001.jpg ... as in the manifest, and kept in photos_cache/.
The Inbox gets hard links to the cached files, so the run can move and rename them and a reset needs no download.
Attribution for every photo is written to prepare/CREDITS.csv.
"""
import argparse
import csv
import io
import os
import shutil
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, "photos_cache")
WORKSPACE = os.path.join(ROOT, "workspace")
INBOX = os.path.join(WORKSPACE, "Photos", "Inbox")
ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=0, help="use only the first N photos")
ap.add_argument("--reset", action="store_true", help="delete workspace/ (results included) before refilling the Inbox")
a = ap.parse_args()
rows = list(csv.DictReader(open(os.path.join(HERE, "photos_manifest.csv"), encoding="utf-8")))
if a.limit:
    rows = rows[:a.limit]
os.makedirs(CACHE, exist_ok=True)


def get(r):
    out = os.path.join(CACHE, r["file"])
    if os.path.exists(out):
        return True
    url = f"https://open-images-dataset.s3.amazonaws.com/{r['split']}/{r['ImageID']}.jpg"
    for _ in range(3):
        try:
            data = urllib.request.urlopen(url, timeout=60).read()
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
            im.thumbnail((768, 768))
            im.save(out + ".part", "JPEG", quality=85, optimize=True)
            os.replace(out + ".part", out)
            return True
        except Exception:  # noqa: BLE001  (retry, then report the photo as missing)
            pass
    return False


ok = 0
with ThreadPoolExecutor(32) as ex:
    for i, good in enumerate(ex.map(get, rows), 1):
        ok += good
        if i % 1000 == 0:
            print(f"  downloaded {i}/{len(rows)}", flush=True)
if a.reset and os.path.isdir(WORKSPACE):
    shutil.rmtree(WORKSPACE)
os.makedirs(INBOX, exist_ok=True)
linked = 0
for r in rows:
    src, dst = os.path.join(CACHE, r["file"]), os.path.join(INBOX, r["file"])
    if os.path.exists(src) and not os.path.exists(dst):
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
        linked += 1
with open(os.path.join(HERE, "CREDITS.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["file", "title", "author", "license", "source"])
    for r in rows:
        w.writerow([r["file"], r["title"], r["author"], r["license"], r["landing_url"]])
print(f"{ok}/{len(rows)} photos available; {len(os.listdir(INBOX))} in {os.path.relpath(INBOX, ROOT)}")
sys.exit(0 if ok == len(rows) else 1)
