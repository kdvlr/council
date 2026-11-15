# Council — multi-model deliberation as an Antigravity `run_workflow` script.
#
# Run with:  run_workflow(ScriptPath="<skill>/scripts/council_workflow.py", Args={...})
#
# Args (all optional except `question`):
#   mode        "council" (Mode 1, default) | "consensus" (Mode 2)
#   question    the user's question / planning request (string, required)
#   context     extra context pasted into every prompt (string)
#   seats       list of model tiers, one per seat. Tiers: "inherit", "pro",
#               "flash", "flash_lite". Default: ["inherit", "pro", "flash"]
#   chairman    "auto" (highest peer-rated seat, default) or a seat index (0-based)
#   max_rounds  Mode 2 only: max turns per participant (default 3)
#   out_dir     directory for report.md + result.json (default: ./council_runs)
#   allow_tools true (default) lets seats read the workspace for context;
#               false asks them to answer from the prompt alone.
#
# Agents never see the script or each other; all cross-seat information is
# relayed by this script, anonymized and shuffled.

import difflib
import json
import os
import random
import re
import time

A = args if isinstance(globals().get("args"), dict) else {}  # noqa: F821
QUESTION = (A.get("question") or "").strip()
if not QUESTION:
    raise ValueError("Args.question is required")

MODE = (A.get("mode") or "council").lower()
CONTEXT = (A.get("context") or "").strip()
VALID_TIERS = {"inherit", "pro", "flash", "flash_lite"}
SEATS = A.get("seats") or ["inherit", "pro", "flash"]
for s in SEATS:
    if s not in VALID_TIERS:
        raise ValueError(f"Unknown seat tier {s!r}; use one of {sorted(VALID_TIERS)}")
MAX_ROUNDS = int(A.get("max_rounds") or 3)
ALLOW_TOOLS = A.get("allow_tools", True)
OUT_DIR = A.get("out_dir") or os.path.join(os.getcwd(), "council_runs")
RUN_ID = time.strftime("%Y%m%d-%H%M%S")
RUN_DIR = os.path.join(OUT_DIR, f"{MODE}-{RUN_ID}")
os.makedirs(RUN_DIR, exist_ok=True)

TOOLS_NOTE = (
    "You may read files in the current workspace if it helps you answer accurately, "
    "but do NOT modify any files and do NOT run commands that change state."
    if ALLOW_TOOLS
    else "Answer from the information in this message alone. Do not use tools other than `finish`."
)
CTX_BLOCK = f"\n\n<context>\n{CONTEXT}\n</context>" if CONTEXT else ""

STR = {"type": "string"}


def seat_label(i):
    return f"Seat {i + 1} ({SEATS[i]})"


def letters(n):
    return [chr(ord("A") + k) for k in range(n)]


def write(name, text):
    p = os.path.join(RUN_DIR, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


# ─────────────────────────────── Mode 1 ───────────────────────────────
async def run_council():
    n = len(SEATS)
    if n < 2:
        raise ValueError("Council mode needs at least 2 seats")

    phase("Stage 1 — Independent answers")
    answer_prompt = (
        "Independent answer\n\n"
        "Answer the question below as well as you can. Be accurate, specific, and "
        "insightful. Use Markdown. If a diagram helps, use a ```mermaid block and quote "
        "node labels containing punctuation. " + TOOLS_NOTE + CTX_BLOCK +
        f"\n\n<question>\n{QUESTION}\n</question>\n\n"
        "Return your full answer (Markdown string) via `finish`."
    )
    answers = await parallel(
        list(range(n)),
        lambda i: agent(answer_prompt, schema=STR, role=f"Answer · {seat_label(i)}", model=SEATS[i]),
    )
    log(f"Collected {n} independent answers")

    phase("Stage 2 — Anonymized peer review")
    review_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "accuracy": {"type": "integer", "minimum": 1, "maximum": 10},
                "insight": {"type": "integer", "minimum": 1, "maximum": 10},
                "critique": {"type": "string"},
            },
            "required": ["label", "accuracy", "insight", "critique"],
        },
    }
    # Each reviewer sees every answer except its own, shuffled and relabeled.
    plans = []
    for r in range(n):
        others = [j for j in range(n) if j != r]
        random.shuffle(others)
        mapping = dict(zip(letters(len(others)), others))
        plans.append((r, mapping))

    def review_prompt(mapping):
        body = "\n\n".join(
            f"<response label=\"{lab}\">\n{answers[j]}\n</response>" for lab, j in mapping.items()
        )
        return (
            "Peer review\n\n"
            "Several anonymous experts answered the question below. Evaluate each response "
            "independently. Score Accuracy (1-10: factual correctness, no errors) and "
            "Insight (1-10: depth, usefulness, non-obvious value), and write a concise "
            "critique (strengths, errors, omissions). Judge on merit only. "
            + TOOLS_NOTE + CTX_BLOCK +
            f"\n\n<question>\n{QUESTION}\n</question>\n\n{body}\n\n"
            f"Return one entry per label ({', '.join(mapping)}) via `finish`."
        )

    raw_reviews = await parallel(
        plans,
        lambda p: agent(review_prompt(p[1]), schema=review_schema,
                        role=f"Review · {seat_label(p[0])}", model=SEATS[p[0]]),
    )

    # reviews[target] = list of {reviewer, accuracy, insight, critique}
    reviews = {i: [] for i in range(n)}
    for (r, mapping), items in zip(plans, raw_reviews):
        for it in items or []:
            j = mapping.get(str(it.get("label", "")).strip().upper()[:1])
            if j is None:
                continue
            reviews[j].append({
                "reviewer": r,
                "accuracy": int(it["accuracy"]),
                "insight": int(it["insight"]),
                "critique": it["critique"],
            })

    board = []
    for i in range(n):
        rs = reviews[i]
        acc = sum(x["accuracy"] for x in rs) / len(rs) if rs else 0.0
        ins = sum(x["insight"] for x in rs) / len(rs) if rs else 0.0
        board.append({"seat": i, "accuracy": round(acc, 2), "insight": round(ins, 2),
                      "total": round(acc + ins, 2), "n": len(rs)})
    board.sort(key=lambda b: b["total"], reverse=True)
    for b in board:
        log(f"{seat_label(b['seat'])}: accuracy {b['accuracy']}, insight {b['insight']}")

    phase("Stage 3 — Chairman synthesis")
    ch = A.get("chairman", "auto")
    chair = board[0]["seat"] if ch in (None, "auto") else int(ch)
    log(f"Chairman: {seat_label(chair)}" + (" (auto: highest rated)" if ch in (None, "auto") else ""))

    order = list(range(n))
    random.shuffle(order)
    anon = dict(zip(letters(n), order))
    body = []
    for lab, j in anon.items():
        crit = "\n".join(
            f"- accuracy {x['accuracy']}/10, insight {x['insight']}/10: {x['critique']}"
            for x in reviews[j]
        )
        body.append(f"<response label=\"{lab}\">\n{answers[j]}\n</response>\n"
                    f"<peer_reviews label=\"{lab}\">\n{crit or '(none)'}\n</peer_reviews>")
    chair_prompt = (
        "Chairman synthesis\n\n"
        "You chair a panel of anonymous experts. Using their responses and the peer "
        "reviews, write the single definitive final answer to the question: keep what is "
        "correct and insightful, fix errors flagged by reviewers, resolve disagreements "
        "explicitly, and do not mention the panel, labels, or scores. Use Markdown. "
        + TOOLS_NOTE + CTX_BLOCK +
        f"\n\n<question>\n{QUESTION}\n</question>\n\n" + "\n\n".join(body) +
        "\n\nReturn the final answer (Markdown string) via `finish`."
    )
    final = await agent(chair_prompt, schema=STR, role=f"Chairman · {seat_label(chair)}", model=SEATS[chair])

    # ── report ──
    md = [f"# Council — {QUESTION[:80]}", "", "## Final Answer", "",
          f"> Chairman: **{seat_label(chair)}**", "", final, "", "## Leaderboard", "",
          "| Rank | Seat | Accuracy | Insight | Total | Reviews |", "|---|---|---|---|---|---|"]
    for k, b in enumerate(board, 1):
        md.append(f"| {k} | {seat_label(b['seat'])} | {b['accuracy']} | {b['insight']} | {b['total']} | {b['n']} |")
    md += ["", "## Individual Answers & Reviews", "", "````carousel"]
    for i in range(n):
        if i:
            md.append("<!-- slide -->")
        md.append(f"### {seat_label(i)}\n\n{answers[i]}\n\n**Peer reviews**\n")
        for x in reviews[i]:
            md.append(f"- *{seat_label(x['reviewer'])}* — accuracy {x['accuracy']}, "
                      f"insight {x['insight']}: {x['critique']}")
    md.append("````")
    result = {"mode": "council", "question": QUESTION, "seats": SEATS, "answers": answers,
              "reviews": reviews, "leaderboard": board, "chairman": chair, "final": final}
    return "\n".join(md), result


# ─────────────────────────────── Mode 2 ───────────────────────────────
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "revision_notes": {"type": "string", "description": "What you changed and why (or why you endorse as-is)."},
        "plan": {"type": "string", "description": "The complete, standalone canonical Markdown plan."},
        "agreed": {"type": "boolean", "description": "true ONLY if you endorse the plan you received with zero changes."},
    },
    "required": ["revision_notes", "plan", "agreed"],
}

STANDING = (
    "You are helping a user write a plan. Work with them one-on-one across several turns. "
    "Each turn, they will show you the current draft (sometimes revised by them since your "
    "last turn). Improve it rigorously: correctness, completeness, feasibility, risks, "
    "sequencing, and clarity. Always return the COMPLETE standalone canonical plan in "
    "Markdown (never a diff or partial). Set `agreed` to true only when you would ship "
    "the draft you were shown exactly as-is; if you change anything, `agreed` must be "
    "false. Do not agree just to be polite. " + TOOLS_NOTE
)


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


async def run_consensus():
    k = len(SEATS)
    if not 2 <= k <= 3:
        raise ValueError("Consensus mode needs 2 or 3 seats")
    slots = list(range(k))
    random.shuffle(slots)  # slots[p] = seat index for Participant p+1
    parts = [agent(STANDING, schema=PLAN_SCHEMA, role=f"Participant {p + 1}", model=SEATS[slots[p]])
             for p in range(k)]
    turns_used = [0] * k
    history = []  # {participant, round, notes, plan, agreed, version}

    phase("Round 1 — Initial draft")
    first = await parts[0](
        "Here is what I need a plan for:" + CTX_BLOCK +
        f"\n\n<request>\n{QUESTION}\n</request>\n\n"
        "Write the first complete draft. Set `agreed` to false.", PLAN_SCHEMA)
    turns_used[0] += 1
    plan, version = first["plan"], 1
    endorsed = {0}
    history.append({"participant": 1, "notes": first["revision_notes"], "plan": plan,
                    "agreed": False, "version": version})
    log("Participant 1 wrote v1")

    consensus = False
    p = 1 % k
    while not consensus and any(t < MAX_ROUNDS for t in turns_used):
        if turns_used[p] >= MAX_ROUNDS:
            p = (p + 1) % k
            continue
        rnd = turns_used[p] + 1
        phase(f"Participant {p + 1} — turn {rnd}")
        intro = ("Here is what I need a plan for:" + CTX_BLOCK +
                 f"\n\n<request>\n{QUESTION}\n</request>\n\n") if turns_used[p] == 0 else ""
        out = await parts[p](
            intro + f"Here is the current draft (v{version}). Review it and return the full plan."
            f"\n\n<draft version=\"{version}\">\n{plan}\n</draft>", PLAN_SCHEMA)
        turns_used[p] += 1
        changed = norm(out["plan"]) != norm(plan)
        if out["agreed"] and not changed:
            endorsed.add(p)
            log(f"Participant {p + 1} endorsed v{version} ({len(endorsed)}/{k})")
        else:
            plan, version = out["plan"], version + 1
            endorsed = {p}
            log(f"Participant {p + 1} revised → v{version}")
        history.append({"participant": p + 1, "notes": out["revision_notes"], "plan": plan,
                        "agreed": bool(out["agreed"] and not changed), "version": version})
        consensus = len(endorsed) == k
        p = (p + 1) % k

    fallback = False
    if not consensus:
        phase("Deadlock — Participant 1 consolidation")
        fallback = True
        out = await parts[0](
            "We're out of revision rounds. Produce the final consolidated plan: keep the "
            "strongest decisions, resolve open disagreements explicitly in a short "
            "'Decisions & Trade-offs' section, and set `agreed` to true."
            f"\n\n<draft version=\"{version}\">\n{plan}\n</draft>", PLAN_SCHEMA)
        plan, version = out["plan"], version + 1
        history.append({"participant": 1, "notes": out["revision_notes"], "plan": plan,
                        "agreed": True, "version": version, "consolidation": True})

    # ── report ──
    status = "✅ Unanimous consensus" if consensus else "⚠️ No consensus — Participant 1 consolidated"
    md = [f"# Consensus Plan — {QUESTION[:80]}", "", f"> {status} on **v{version}** "
          f"after {len(history)} turns.", "", plan, "", "<details><summary>Reveal participants</summary>", ""]
    for i in range(k):
        md.append(f"- Participant {i + 1}: {seat_label(slots[i])}")
    md += ["", "</details>", "", "## Deliberation", ""]
    prev = ""
    for h in history:
        tag = "consolidation" if h.get("consolidation") else ("endorsed" if h["agreed"] else "revised")
        md.append(f"### Participant {h['participant']} → v{h['version']} ({tag})\n\n{h['notes']}\n")
        if prev and h["plan"] != prev:
            diff = "\n".join(difflib.unified_diff(prev.splitlines(), h["plan"].splitlines(),
                                                  "previous", "this turn", lineterm=""))
            md.append(f"<details><summary>Diff</summary>\n\n```diff\n{diff}\n```\n\n</details>\n")
        prev = h["plan"]
    result = {"mode": "consensus", "question": QUESTION, "seats": SEATS,
              "participants": {f"Participant {i + 1}": SEATS[slots[i]] for i in range(k)},
              "consensus": consensus, "fallback": fallback, "version": version,
              "plan": plan, "history": history}
    return "\n".join(md), result


if MODE in ("council", "mode1", "1"):
    report, result = await run_council()  # noqa: F704
elif MODE in ("consensus", "plan", "mode2", "2"):
    report, result = await run_consensus()  # noqa: F704
else:
    raise ValueError("mode must be 'council' or 'consensus'")

rp = write("report.md", report)
write("result.json", json.dumps(result, indent=2, default=str))
log(f"Report: {rp}")
print(json.dumps({"report": rp, "run_dir": RUN_DIR}))
