---
name: council
description: >-
  Multi-model deliberation inside Antigravity. Mode "council": independent
  cross-vendor answers, anonymized self-excluded peer review (Accuracy + Insight),
  and Auto Chairman synthesis. Mode "consensus": 2-3 blind participants
  iteratively revise one canonical plan until all endorse it unchanged. Defaults
  to Gemini 4 Carbon + Claude Opus 4.6 via native `swarm` (with automatic
  `run_workflow` fallback). Use when the user asks for a council, second opinions,
  multiple models, peer review, or a consensus plan.
---

# Council

Runs 100% natively inside Antigravity with zero external servers or API keys:

1. **Primary Cross-Vendor Engine (`swarm` + [`scripts/swarm_helper.py`](scripts/swarm_helper.py))**:
   Used whenever the `swarm` tool is available. Pins exact cross-vendor models
   per seat—defaulting to **Gemini 4 Carbon** (`gemini-4-carbon-high`) and
   **Claude Opus 4.6** (`claude-opus-4-6-thinking`)—while keeping all prompts,
   answers, reviews, and drafts in isolated scratch files so nothing leaks onto
   the shared message board.
2. **Fallback Tier Engine (`run_workflow` + [`scripts/council_workflow.py`](scripts/council_workflow.py))**:
   Used automatically if `swarm` is unavailable in the current session (for
   example, when the user's active coordinator model does not expose `swarm`).

---

## 1. Check Available Models & Gather Inputs

1. If the `swarm` tool is in your toolset, call `swarm(action="models", all=True)`
   first to check live model IDs and `quota_remaining` on the user's account.
   - **Default cross-vendor seats**:
     1. `gemini-4-carbon-high` (or `gemini-4-carbon-medium` if `high` is unavailable / `0%` quota)
     2. `claude-opus-4-6-thinking` (or `claude-sonnet-4-6` / `gpt-oss-120b-medium` if Opus is unavailable / `0%` quota)
   - Users can also add a 3rd–5th seat (in `council` mode) or 3rd seat (in `consensus` mode) from any model returned by `swarm(action="models", all=True)` (e.g. `gemini-4-hydrogen-xhigh`, `gpt-oss-120b-medium`, `claude-sonnet-4-6`).
2. Ask one `ask_question` card (skipping anything the user already specified):
   - **Mode**: `(Recommended) Council — Independent answers + anonymized peer review + Chairman` vs `Consensus Plan — Blind iterative plan until unanimous endorsement`
   - **Seats**: `(Recommended) Default: Gemini 4 Carbon + Claude Opus 4.6` vs adding `GPT-OSS 120B` / `Gemini 4 Hydrogen`
   - **Workspace read access**: `(Recommended) Allow read-only workspace access` vs `Prompt-only (no file reads)`

---

## 2A. Running with Cross-Vendor `swarm` (Primary)

Store scratch runs in `<artifact_dir>/scratch/council`. Write the user's question
to `<artifact_dir>/scratch/council/question.txt` (and optional context to `context.txt`).

> **Important `swarm` rule**: `post_message`, `read_board`, and `swarm_wait` unlock on
> the turn *after* your first `swarm(action="add")` in a conversation. On the very
> first `swarm(action="add")` turn, add the initial worker(s) and **end your turn**
> so the worker pings wake you back up with board tools enabled. Do NOT spawn
> `narrator` or `monitor` workers for Council runs.

### Mode 1 (`council`) Steps

1. **Initialize Stage 1**:
   ```bash
   python3 "<skill_dir>/scripts/swarm_helper.py" init \
     --mode council \
     --out-dir "<artifact_dir>/scratch/council" \
     --seats "gemini-4-carbon-high,claude-opus-4-6-thinking" \
     --question-file "<artifact_dir>/scratch/council/question.txt" \
     --allow-tools
   ```
   Call `swarm(action="title", title="Council Deliberation")` and call
   `swarm(action="add", name=..., model=..., brief=...)` for each entry in
   `swarm_add`. Wait until all `expected_outputs` exist (using `swarm_wait` if
   board tools are already active, or ending your turn on first `swarm` creation).

2. **Stage 2 — Anonymized Self-Excluded Peer Review**:
   ```bash
   python3 "<skill_dir>/scripts/swarm_helper.py" prepare-reviews --run-dir "<run_dir>"
   ```
   Send each string in `post_messages` via `post_message`, then call `swarm_wait`
   until all Stage 2 JSON files in `expected_outputs` exist.

3. **Stage 3 — Chairman Synthesis**:
   ```bash
   python3 "<skill_dir>/scripts/swarm_helper.py" prepare-chairman --run-dir "<run_dir>" --chairman auto
   ```
   Send the `post_messages[0]` wakeup via `post_message`, then call `swarm_wait`
   until `stage3_chair.md` exists.

4. **Finalize & Clean Up**:
   ```bash
   python3 "<skill_dir>/scripts/swarm_helper.py" finalize-council --run-dir "<run_dir>"
   ```
   Kill each worker in `workers_to_kill` via `swarm(action="kill", name=...)` so no
   idle workers linger.

### Mode 2 (`consensus`) Steps

1. **Initialize Turn 1 (`Participant 1`)**:
   ```bash
   python3 "<skill_dir>/scripts/swarm_helper.py" init \
     --mode consensus \
     --out-dir "<artifact_dir>/scratch/council" \
     --seats "gemini-4-carbon-high,claude-opus-4-6-thinking" \
     --max-rounds 3 \
     --question-file "<artifact_dir>/scratch/council/question.txt" \
     --allow-tools
   ```
   Call `swarm(action="title", title="Blind Consensus Plan")` and spawn `swarm_add[0]`.
   Wait for `outputs/turn_1.json`.

2. **Advance Rolling Blind Turns (`step-consensus`)**:
   Whenever the current `expected_outputs[0]` file exists, run:
   ```bash
   python3 "<skill_dir>/scripts/swarm_helper.py" step-consensus --run-dir "<run_dir>"
   ```
   - If `"status": "turn_ready"`: execute any `swarm_add` calls (spawning
     `Participant 2` / `Participant 3` lazily on their first turn) and/or send
     `post_messages` to wake an existing participant, then `swarm_wait`.
   - If `"status": "completed"`: kill all workers in `workers_to_kill` via
     `swarm(action="kill", name=...)`.

---

## 2B. Fallback Engine (`run_workflow` when `swarm` is unavailable)

If `swarm` is not in your tool declarations, tell the user briefly that exact
cross-vendor pinning requires a Gemini coordinator model, and run
[`scripts/council_workflow.py`](scripts/council_workflow.py) via `run_workflow`
with `seats: ["inherit", "pro"]`:

```
run_workflow(
  ScriptPath="<skill_dir>/scripts/council_workflow.py",
  Description="Council: <short question>",
  Args={
    "mode": "council" | "consensus",
    "question": "<question>",
    "context": "<context>",
    "seats": ["inherit", "pro"],
    "chairman": "auto",
    "max_rounds": 3,
    "allow_tools": true,
    "out_dir": "<artifact_dir>/scratch/council"
  }
)
```

---

## 3. Present the Artifact

Read `<run_dir>/report.md` and write it as an Artifact (`council_<slug>.md`):
- **`council` mode**: Set `UserFacing: true`, `RequestFeedback: false`.
- **`consensus` mode**: Set `UserFacing: true`, `RequestFeedback: true` so the user
  gets a **Proceed** button to execute the agreed plan right away.

In chat, give a concise 2-3 line headline (winner / consensus outcome) and link
the artifact without duplicating its full contents.
