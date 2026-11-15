---
name: council
description: >-
  Multi-model deliberation inside Antigravity. Mode "council": several models
  answer independently, anonymously peer-review each other (Accuracy + Insight),
  and the highest-rated model synthesizes a final answer. Mode "consensus":
  2-3 blind participants iteratively revise one plan until all endorse it.
  Use when the user asks for a council, second opinions, multiple models,
  peer review of answers, or a consensus / agreed plan.
---

# Council

Runs entirely on Antigravity's built-in agents via `run_workflow` — no server,
API keys, or external services. The engine is
[`scripts/council_workflow.py`](scripts/council_workflow.py) in this skill's
directory.

## 1. Gather inputs

Ask with **one `ask_question` card** (skip anything the user already stated):

1. **Mode** — `council` (independent answers + peer review + chairman) or
   `consensus` (blind iterative plan agreement).
2. **Seats** — which model tiers sit on the council (see *Seats* below).
   Default `["inherit", "pro", "flash"]`.
3. **Workspace access** — may seats read the current workspace for context
   (default yes, read-only)?

Then collect the question and any context the seats need. Seats start fresh
and never see this conversation, so put relevant facts (file paths, errors,
constraints, prior decisions) into `context`. Keep it focused.

## 2. Seats

Each seat is a `run_workflow` model tier:

| Tier | Meaning |
|---|---|
| `inherit` | The model the user has selected for this conversation |
| `pro` | Antigravity's large tier |
| `flash` | Antigravity's fast tier |
| `flash_lite` | Antigravity's lightest tier |

Diversity comes from mixing tiers. Repeating a tier is allowed (independent
samples of the same model still disagree usefully), but tell the user that
distinct tiers give more diverse opinions. If the user names a specific model
(e.g. "use Opus"), explain that it is reached by selecting that model in the
model picker and using the `inherit` seat.

Limits: `council` needs 2-5 seats; `consensus` needs 2-3.

## 3. Run

Tell the user how many agent runs this will cost (council with `n` seats:
`2n + 1`; consensus: up to `seats × max_rounds + 1` turns), then call:

```
run_workflow(
  ScriptPath="<this skill dir>/scripts/council_workflow.py",
  Description="Council: <short question>",
  Args={
    "mode": "council" | "consensus",
    "question": "<the question or planning request>",
    "context": "<relevant facts, file paths, constraints>",
    "seats": ["inherit", "pro", "flash"],
    "chairman": "auto",          # council only; or a 0-based seat index
    "max_rounds": 3,             # consensus only
    "allow_tools": true,
    "out_dir": "<artifact dir>/scratch/council"
  }
)
```

It runs in the background; end your turn and wait for the notification.

## 4. Present the result

The script prints `{"report": ".../report.md", "run_dir": ...}`. Read
`report.md` and write it as an artifact (`council_<slug>.md`):

- **council**: final answer, leaderboard table, carousel of individual answers
  with their peer reviews.
- **consensus**: the agreed plan, a `<details>` spoiler revealing which tier
  played each participant, and the per-turn revision notes with diffs. Create
  it with `RequestFeedback: true` so the user can click **Proceed** to execute
  the plan.

In chat, give only the headline (winner / consensus status) and link the
artifact. Don't re-summarize it.

## Guarantees and limits

- **Blindness**: workflow agents never see the script, each other, or this
  conversation. Peer review is self-excluded, shuffled, and relabeled per
  reviewer. In `consensus`, each participant believes it is iterating 1-on-1
  with the user; peer revisions are relayed as the user's draft.
- **Consensus rule**: consensus is reached only when every participant
  endorses the same version with zero text changes; any edit resets
  endorsements. After `max_rounds` turns each, Participant 1 consolidates.
- **Safety**: seats are told not to modify files or change state. Nothing is
  executed until the user proceeds on the plan.
- **Cost**: every seat turn is a full agent run against the user's quota.
