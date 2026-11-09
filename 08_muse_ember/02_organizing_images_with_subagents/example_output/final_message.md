Done — all 10,000 photos captioned, renamed, and sorted. `Photos/Inbox` is empty.

**Albums chosen** from a 32-photo sample captioned first: Food-and-Drink (1,531), Animals-and-Wildlife (1,539), Objects-and-Everyday-Life (1,646), Vehicles-and-Transport (1,231), Nature-and-Plants (1,206), City-and-Architecture (1,022), Home-and-Interiors (1,001), Landscapes-and-Travel (824).

**Pipeline:** `pipeline.py` sends 8 photos per request to `$EMBER_MODEL` via `$MODEL_API_BASE`, resized to 512 px, `reasoning_effort: "minimal"`, returning caption + album per photo; files are moved to `Photos/<Album>/<caption-slug>_<original-name>.jpg` and are resumable via per-shard manifests. Sixteen `ember-worker` subagents ran it in parallel, one shard each (`--shard N --num-shards 16`, sharding by photo number modulo 16) — all reported DONE with no failed batches.

**Verified:** 10,000 manifest records, 10,000 unique originals, 0 missing files, 10,000 JPGs on disk under `Photos/`. The merged caption index is at `Photos/captions.jsonl` and `Photos/captions.csv`, with per-shard logs in `Photos/_manifests/`.
