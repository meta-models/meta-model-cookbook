# Example output: what Muse Wonder wrote in our run

`run.sh` does not use these files. Every run writes its own pipeline, so your albums, script and file names will differ.
They are here so you can see what the one-line prompt produced in our 10,000-photo run.

| File | What it is |
|---|---|
| `pipeline.py` | The pipeline script Muse Wonder wrote in the workspace (97 lines). All 16 Muse Ember subagents ran it unchanged, one shard each: `python3 pipeline.py --shard N --num-shards 16`. It sends 8 photos per request at 512 px with `reasoning_effort: "minimal"`, moves each photo to `Photos/<album>/<caption-slug>_<original-name>.jpg`, and keeps a resumable per-shard log. |
| `sample.py` | The script Muse Wonder used first to caption 32 sample photos (every 312th) and choose the 8 albums that `pipeline.py` uses. |
| `worker_briefs.json` | The 16 tasks Muse Wonder gave the subagents. Each worker gets one command and owns one shard. |
| `final_message.md` | Muse Wonder's report at the end of the run. |

The scripts read `MODEL_API_BASE`, `MODEL_API_KEY` and `EMBER_MODEL` from the environment, as the prompt tells them to.
