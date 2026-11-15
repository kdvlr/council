#!/usr/bin/env python3
"""Helper state machine for running Council (Mode 1 & Mode 2) over Antigravity `swarm`.

Keeps all prompts, answers, anonymized peer reviews, and blind consensus drafts in
local files under `<out_dir>/<mode>-<timestamp>-<tag>/` so nothing leaks onto the
shared swarm message board. The swarm board is used strictly as a wakeup doorbell.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import random
import re
import secrets
import sys
import time
from typing import Any, Dict, List


DISPLAY_NAMES = {
    "claude-opus-4-6-thinking": "Claude Opus 4.6 (Thinking)",
    "claude-sonnet-4-6": "Claude Sonnet 4.6 (Thinking)",
    "gemini-4-carbon-high": "Gemini 4 Carbon (High)",
    "gemini-4-carbon-medium": "Gemini 4 Carbon (Medium)",
    "gemini-4-carbon-low": "Gemini 4 Carbon (Low)",
    "gemini-4-hydrogen-xhigh": "Gemini 4 Hydrogen (XHigh)",
    "gemini-4-hydrogen-high": "Gemini 4 Hydrogen (High)",
    "gemini-4-hydrogen-medium": "Gemini 4 Hydrogen (Medium)",
    "gemini-4-hydrogen-low": "Gemini 4 Hydrogen (Low)",
    "gemini-4-argon-high": "Gemini 4 Argon (High)",
    "gemini-4-argon-medium": "Gemini 4 Argon (Medium)",
    "gemini-4-argon-low": "Gemini 4 Argon (Low)",
    "gemini-3.8-flash-high": "Gemini 3.8 Flash (High)",
    "gemini-3.8-flash-medium": "Gemini 3.8 Flash (Medium)",
    "gemini-3.8-flash-low": "Gemini 3.8 Flash (Low)",
    "gpt-oss-120b-medium": "GPT-OSS 120B (Medium)",
}


def pretty_model(model_id: str) -> str:
    return DISPLAY_NAMES.get(model_id, model_id)


def seat_label(idx: int, seats: List[str]) -> str:
    return f"Seat {idx + 1} — {pretty_model(seats[idx])}"


def letters(n: int) -> List[str]:
    return [chr(ord("A") + i) for i in range(n)]


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path: str, content: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def load_state(run_dir: str) -> Dict[str, Any]:
    return json.loads(read_text(os.path.join(run_dir, "state.json")))


def save_state(run_dir: str, state: Dict[str, Any]) -> None:
    write_text(os.path.join(run_dir, "state.json"), json.dumps(state, indent=2))


def parse_json_lenient(raw: str) -> Any:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for open_ch, close_ch in (("[", "]"), ("{", "}")):
            start = text.find(open_ch)
            end = text.rfind(close_ch)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    continue
        raise


def tools_instruction(allow_tools: bool) -> str:
    if allow_tools:
        return (
            "You may inspect files in the workspace (read-only) if helpful for accuracy, "
            "but NEVER edit workspace files (other than writing your designated output file) "
            "and NEVER call `read_board` or `swarm`."
        )
    return (
        "Answer strictly from the prompt below without reading workspace files. "
        "Only use `read_file` on your assigned prompt file, `write_file` on your assigned "
        "output file, and `post_message` for your 1-line completion ping. NEVER call `read_board` or `swarm`."
    )


def worker_brief(worker_name: str, prompt_path: str, output_path: str, ping_tag: str) -> str:
    return (
        f"You are an isolated deliberation participant (`{worker_name}`). "
        f"STRICT RULES: Never call `read_board` and never call `swarm`. Never post any "
        f"answer, critique, or plan text to the board. "
        f"1) Read `{prompt_path}`. "
        f"2) Write your complete output ONLY to `{output_path}` (overwrite if needed). "
        f"3) Call `post_message` with exact text `@coordinator {ping_tag}` and end your turn."
    )


def wakeup_message(worker_name: str, prompt_path: str, output_path: str, ping_tag: str) -> str:
    return (
        f"@{worker_name} Read `{prompt_path}`, follow its instructions, write your output "
        f"ONLY to `{output_path}` (never to the board, never call `read_board`), then "
        f"`post_message` exact text `@coordinator {ping_tag}`."
    )


# ─────────────────────────────── INIT ───────────────────────────────


def cmd_init(args: argparse.Namespace) -> None:
    mode = args.mode.lower()
    if mode not in ("council", "consensus"):
        raise SystemExit("mode must be 'council' or 'consensus'")

    seats = [s.strip() for s in args.seats.split(",") if s.strip()]
    if mode == "council" and not (2 <= len(seats) <= 5):
        raise SystemExit("council mode requires 2 to 5 seats")
    if mode == "consensus" and not (2 <= len(seats) <= 3):
        raise SystemExit("consensus mode requires 2 or 3 seats")

    question = read_text(args.question_file).strip() if args.question_file else (args.question or "").strip()
    if not question:
        raise SystemExit("question is required")
    context = read_text(args.context_file).strip() if args.context_file else (args.context or "").strip()

    tag = secrets.token_hex(2)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = os.path.abspath(os.path.join(args.out_dir, f"{mode}-{stamp}-{tag}"))
    os.makedirs(os.path.join(run_dir, "prompts"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "outputs"), exist_ok=True)

    ctx_block = f"\n\n<context>\n{context}\n</context>" if context else ""
    t_note = tools_instruction(args.allow_tools)

    if mode == "council":
        workers = [f"seat{i}-{tag}" for i in range(len(seats))]
        add_calls = []
        expected_outputs = []
        for i, model_id in enumerate(seats):
            p_path = os.path.join(run_dir, "prompts", f"stage1_{i}.md")
            o_path = os.path.join(run_dir, "outputs", f"stage1_{i}.md")
            prompt = (
                "# Independent Question\n\n"
                "Answer the question below thoroughly, accurately, and insightfully in Markdown. "
                "If a diagram clarifies your answer, use a ```mermaid fenced block and always quote "
                'node labels containing parentheses or special characters (e.g. `A["Step (1)"]`).\n\n'
                f"{t_note}{ctx_block}\n\n"
                f"<question>\n{question}\n</question>\n\n"
                f"Write ONLY your Markdown answer to `{o_path}`."
            )
            write_text(p_path, prompt)
            expected_outputs.append(o_path)
            add_calls.append(
                {
                    "name": workers[i],
                    "model": model_id,
                    "brief": worker_brief(workers[i], p_path, o_path, f"stage1 {i} done"),
                }
            )

        state = {
            "mode": "council",
            "tag": tag,
            "run_dir": run_dir,
            "question": question,
            "context": context,
            "allow_tools": args.allow_tools,
            "seats": seats,
            "workers": workers,
            "stage": "stage1",
        }
        save_state(run_dir, state)
        print(
            json.dumps(
                {
                    "status": "stage1_ready",
                    "run_dir": run_dir,
                    "swarm_add": add_calls,
                    "expected_outputs": expected_outputs,
                },
                indent=2,
            )
        )
        return

    # Consensus mode: shuffle seats into blind Participant 1..K slots
    slot_order = list(range(len(seats)))
    random.shuffle(slot_order)
    workers = [f"p{p + 1}-{tag}" for p in range(len(seats))]
    p1_model = seats[slot_order[0]]

    p_path = os.path.join(run_dir, "prompts", "turn_1.md")
    o_path = os.path.join(run_dir, "outputs", "turn_1.json")
    prompt = (
        "# Planning Session — Turn 1\n\n"
        "You are working one-on-one to craft a rigorous, production-grade plan in Markdown.\n"
        f"{t_note}{ctx_block}\n\n"
        f"<request>\n{question}\n</request>\n\n"
        "Write a JSON object (no surrounding prose) to "
        f"`{o_path}` with these exact keys:\n"
        '{\n'
        '  "revision_notes": "Key design choices and rationale for this initial draft.",\n'
        '  "plan": "<Complete standalone canonical Markdown plan>",\n'
        '  "agreed": false\n'
        '}\n'
    )
    write_text(p_path, prompt)

    state = {
        "mode": "consensus",
        "tag": tag,
        "run_dir": run_dir,
        "question": question,
        "context": context,
        "allow_tools": args.allow_tools,
        "max_rounds": args.max_rounds,
        "seats": seats,
        "slot_order": slot_order,  # participant index p -> seat index
        "workers": workers,
        "spawned_participants": [0],
        "turns_used": [0] * len(seats),
        "turn_number": 1,
        "active_participant": 0,
        "current_plan": "",
        "version": 0,
        "endorsed": [],
        "consolidation_pending": False,
        "history": [],
    }
    save_state(run_dir, state)
    print(
        json.dumps(
            {
                "status": "turn_ready",
                "run_dir": run_dir,
                "turn": 1,
                "swarm_add": [
                    {
                        "name": workers[0],
                        "model": p1_model,
                        "brief": worker_brief(workers[0], p_path, o_path, "turn 1 done"),
                    }
                ],
                "post_messages": [],
                "expected_outputs": [o_path],
            },
            indent=2,
        )
    )


# ─────────────────────────── MODE 1 STAGES ───────────────────────────


def cmd_prepare_reviews(args: argparse.Namespace) -> None:
    state = load_state(args.run_dir)
    seats = state["seats"]
    workers = state["workers"]
    n = len(seats)
    ctx_block = f"\n\n<context>\n{state['context']}\n</context>" if state["context"] else ""
    t_note = tools_instruction(state["allow_tools"])

    answers = []
    for i in range(n):
        ans_path = os.path.join(args.run_dir, "outputs", f"stage1_{i}.md")
        if not os.path.exists(ans_path):
            raise SystemExit(f"Missing Stage 1 output: {ans_path}")
        answers.append(read_text(ans_path).strip())

    review_mappings: Dict[str, Dict[str, int]] = {}
    post_messages = []
    expected_outputs = []

    for r in range(n):
        others = [j for j in range(n) if j != r]
        random.shuffle(others)
        mapping = dict(zip(letters(len(others)), others))
        review_mappings[str(r)] = mapping

        responses_block = "\n\n".join(
            f'<response label="{lab}">\n{answers[j]}\n</response>' for lab, j in mapping.items()
        )
        p_path = os.path.join(args.run_dir, "prompts", f"stage2_{r}.md")
        o_path = os.path.join(args.run_dir, "outputs", f"stage2_{r}.json")
        labels_str = ", ".join(f'"{lab}"' for lab in mapping)
        prompt = (
            "# Anonymized Peer Review\n\n"
            "Evaluate each anonymous response below strictly on technical merit.\n"
            "- **accuracy** (integer 1-10): factual correctness, absence of bugs or hallucinations.\n"
            "- **insight** (integer 1-10): depth, architectural judgment, non-obvious value.\n"
            "- **critique**: concise strengths, flaws, and omissions.\n\n"
            f"{t_note}{ctx_block}\n\n"
            f"<question>\n{state['question']}\n</question>\n\n"
            f"{responses_block}\n\n"
            f"Write ONLY a valid JSON array to `{o_path}` with one object per label ({labels_str}):\n"
            "[\n"
            '  {"label": "A", "accuracy": 8, "insight": 7, "critique": "..."}\n'
            "]\n"
        )
        write_text(p_path, prompt)
        expected_outputs.append(o_path)
        post_messages.append(wakeup_message(workers[r], p_path, o_path, f"stage2 {r} done"))

    state["answers"] = answers
    state["review_mappings"] = review_mappings
    state["stage"] = "stage2"
    save_state(args.run_dir, state)

    print(
        json.dumps(
            {
                "status": "stage2_ready",
                "post_messages": post_messages,
                "expected_outputs": expected_outputs,
            },
            indent=2,
        )
    )


def cmd_prepare_chairman(args: argparse.Namespace) -> None:
    state = load_state(args.run_dir)
    seats = state["seats"]
    workers = state["workers"]
    answers = state["answers"]
    review_mappings = state["review_mappings"]
    n = len(seats)

    reviews: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(n)}
    for r in range(n):
        o_path = os.path.join(args.run_dir, "outputs", f"stage2_{r}.json")
        if not os.path.exists(o_path):
            raise SystemExit(f"Missing Stage 2 output: {o_path}")
        items = parse_json_lenient(read_text(o_path))
        if isinstance(items, dict) and "reviews" in items:
            items = items["reviews"]
        mapping = review_mappings[str(r)]
        for item in items:
            lab = str(item.get("label", "")).strip().upper()[:1]
            if lab not in mapping:
                continue
            target = mapping[lab]
            reviews[target].append(
                {
                    "reviewer": r,
                    "accuracy": max(1, min(10, int(round(float(item["accuracy"]))))),
                    "insight": max(1, min(10, int(round(float(item["insight"]))))),
                    "critique": str(item.get("critique", "")).strip(),
                }
            )

    leaderboard = []
    for i in range(n):
        rs = reviews[i]
        acc = sum(x["accuracy"] for x in rs) / len(rs) if rs else 0.0
        ins = sum(x["insight"] for x in rs) / len(rs) if rs else 0.0
        leaderboard.append(
            {
                "seat": i,
                "model": seats[i],
                "display_name": pretty_model(seats[i]),
                "accuracy": round(acc, 2),
                "insight": round(ins, 2),
                "total": round(acc + ins, 2),
                "n": len(rs),
            }
        )
    leaderboard.sort(key=lambda b: (b["total"], b["accuracy"], b["insight"]), reverse=True)

    chair_arg = (args.chairman or "auto").strip().lower()
    chair_idx = leaderboard[0]["seat"] if chair_arg == "auto" else int(chair_arg)

    order = list(range(n))
    random.shuffle(order)
    anon = dict(zip(letters(n), order))
    sections = []
    for lab, j in anon.items():
        crit_lines = "\n".join(
            f"- Accuracy {x['accuracy']}/10, Insight {x['insight']}/10: {x['critique']}"
            for x in reviews[j]
        )
        sections.append(
            f'<response label="{lab}">\n{answers[j]}\n</response>\n'
            f'<peer_reviews label="{lab}">\n{crit_lines or "(none)"}\n</peer_reviews>'
        )

    ctx_block = f"\n\n<context>\n{state['context']}\n</context>" if state["context"] else ""
    t_note = tools_instruction(state["allow_tools"])
    p_path = os.path.join(args.run_dir, "prompts", "stage3_chair.md")
    o_path = os.path.join(args.run_dir, "outputs", "stage3_chair.md")
    prompt = (
        "# Chairman Synthesis\n\n"
        "Synthesize the single definitive, authoritative final answer to the question below "
        "using the anonymous panel responses and peer reviews.\n"
        "- Incorporate the strongest insights and verified details.\n"
        "- Correct any flaws or omissions identified in the peer reviews.\n"
        "- Resolve disagreements explicitly.\n"
        "- Do NOT mention 'Response A/B', scores, or the existence of a panel—present a clean, "
        "standalone answer in Markdown.\n\n"
        f"{t_note}{ctx_block}\n\n"
        f"<question>\n{state['question']}\n</question>\n\n"
        + "\n\n".join(sections)
        + f"\n\nWrite ONLY the final synthesized Markdown answer to `{o_path}`."
    )
    write_text(p_path, prompt)

    state["reviews"] = {str(k): v for k, v in reviews.items()}
    state["leaderboard"] = leaderboard
    state["chairman"] = chair_idx
    state["chairman_mode"] = chair_arg
    state["stage"] = "stage3"
    save_state(args.run_dir, state)

    print(
        json.dumps(
            {
                "status": "stage3_ready",
                "chairman_seat": chair_idx,
                "chairman_model": seats[chair_idx],
                "leaderboard": leaderboard,
                "post_messages": [
                    wakeup_message(workers[chair_idx], p_path, o_path, "stage3 chair done")
                ],
                "expected_outputs": [o_path],
            },
            indent=2,
        )
    )


def cmd_finalize_council(args: argparse.Namespace) -> None:
    state = load_state(args.run_dir)
    seats = state["seats"]
    answers = state["answers"]
    reviews = {int(k): v for k, v in state["reviews"].items()}
    board = state["leaderboard"]
    chair = state["chairman"]
    auto_note = " *(Auto — Highest Peer-Rated)*" if state.get("chairman_mode") == "auto" else ""

    chair_path = os.path.join(args.run_dir, "outputs", "stage3_chair.md")
    if not os.path.exists(chair_path):
        raise SystemExit(f"Missing Chairman output: {chair_path}")
    final_answer = read_text(chair_path).strip()

    md = [
        f"# Council Deliberation — {state['question'][:80]}",
        "",
        f"> [!IMPORTANT]\n> **Chairman Synthesis**: **{seat_label(chair, seats)}**{auto_note}",
        "",
        final_answer,
        "",
        "---",
        "",
        "## Peer Review Leaderboard",
        "",
        "| Rank | Seat | Accuracy (1–10) | Insight (1–10) | Combined (/20) | Reviews |",
        "| :--- | :--- | :---: | :---: | :---: | :---: |",
    ]
    for rank, b in enumerate(board, 1):
        md.append(
            f"| {rank} | {seat_label(b['seat'], seats)} | {b['accuracy']:.1f} | "
            f"{b['insight']:.1f} | **{b['total']:.1f}** | {b['n']} |"
        )

    md += ["", "## Individual Responses & Anonymized Critiques", "", "````carousel"]
    for i in range(len(seats)):
        if i > 0:
            md.append("<!-- slide -->")
        md.append(f"### {seat_label(i, seats)}\n\n{answers[i]}\n\n#### Peer Critiques Received\n")
        for r in reviews[i]:
            md.append(
                f"- **{seat_label(r['reviewer'], seats)}** *(Accuracy {r['accuracy']}/10, "
                f"Insight {r['insight']}/10)*: {r['critique']}"
            )
    md.append("````")

    report_path = write_text(os.path.join(args.run_dir, "report.md"), "\n".join(md) + "\n")
    result = {
        "mode": "council",
        "question": state["question"],
        "seats": seats,
        "chairman": chair,
        "leaderboard": board,
        "answers": answers,
        "reviews": state["reviews"],
        "final": final_answer,
    }
    write_text(os.path.join(args.run_dir, "result.json"), json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                "status": "completed",
                "report": report_path,
                "workers_to_kill": state["workers"],
            },
            indent=2,
        )
    )


# ─────────────────────────── MODE 2 STEPPER ───────────────────────────


def render_consensus_report(state: Dict[str, Any], consensus: bool) -> str:
    seats = state["seats"]
    slot_order = state["slot_order"]
    history = state["history"]
    plan = state["current_plan"]
    version = state["version"]

    badge = (
        f"> [!TIP]\n> **Unanimous Blind Consensus** reached on **v{version}** after {len(history)} turns."
        if consensus
        else f"> [!WARNING]\n> **Max Rounds Reached** — Consolidated by `Participant 1` into **v{version}** after {len(history)} turns."
    )
    md = [
        f"# Consensus Plan — {state['question'][:80]}",
        "",
        badge,
        "",
        plan,
        "",
        "---",
        "",
        "<details><summary><strong>Reveal Blind Participant Mapping (Spoiler)</strong></summary>",
        "",
    ]
    for p_idx, seat_idx in enumerate(slot_order):
        md.append(f"- **Participant {p_idx + 1}**: {pretty_model(seats[seat_idx])} (`{seats[seat_idx]}`)")
    md += ["", "</details>", "", "## Deliberation History", ""]

    prev_plan = ""
    for item in history:
        tag = (
            "Consolidation"
            if item.get("consolidation")
            else ("Endorsed Unchanged" if item["agreed"] else "Revised Plan")
        )
        md.append(
            f"### Turn {item['turn']} · Participant {item['participant']} → v{item['version']} ({tag})\n\n"
            f"{item['notes']}\n"
        )
        if prev_plan and item["plan"] != prev_plan:
            diff_lines = "\n".join(
                difflib.unified_diff(
                    prev_plan.splitlines(),
                    item["plan"].splitlines(),
                    fromfile="previous",
                    tofile=f"v{item['version']}",
                    lineterm="",
                )
            )
            md.append(f"<details><summary>View Plan Diff</summary>\n\n```diff\n{diff_lines}\n```\n\n</details>\n")
        prev_plan = item["plan"]
    return "\n".join(md) + "\n"


def cmd_step_consensus(args: argparse.Namespace) -> None:
    state = load_state(args.run_dir)
    seats = state["seats"]
    slot_order = state["slot_order"]
    workers = state["workers"]
    k = len(seats)
    turn = state["turn_number"]
    p = state["active_participant"]

    out_path = os.path.join(args.run_dir, "outputs", f"turn_{turn}.json")
    if not os.path.exists(out_path):
        raise SystemExit(f"Missing Turn {turn} output: {out_path}")

    parsed = parse_json_lenient(read_text(out_path))
    new_plan = str(parsed.get("plan", "")).strip()
    notes = str(parsed.get("revision_notes", "")).strip()
    claimed_agreed = bool(parsed.get("agreed", False))

    if not new_plan:
        raise SystemExit(f"Turn {turn} returned an empty plan")

    if state["consolidation_pending"]:
        state["version"] += 1
        state["current_plan"] = new_plan
        state["history"].append(
            {
                "turn": turn,
                "participant": p + 1,
                "notes": notes,
                "plan": new_plan,
                "agreed": True,
                "version": state["version"],
                "consolidation": True,
            }
        )
        save_state(args.run_dir, state)
        report_md = render_consensus_report(state, consensus=False)
        report_path = write_text(os.path.join(args.run_dir, "report.md"), report_md)
        write_text(
            os.path.join(args.run_dir, "result.json"),
            json.dumps({**state, "consensus": False}, indent=2),
        )
        print(
            json.dumps(
                {
                    "status": "completed",
                    "consensus": False,
                    "report": report_path,
                    "workers_to_kill": [workers[i] for i in state["spawned_participants"]],
                },
                indent=2,
            )
        )
        return

    state["turns_used"][p] += 1
    if turn == 1:
        state["current_plan"] = new_plan
        state["version"] = 1
        state["endorsed"] = [p]
        effective_agreed = False
    else:
        changed = norm_text(new_plan) != norm_text(state["current_plan"])
        if claimed_agreed and not changed:
            if p not in state["endorsed"]:
                state["endorsed"].append(p)
            effective_agreed = True
        else:
            state["current_plan"] = new_plan
            state["version"] += 1
            state["endorsed"] = [p]
            effective_agreed = False

    state["history"].append(
        {
            "turn": turn,
            "participant": p + 1,
            "notes": notes,
            "plan": state["current_plan"],
            "agreed": effective_agreed,
            "version": state["version"],
        }
    )

    if len(state["endorsed"]) == k:
        save_state(args.run_dir, state)
        report_md = render_consensus_report(state, consensus=True)
        report_path = write_text(os.path.join(args.run_dir, "report.md"), report_md)
        write_text(
            os.path.join(args.run_dir, "result.json"),
            json.dumps({**state, "consensus": True}, indent=2),
        )
        print(
            json.dumps(
                {
                    "status": "completed",
                    "consensus": True,
                    "report": report_path,
                    "workers_to_kill": [workers[i] for i in state["spawned_participants"]],
                },
                indent=2,
            )
        )
        return

    # Find next participant with remaining turns
    next_p = None
    for offset in range(1, k + 1):
        cand = (p + offset) % k
        if state["turns_used"][cand] < state["max_rounds"]:
            next_p = cand
            break

    ctx_block = f"\n\n<context>\n{state['context']}\n</context>" if state["context"] else ""
    t_note = tools_instruction(state["allow_tools"])
    next_turn = turn + 1
    p_path = os.path.join(args.run_dir, "prompts", f"turn_{next_turn}.md")
    o_path = os.path.join(args.run_dir, "outputs", f"turn_{next_turn}.json")

    if next_p is None:
        # Deadlock fallback -> Participant 1 consolidates
        state["consolidation_pending"] = True
        state["turn_number"] = next_turn
        state["active_participant"] = 0
        prompt = (
            f"# Final Plan Consolidation — Turn {next_turn}\n\n"
            "We have reached the maximum revision budget. Produce the final consolidated "
            "standalone Markdown plan from the latest draft below: preserve the strongest "
            "decisions, resolve any remaining tensions explicitly in a concise "
            "'Key Trade-offs & Decisions' section, and set `agreed` to `true`.\n\n"
            f"<draft version=\"{state['version']}\">\n{state['current_plan']}\n</draft>\n\n"
            f"Write ONLY a valid JSON object to `{o_path}`:\n"
            '{\n'
            '  "revision_notes": "Summary of final consolidation",\n'
            '  "plan": "<Complete standalone canonical Markdown plan>",\n'
            '  "agreed": true\n'
            '}\n'
        )
        write_text(p_path, prompt)
        save_state(args.run_dir, state)
        print(
            json.dumps(
                {
                    "status": "turn_ready",
                    "turn": next_turn,
                    "consolidation": True,
                    "swarm_add": [],
                    "post_messages": [
                        wakeup_message(workers[0], p_path, o_path, f"turn {next_turn} done")
                    ],
                    "expected_outputs": [o_path],
                },
                indent=2,
            )
        )
        return

    first_time = next_p not in state["spawned_participants"]
    intro = (
        "You are working one-on-one to craft and refine a rigorous, production-grade plan.\n"
        f"{t_note}{ctx_block}\n\n<request>\n{state['question']}\n</request>\n\n"
        if first_time
        else ""
    )
    prompt = (
        f"# Plan Review — Turn {next_turn} (Draft v{state['version']})\n\n"
        f"{intro}"
        "Below is the latest draft of the plan. Evaluate it critically on technical merit, "
        "completeness, edge cases, sequencing, and clarity.\n"
        "- Always return the COMPLETE standalone canonical Markdown plan in `plan` (never a diff or partial).\n"
        "- Set `agreed` to `true` ONLY if you endorse this exact draft as-is with zero modifications.\n"
        "- If you improve or change anything at all, set `agreed` to `false`.\n\n"
        f"<draft version=\"{state['version']}\">\n{state['current_plan']}\n</draft>\n\n"
        f"Write ONLY a valid JSON object to `{o_path}`:\n"
        '{\n'
        '  "revision_notes": "What you changed and why (or why you endorse unchanged)",\n'
        '  "plan": "<Complete standalone canonical Markdown plan>",\n'
        '  "agreed": false\n'
        '}\n'
    )
    write_text(p_path, prompt)

    swarm_add = []
    post_messages = []
    if first_time:
        state["spawned_participants"].append(next_p)
        swarm_add.append(
            {
                "name": workers[next_p],
                "model": seats[slot_order[next_p]],
                "brief": worker_brief(workers[next_p], p_path, o_path, f"turn {next_turn} done"),
            }
        )
    else:
        post_messages.append(
            wakeup_message(workers[next_p], p_path, o_path, f"turn {next_turn} done")
        )

    state["turn_number"] = next_turn
    state["active_participant"] = next_p
    save_state(args.run_dir, state)
    print(
        json.dumps(
            {
                "status": "turn_ready",
                "turn": next_turn,
                "swarm_add": swarm_add,
                "post_messages": post_messages,
                "expected_outputs": [o_path],
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Council Swarm State Helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--mode", required=True, choices=["council", "consensus"])
    p_init.add_argument("--out-dir", required=True)
    p_init.add_argument(
        "--seats",
        default="gemini-4-carbon-high,claude-opus-4-6-thinking",
        help="Comma-separated swarm model IDs",
    )
    p_init.add_argument("--question", default="")
    p_init.add_argument("--question-file", default="")
    p_init.add_argument("--context", default="")
    p_init.add_argument("--context-file", default="")
    p_init.add_argument("--max-rounds", type=int, default=3)
    p_init.add_argument("--allow-tools", action="store_true", default=False)
    p_init.set_defaults(func=cmd_init)

    p_rev = sub.add_parser("prepare-reviews")
    p_rev.add_argument("--run-dir", required=True)
    p_rev.set_defaults(func=cmd_prepare_reviews)

    p_chair = sub.add_parser("prepare-chairman")
    p_chair.add_argument("--run-dir", required=True)
    p_chair.add_argument("--chairman", default="auto")
    p_chair.set_defaults(func=cmd_prepare_chairman)

    p_fin = sub.add_parser("finalize-council")
    p_fin.add_argument("--run-dir", required=True)
    p_fin.set_defaults(func=cmd_finalize_council)

    p_step = sub.add_parser("step-consensus")
    p_step.add_argument("--run-dir", required=True)
    p_step.set_defaults(func=cmd_step_consensus)

    parsed = parser.parse_args()
    parsed.func(parsed)


if __name__ == "__main__":
    main()
