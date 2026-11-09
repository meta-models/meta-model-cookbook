#!/usr/bin/env python3
"""Caption, rename and sort Photos/Inbox photos into albums.

Usage: python3 pipeline.py --shard 0 --num-shards 16
Shard rule (timing-independent): numeric id in IMG_NNNNN.jpg with N % num_shards == shard.
Each request: 8 photos, resized to max 512px, reasoning_effort=minimal.
Moves each photo to Photos/<Album>/<caption-slug>_<orig-stem>.jpg and appends
one JSON line per photo to Photos/_manifests/shard_<shard:02d>.jsonl (resumable: skips done).
"""
import argparse, base64, io, json, os, re, shutil, sys, time, urllib.request, urllib.error
from PIL import Image

ALBUMS = ["Food-and-Drink", "Animals-and-Wildlife", "Nature-and-Plants",
          "Landscapes-and-Travel", "City-and-Architecture", "Vehicles-and-Transport",
          "Home-and-Interiors", "Objects-and-Everyday-Life"]
INBOX = "Photos/Inbox"

def datauri(path):
    im = Image.open(path).convert("RGB")
    im.thumbnail((512, 512))
    b = io.BytesIO(); im.save(b, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()

def slugify(text, maxlen=60):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:maxlen].rstrip("-") or "photo")

def call_api(paths):
    base = os.environ["MODEL_API_BASE"]; key = os.environ["MODEL_API_KEY"]; model = os.environ["EMBER_MODEL"]
    prompt = ("Caption each of the %d images in one short sentence and classify each into exactly one album "
              "from this list: %s. Reply ONLY with a JSON array, in order, of objects "
              '{"caption": "...", "album": "..."} using the exact album strings.' % (len(paths), ", ".join(ALBUMS)))
    content = [{"type": "text", "text": prompt}]
    for p in paths:
        content.append({"type": "image_url", "image_url": {"url": datauri(p)}})
    payload = {"model": model, "reasoning_effort": "minimal",
               "messages": [{"role": "user", "content": content}], "max_tokens": 1200}
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(base + "/chat/completions", data=json.dumps(payload).encode(),
                                         headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            txt = d["choices"][0]["message"]["content"].strip()
            txt = re.sub(r"^```(json)?|```$", "", txt, flags=re.M).strip()
            arr = json.loads(txt)
            assert isinstance(arr, list) and len(arr) == len(paths)
            out = []
            for it in arr:
                album = it.get("album", "Objects-and-Everyday-Life")
                if album not in ALBUMS: album = "Objects-and-Everyday-Life"
                out.append({"caption": str(it.get("caption", "")).strip() or "Untitled photo", "album": album})
            return out
        except Exception as e:
            last = e; time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"API failed after retries: {last}")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--num-shards", type=int, default=16); args = ap.parse_args()
    os.makedirs("Photos/_manifests", exist_ok=True)
    manifest = f"Photos/_manifests/shard_{args.shard:02d}.jsonl"
    done = set()
    if os.path.exists(manifest):
        for line in open(manifest):
            try: done.add(json.loads(line)["original"])
            except Exception: pass
    files = []
    for f in sorted(os.listdir(INBOX)):
        m = re.match(r"IMG_(\d+)\.jpg$", f)
        if m and int(m.group(1)) % args.num_shards == args.shard and f not in done:
            files.append(f)
    print(f"shard {args.shard}: {len(files)} photos", flush=True)
    with open(manifest, "a") as mf:
        for i in range(0, len(files), 8):
            batch = files[i:i+8]
            try:
                results = call_api([os.path.join(INBOX, f) for f in batch])
            except Exception as e:
                print(f"shard {args.shard}: BATCH FAILED {batch}: {e}", flush=True); continue
            for f, res in zip(batch, results):
                stem = os.path.splitext(f)[0]
                album_dir = os.path.join("Photos", res["album"]); os.makedirs(album_dir, exist_ok=True)
                dest = os.path.join(album_dir, f"{slugify(res['caption'])}_{stem}.jpg")
                n = 2
                base_dest = dest
                while os.path.exists(dest):
                    dest = base_dest[:-4] + f"-{n}.jpg"; n += 1
                shutil.move(os.path.join(INBOX, f), dest)
                rec = {"original": f, "caption": res["caption"], "album": res["album"], "new_path": dest}
                mf.write(json.dumps(rec) + "\n"); mf.flush()
            print(f"shard {args.shard}: {min(i+8,len(files))}/{len(files)}", flush=True)
    print(f"shard {args.shard}: DONE", flush=True)

if __name__ == "__main__":
    main()
