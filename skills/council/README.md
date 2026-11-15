# Council — Antigravity Skill

Multi-model deliberation that runs entirely inside [Antigravity](https://antigravity.google)
using built-in `run_workflow` agents. No server, API keys, or LiteLLM needed.

- **council** — N seats answer independently → each anonymously reviews the
  others (Accuracy 1-10, Insight 1-10, critique; own answer excluded, order
  shuffled) → the highest-rated seat (or a chosen chairman) writes the final answer.
- **consensus** — 2-3 blind participants take turns revising one plan; each
  believes it is working 1-on-1 with the user. Ends when everyone endorses the
  same version unchanged, or Participant 1 consolidates after `max_rounds`.

## Install

```bash
git clone https://github.com/kdvlr/council.git
mkdir -p ~/.gemini/config/skills
cp -r council/skills/council ~/.gemini/config/skills/council
# or symlink to keep it updated:  ln -s "$PWD/council/skills/council" ~/.gemini/config/skills/council
```

Restart Antigravity (or start a new conversation), then ask e.g.
*"Run a council on: should we use SQLite or Postgres here?"* or
*"Get a consensus plan for migrating auth to OIDC."*

## Seats

Seats are `run_workflow` model tiers: `inherit` (your selected model — e.g.
pick Claude Opus in the model picker), `pro`, `flash`, `flash_lite`. Mixing
tiers gives the most diverse opinions.

## Output

Each run writes `report.md` and `result.json` to `out_dir`; the agent turns
the report into an Antigravity artifact (consensus plans get a **Proceed**
button to execute them).

## Requirements

Antigravity with the `run_workflow` tool and Python 3.8+ on `PATH`.
Each seat turn is a full agent run against your quota.
