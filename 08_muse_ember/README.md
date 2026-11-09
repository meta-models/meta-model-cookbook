# Muse Ember

Recipes for building with **Muse Ember** (`muse-ember-1.0`) on Meta Model API. Muse Ember is built for
high-volume, repeated work: pair it with a larger model that plans, and let Muse Ember run the subagent tasks
and batch jobs.

## Recipes

| # | Recipe | What it does |
|---|--------|--------------|
| [01](01_python_to_rust/) | Port Python to Rust with Muse Wonder and Muse Ember | Muse Wonder plans and checks the work; Muse Ember workers port 16 Pygments lexers from Python to Rust in parallel. |
| [02](02_organizing_images_with_subagents/) | Organizing images with subagents | One prompt in Muse Code: Muse Wonder writes the photo pipeline, and 16 Muse Ember subagents run it to caption, rename and sort a 10,000-photo camera roll. |

## Configuration

Sign in to Muse Code with your plan, or use a Model API key:

```bash
export MODEL_API_KEY="<your Model API key>"
```

## Adding a recipe

Follow [CONTRIBUTING.md](../CONTRIBUTING.md): a numbered `NN_short_name/` folder with a
`README.md` that opens with the summary table, self-contained code, token usage (not dollar
costs), and a row in both this table and the root [README](../README.md).
