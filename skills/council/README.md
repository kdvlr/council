# Council — Antigravity Skill

Serverless, cross-vendor multi-LLM deliberation that runs entirely inside
[Antigravity](https://antigravity.google) — no external server, LiteLLM proxy,
or API keys required.

## Modes

- **Council (`council`)** — 2–5 models answer independently in parallel →
  self-excluded shuffled anonymized peer review (`Accuracy 1–10`, `Insight 1–10`,
  qualitative critique) → **Auto (Highest-Rated)** Chairman synthesizes the
  definitive answer.
- **Blind Consensus Plan (`consensus`)** — 2–3 models are randomized into blind
  `Participant 1..3` slots and iteratively refine one standalone canonical
  Markdown plan. Exits early only when all participants endorse the exact same
  plan version unchanged; otherwise `Participant 1` consolidates after `max_rounds`.

## Default Models & Portability

- **Primary Cross-Vendor Engine (`swarm` + `scripts/swarm_helper.py`)**:
  Dynamically checks `swarm(action="models", all=True)` on the user's account and
  defaults to:
  1. **Gemini 4 Carbon** (`gemini-4-carbon-high`)
  2. **Claude Opus 4.6 (Thinking)** (`claude-opus-4-6-thinking`)

  Users can also add `gpt-oss-120b-medium`, `gemini-4-hydrogen-xhigh`, or
  `claude-sonnet-4-6` (or automatic account-aware fallbacks if a model's quota
  is `0%`). All prompts, drafts, and reviews are exchanged via isolated scratch
  files so nothing leaks onto the shared swarm board.
- **Fallback Engine (`run_workflow` + `scripts/council_workflow.py`)**:
  Automatically used when `swarm` is unavailable (e.g., non-Gemini coordinator),
  running `["inherit", "pro"]` model tiers.

## Install

```bash
git clone https://github.com/kdvlr/council.git
mkdir -p ~/.gemini/config/skills
cp -r council/skills/council ~/.gemini/config/skills/council
# Or symlink for automatic updates:
# ln -sfn "$PWD/council/skills/council" ~/.gemini/config/skills/council
```

Start a new conversation and ask:
- *"Run a council on: how should we structure event-sourced projections here?"*
- *"Create a consensus plan for migrating auth to passkeys."*
