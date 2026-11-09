#!/usr/bin/env python3
"""Check a finished run: is every photo filed, which albums were created, and what do the new names look like.

  python3 check.py

Muse Wonder chooses the album names and the file layout itself, so this reads the folders rather than a
fixed index format: every subfolder of workspace/Photos (except Inbox and folders starting with "_" or ".")
counts as an album.
"""
import csv
import os
import random

ROOT = os.path.dirname(os.path.abspath(__file__))
PHOTOS = os.path.join(ROOT, "workspace", "Photos")
expected = {r["file"] for r in csv.DictReader(open(os.path.join(ROOT, "prepare", "CREDITS.csv"), encoding="utf-8"))}
inbox = [f for f in os.listdir(os.path.join(PHOTOS, "Inbox")) if f.lower().endswith(".jpg")] \
    if os.path.isdir(os.path.join(PHOTOS, "Inbox")) else []
albums = {}
for name in sorted(os.listdir(PHOTOS)):
    path = os.path.join(PHOTOS, name)
    if not os.path.isdir(path) or name == "Inbox" or name[0] in "_.":
        continue
    files = [os.path.relpath(os.path.join(dp, f), path) for dp, _, fs in os.walk(path) for f in fs if f.lower().endswith(".jpg")]
    albums[name] = files
filed = sum(len(v) for v in albums.values())
print(f"Photos fetched: {len(expected):,}   filed in albums: {filed:,}   still in Inbox: {len(inbox):,}")
print("Result:", "every photo filed" if filed == len(expected) and not inbox else "INCOMPLETE")
print(f"\n{len(albums)} albums:")
for name, files in sorted(albums.items(), key=lambda kv: -len(kv[1])):
    print(f"  {name:32} {len(files):6,}")
random.seed(0)
print("\nSample of new names:")
for name, files in sorted(albums.items()):
    for f in random.sample(files, min(2, len(files))):
        print(f"  {name}/{f}")
for f in sorted(os.listdir(PHOTOS)):
    if f.lower().endswith((".csv", ".jsonl", ".json")):
        print(f"\nIndex written by the run: Photos/{f}")
