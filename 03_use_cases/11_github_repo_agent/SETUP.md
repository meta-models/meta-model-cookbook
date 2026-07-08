# Set up the GitHub Repo Agent in your own repo

This recipe's agent runs as a **GitHub Action**: on an issue or PR (or a `/oc` comment), it
checks out your repo, runs an OpenCode agent powered by the **Meta Model API** (Muse Spark),
and replies / labels / opens a PR. Everything runs inside *your* GitHub Actions runner — no
external service sees your code.

Estimated time: ~15 minutes for read-only PR review (Phase 1).

## Prerequisites

- A GitHub repository you can add secrets and workflows to.
- A **Meta Model API key** (`MODEL_API_KEY`).
- That's it for Phase 1. (Bun/OpenCode are installed automatically inside the Action.)

## What gets added to your repo

```
<your repo root>/
├── opencode.json          # Meta Model API provider config (Muse Spark)
├── AGENTS.md              # repo context + security rules every agent inherits
├── .opencode/
│   ├── agent/             # triage, qa, review, rfc, bugfix, stale, repo-agent
│   └── command/           # /triage /review /fix (for local opencode use)
└── .github/workflows/
    └── opencode-*.yml     # the workflows you choose to enable
```

> These three things (`opencode.json`, `AGENTS.md`, `.opencode/`) **must be at the repo
> root** — OpenCode discovers them from the checkout root. In this recipe they live in the
> recipe folder; copy them to your repo's root.

## Step 1 — Copy the agent files to your repo root

From this recipe folder (`github_repo_agent/`):

```bash
cp opencode.json AGENTS.md  /path/to/your-repo/
cp -r .opencode             /path/to/your-repo/
mkdir -p /path/to/your-repo/.github/workflows
# copy only the workflows you want (start with PR review — see Step 4)
cp workflow/opencode-pr-review.yml /path/to/your-repo/.github/workflows/
```

The items above are everything the agent needs to run.

## Step 2 — Add the API key as a repository secret

```bash
gh secret set MODEL_API_KEY --repo <owner>/<repo>   # paste your key when prompted
```
(Or: repo → Settings → Secrets and variables → Actions → New repository secret.)

The workflows pass it to OpenCode as `env: MODEL_API_KEY`, and `opencode.json` reads it via
`{env:MODEL_API_KEY}`. Nothing else needs the key.

## Step 3 — Point AGENTS.md at your repo

`AGENTS.md` is the shared brief every agent reads. Edit it so it describes **your** project:
what the repo is, what's in/out of scope, your conventions, and which key files to consult
(it ships with example content — replace it with your own project's description,
conventions, and key docs). Keep the **SECURITY** section:
it tells every agent to treat issue/PR text as untrusted input.

## Step 4 — Choose authentication, then enable workflows

The workflows use the runner's built-in `GITHUB_TOKEN` (`use_github_token: true`) — **no app
install required**. Each workflow declares only the permissions it needs. Alternatively you
can install the [OpenCode GitHub App](https://github.com/apps/opencode-agent) so actions
appear as the app; then drop `use_github_token` and the `GITHUB_TOKEN` env.

Enable workflows in phases (copy each file into `.github/workflows/` when you're ready):

| Phase | Workflow | Trigger | Token perms | Risk |
|---|---|---|---|---|
| 1 | `opencode-pr-review.yml` | PR opened/updated | `pull-requests: write` (comment), `contents: read` | low |
| 1 | `opencode-triage.yml` | issue opened | `issues: write` (comment+label) | low |
| 2 | `opencode-command.yml` | `/oc` comment (collaborators only) | `contents/issues/PRs: write` | medium |
| 3 | `opencode-bugfix.yml` | issue labeled `agent-fix` | `contents/PRs: write` | medium |
| — | `opencode-stale.yml` | weekly cron | `issues: write` | low |

Start with **Phase 1** only. Each `*.yml` already sets `model: model_api/muse-spark-1.1`,
`use_github_token: true`, `persist-credentials: false`, and least-privilege job permissions.

## Step 5 — Test it

- **PR review:** open a small test PR. Within a minute the `review` agent comments with a
  verdict (correctness, style, missing tests, AI-slop).
- **Triage:** open a test issue; the `triage` agent classifies, labels, and replies.
- **`/oc` (Phase 2):** as a collaborator, comment `/oc explain this` or `/oc fix this` on an
  issue/PR. The `repo-agent` orchestrator routes to the right specialist.
- **Bug fix (Phase 3):** add the `agent-fix` label to an issue; the `bugfix` agent
  investigates, patches, runs tests, and opens a PR for **human review** (it never merges).

## Security model (what protects you)

- Agents treat all issue/PR/comment text as **untrusted data**, never instructions (AGENTS.md).
- `webfetch` is disabled on every agent; read-only agents have no write/edit; `bash` is
  allow-listed (read-only `git`, specific `gh`); `bugfix` denies `curl`/`wget`/`nc`/`ssh`.
- No agent can **approve or merge** PRs. Write actions are gated behind a maintainer `/oc`
  comment or the `agent-fix` label.
- `pull_request` (not `pull_request_target`) so fork PRs run with a read-only token.
- Recommended hardening: branch protection on your default branch + CODEOWNERS on
  `.github/workflows/*` so the agent's own config requires human review to change.

## Customizing the agents

- **Change behavior / tone:** edit the markdown body of `.opencode/agent/<name>.md`.
- **Change tools/permissions:** edit the `tools:` / `permission:` frontmatter (see any agent
  for the pattern; e.g. `bugfix.md` shows an allow-listed `bash`).
- **Add an agent:** drop a new `.opencode/agent/<name>.md` with `mode`, `model`,
  `description` (the description is how `repo-agent` routes to it), and `tools`.
- **Switch model:** change `model:` in `opencode.json` and the workflows (e.g. another Meta
  Model API model).

## Verify your setup locally (optional)

The `opencode.json` you copied in Step 1 already points OpenCode at the Meta Model API via
`MODEL_API_KEY`, so the agents run headless exactly as they do in the Action. With OpenCode
installed and `MODEL_API_KEY` exported, from your repo root:

```bash
opencode agent list                      # should list triage, review, qa, bugfix, ...
opencode run --agent review "Review the latest changes for issues."
```
If an agent shows as "not found", your `.opencode/` isn't at the directory OpenCode treats as
the project root — make sure it's at the repo root (OpenCode uses `$PWD` / the git root).

> **Prefer to connect interactively?** OpenCode has a built-in **Meta** provider. Run `/connect`,
> pick **Meta** from the "Connect provider" dropdown, paste your [dashboard](https://dev.meta.ai)
> key, then select **Muse Spark 1.1** (the status bar reads **Muse Spark 1.1 · Meta**). The agents
> in `.opencode/` still resolve their model from `opencode.json`, so this is just a convenience for
> exploring interactively — the headless config is what the GitHub Action uses.
