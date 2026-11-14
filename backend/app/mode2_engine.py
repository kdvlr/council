import asyncio
import json
import random
import re
import time
import uuid
from typing import Any, Callable, Optional

from .attachments import format_attachments_block
from .db import get_db, get_prior_completed_runs, update_run_fields, utc_now_iso
from .job_manager import RunEventStream
from .litellm_client import litellm_client

MAX_ROUNDS_PER_LLM = 3


class StreamingTurnParser:
    """
    Incrementally parses streaming tokens formatted as:
    <AGREED>true|false</AGREED>
    <NOTES>...</NOTES>
    <PLAN>...</PLAN>
    Emits live deltas for 'notes' and 'plan' sections without exposing wrapper XML tags.
    """

    def __init__(
        self,
        on_notes_delta: Callable[[str], None],
        on_plan_delta: Callable[[str], None],
    ) -> None:
        self._on_notes = on_notes_delta
        self._on_plan = on_plan_delta
        self._raw_buf = ""
        self._emitted_notes_len = 0
        self._emitted_plan_len = 0

    def feed(self, piece: str) -> None:
        self._raw_buf += piece

        # Stream NOTES content while inside or after <NOTES>
        notes_start = self._raw_buf.find("<NOTES>")
        if notes_start != -1:
            content_start = notes_start + len("<NOTES>")
            notes_end = self._raw_buf.find("</NOTES>", content_start)
            if notes_end != -1:
                available = self._raw_buf[content_start:notes_end]
            else:
                # Hold back last 8 chars in case partial '</NOTES>' tag is arriving
                safe_end = max(content_start, len(self._raw_buf) - 8)
                available = self._raw_buf[content_start:safe_end]
            if len(available) > self._emitted_notes_len:
                delta = available[self._emitted_notes_len :]
                self._emitted_notes_len = len(available)
                self._on_notes(delta)

        # Stream PLAN content while inside or after <PLAN>
        plan_start = self._raw_buf.find("<PLAN>")
        if plan_start != -1:
            content_start = plan_start + len("<PLAN>")
            plan_end = self._raw_buf.find("</PLAN>", content_start)
            if plan_end != -1:
                available = self._raw_buf[content_start:plan_end]
            else:
                safe_end = max(content_start, len(self._raw_buf) - 7)
                available = self._raw_buf[content_start:safe_end]
            if len(available) > self._emitted_plan_len:
                delta = available[self._emitted_plan_len :]
                self._emitted_plan_len = len(available)
                self._on_plan(delta)


def parse_structured_turn_output(
    raw_text: str, *, force_disagree: bool = False, fallback_plan: str = ""
) -> tuple[bool, str, str]:
    """
    Returns (agreed, revision_notes, plan_markdown).
    Resilient to minor formatting variations so output is always valid Markdown.
    """
    agreed = False
    if not force_disagree:
        m_ag = re.search(r"<AGREED>\s*(true|yes)\s*</AGREED>", raw_text, re.IGNORECASE)
        if m_ag:
            agreed = True

    m_notes = re.search(r"<NOTES>(.*?)</NOTES>", raw_text, re.DOTALL | re.IGNORECASE)
    notes = m_notes.group(1).strip() if m_notes else ""

    m_plan = re.search(r"<PLAN>(.*?)</PLAN>", raw_text, re.DOTALL | re.IGNORECASE)
    if m_plan:
        plan_md = m_plan.group(1).strip()
    elif "<PLAN>" in raw_text:
        # Unclosed <PLAN> tag at end of output
        plan_md = raw_text.split("<PLAN>", 1)[1].strip()
    else:
        # Fallback: strip any <AGREED> / <NOTES> tags and treat remainder as Markdown plan
        stripped = re.sub(r"<AGREED>.*?</AGREED>", "", raw_text, flags=re.DOTALL | re.IGNORECASE)
        stripped = re.sub(r"<NOTES>.*?</NOTES>", "", stripped, flags=re.DOTALL | re.IGNORECASE).strip()
        plan_md = stripped

    if agreed and fallback_plan.strip():
        # Guarantee canonical draft immutability when participant endorses without substantive changes
        plan_md = fallback_plan.strip()
        if not notes:
            notes = "- Reviewed the current working plan in full and confirmed complete agreement with no further changes needed."
    elif not plan_md and fallback_plan.strip():
        plan_md = fallback_plan.strip()

    if not notes:
        notes = "- Proposed structured Markdown plan." if force_disagree else "- Updated working plan."

    return agreed, notes, plan_md


def _build_blind_turn_messages(
    *,
    prompt: str,
    shared_constraints: Optional[str],
    attachments: list[dict[str, Any]],
    prior_agreed_plan: Optional[str],
    is_initial_seed: bool,
    canonical_plan: str,
    recent_external_revisions: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """
    Constructs a 1-on-1 User-Assistant prompt with ZERO awareness of other LLMs,
    councils, slots, or AI participants.
    """
    base_sys = (
        "You are a principal systems architect and strategic planner working 1-on-1 with the user to craft an actionable, rock-solid plan.\n"
        "All plans and notes MUST be written in clean GitHub-Flavored Markdown (clear headings, numbered phases, checklists, tables, or Mermaid diagrams where helpful).\n\n"
        "You MUST format your entire response using these exact three XML sections and nothing outside them:\n"
        "<AGREED>true or false</AGREED>\n"
        "<NOTES>\n"
        "- Concise Markdown bullet points summarizing key design choices, critiques addressed, or why you agree with the current working draft.\n"
        "</NOTES>\n"
        "<PLAN>\n"
        "# Plan Title\n"
        "(Complete, self-contained Markdown plan — never write partial diffs or placeholders like 'same as above'.)\n"
        "</PLAN>"
    )
    if shared_constraints and shared_constraints.strip():
        base_sys += f"\n\nAdditional user constraints:\n{shared_constraints.strip()}"

    att_block = format_attachments_block(attachments)
    context_prefix = f"{att_block}\n\n" if att_block else ""
    if prior_agreed_plan:
        context_prefix += (
            "### Previously Baseline Plan (from earlier turn)\n"
            f"{prior_agreed_plan}\n\n"
        )

    if is_initial_seed:
        user_msg = (
            f"{context_prefix}"
            f"### Goal / Request\n{prompt}\n\n"
            "Draft the complete initial Markdown plan for this request. "
            "Set `<AGREED>false</AGREED>`, summarize your architectural rationale in `<NOTES>`, "
            "and write the full standalone Markdown plan inside `<PLAN>`."
        )
    else:
        feedback_sections: list[str] = []
        for idx, rev in enumerate(recent_external_revisions, start=1):
            feedback_sections.append(
                f"#### Revision Note Set {idx}:\n{rev['revision_notes']}"
            )
        notes_digest = "\n\n".join(feedback_sections) if feedback_sections else "None."

        user_msg = (
            f"{context_prefix}"
            f"### Goal / Request\n{prompt}\n\n"
            f"### Current Working Draft Plan\n{canonical_plan}\n\n"
            f"### Recent Revision Notes & Considerations\n{notes_digest}\n\n"
            "### Instructions\n"
            "Carefully review the Current Working Draft Plan against the Goal and Revision Notes:\n"
            "1. If the Current Working Draft Plan is already comprehensive, accurate, actionable, and needs NO substantive structural or technical changes (avoid nitpicking wording or cosmetic rephrasing), set `<AGREED>true</AGREED>`, briefly state why the plan is ready in `<NOTES>`, and repeat the Current Working Draft Plan inside `<PLAN>`.\n"
            "2. If there is a genuine gap, flaw, missing edge case, or concrete improvement needed, set `<AGREED>false</AGREED>`, list the exact changes made in `<NOTES>`, and output the complete revised standalone Markdown plan inside `<PLAN>`."
        )

    return [
        {"role": "system", "content": base_sys},
        {"role": "user", "content": user_msg},
    ]


def _build_blind_tiebreak_messages(
    *,
    prompt: str,
    shared_constraints: Optional[str],
    attachments: list[dict[str, Any]],
    latest_drafts_by_slot: list[dict[str, Any]],
) -> list[dict[str, str]]:
    sys_msg = (
        "You are a principal editor finalizing a single canonical Markdown plan for the user.\n"
        "You are given the user's goal and competing final working drafts with their revision notes.\n"
        "Produce the definitive consolidated plan strictly following these rules:\n"
        "1. Include all architecture, steps, and decisions shared across the drafts.\n"
        "2. Where the drafts still disagree on a substantive choice, pick the most pragmatic safe default AND add a dedicated `## Disputed Trade-offs & Open Decisions` section at the bottom summarizing the alternatives concisely.\n"
        "3. Output using the exact XML sections `<AGREED>true</AGREED>`, `<NOTES>...</NOTES>`, and `<PLAN>...</PLAN>` with clean GitHub-Flavored Markdown."
    )
    if shared_constraints and shared_constraints.strip():
        sys_msg += f"\n\nAdditional user constraints:\n{shared_constraints.strip()}"

    att_block = format_attachments_block(attachments)
    draft_blocks = []
    for i, d in enumerate(latest_drafts_by_slot, start=1):
        draft_blocks.append(
            f"### Working Draft Option {i}\n"
            f"**Notes:**\n{d['revision_notes']}\n\n"
            f"**Plan:**\n{d['plan_markdown']}"
        )

    user_msg = (
        (f"{att_block}\n\n" if att_block else "")
        + f"## Goal / Request\n{prompt}\n\n"
        + "\n\n---\n\n".join(draft_blocks)
    )
    return [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": user_msg},
    ]


async def execute_mode2_run(
    *,
    stream: RunEventStream,
    session_id: str,
    run_id: str,
    run_index: int,
    prompt: str,
    models: list[str],
    shared_constraints: Optional[str],
    attachments: list[dict[str, Any]],
) -> None:
    if len(models) < 2 or len(models) > 3:
        raise ValueError("Conversation mode requires 2 to 3 distinct LLMs.")

    run_t0 = time.perf_counter()
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost_usd = 0.0

    try:
        prior_runs = await get_prior_completed_runs(session_id, run_index)
        prior_agreed_plan: Optional[str] = None
        if prior_runs:
            prior_agreed_plan = prior_runs[-1].get("final_markdown") or None

        # Randomize LLM slot assignment at the start of every cycle
        shuffled = list(models)
        random.SystemRandom().shuffle(shuffled)
        slot_mapping = {str(i + 1): m for i, m in enumerate(shuffled)}

        await update_run_fields(run_id, slot_mapping_json=json.dumps(slot_mapping))
        stream.publish(
            "mode2_init",
            {
                "run_id": run_id,
                "participant_count": len(shuffled),
                "slot_mapping": slot_mapping,
                "max_rounds": MAX_ROUNDS_PER_LLM,
            },
        )

        active_slots: set[int] = set(range(1, len(shuffled) + 1))
        canonical_plan = ""
        canonical_version = 0
        endorsers: set[int] = set()
        turn_history: list[dict[str, Any]] = []
        turn_counter = 0
        consensus_reached = False

        for round_num in range(1, MAX_ROUNDS_PER_LLM + 1):
            if consensus_reached:
                break

            await update_run_fields(run_id, stage=f"round_{round_num}")
            stream.publish(
                "stage", {"run_id": run_id, "stage": f"round_{round_num}", "round": round_num}
            )

            for slot_num in sorted(list(active_slots)):
                model_id = slot_mapping[str(slot_num)]
                turn_counter += 1
                turn_id = str(uuid.uuid4())
                is_seed = canonical_version == 0

                conn = await get_db()
                try:
                    await conn.execute(
                        """
                        INSERT INTO mode2_turns (
                            id, run_id, turn_number, round_number, slot_number, model_id,
                            is_tie_break, agreed, plan_version, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, 'streaming', ?)
                        """,
                        (
                            turn_id,
                            run_id,
                            turn_counter,
                            round_num,
                            slot_num,
                            model_id,
                            max(1, canonical_version),
                            utc_now_iso(),
                        ),
                    )
                    await conn.commit()
                finally:
                    await conn.close()

                stream.publish(
                    "turn_start",
                    {
                        "id": turn_id,
                        "run_id": run_id,
                        "turn_number": turn_counter,
                        "round_number": round_num,
                        "slot_number": slot_num,
                        "is_tie_break": False,
                    },
                )

                # Gather revision notes from the other slots since this slot's last turn
                recent_external = []
                for prev in reversed(turn_history):
                    if prev["slot_number"] == slot_num:
                        break
                    recent_external.append(prev)
                recent_external.reverse()

                messages = _build_blind_turn_messages(
                    prompt=prompt,
                    shared_constraints=shared_constraints,
                    attachments=attachments,
                    prior_agreed_plan=prior_agreed_plan,
                    is_initial_seed=is_seed,
                    canonical_plan=canonical_plan,
                    recent_external_revisions=recent_external,
                )

                parser = StreamingTurnParser(
                    on_notes_delta=lambda d, tn=turn_counter, sn=slot_num: stream.publish(
                        "token",
                        {
                            "run_id": run_id,
                            "target": "mode2_notes",
                            "turn_number": tn,
                            "slot_number": sn,
                            "delta": d,
                        },
                    ),
                    on_plan_delta=lambda d, tn=turn_counter, sn=slot_num: stream.publish(
                        "token",
                        {
                            "run_id": run_id,
                            "target": "mode2_plan",
                            "turn_number": tn,
                            "slot_number": sn,
                            "delta": d,
                        },
                    ),
                )

                try:
                    res = await litellm_client.stream_chat(
                        model=model_id,
                        messages=messages,
                        temperature=0.5 if is_seed else 0.35,
                        on_delta=parser.feed,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    err_txt = str(exc)[:300]
                    c = await get_db()
                    try:
                        await c.execute(
                            "UPDATE mode2_turns SET status = 'failed', error_message = ? WHERE id = ?",
                            (err_txt, turn_id),
                        )
                        await c.commit()
                    finally:
                        await c.close()
                    active_slots.discard(slot_num)
                    endorsers.discard(slot_num)
                    stream.publish(
                        "turn_done",
                        {
                            "id": turn_id,
                            "turn_number": turn_counter,
                            "round_number": round_num,
                            "slot_number": slot_num,
                            "status": "failed",
                            "error_message": err_txt,
                        },
                    )
                    if len(active_slots) < 2:
                        raise RuntimeError(
                            f"Fewer than 2 active participants remain after error ({err_txt})."
                        )
                    continue

                total_prompt_tokens += res.prompt_tokens
                total_completion_tokens += res.completion_tokens
                total_cost_usd += res.cost_usd

                agreed, notes, plan_md = parse_structured_turn_output(
                    res.content,
                    force_disagree=is_seed,
                    fallback_plan=canonical_plan,
                )

                if is_seed or not agreed:
                    canonical_version += 1
                    canonical_plan = plan_md
                    endorsers = {slot_num}
                else:
                    # Participant endorsed the exact current canonical_version
                    endorsers.add(slot_num)

                conn = await get_db()
                try:
                    await conn.execute(
                        """
                        UPDATE mode2_turns
                        SET status = 'completed', agreed = ?, plan_version = ?,
                            revision_notes = ?, plan_markdown = ?, raw_output = ?,
                            prompt_tokens = ?, completion_tokens = ?, cost_usd = ?, latency_ms = ?
                        WHERE id = ?
                        """,
                        (
                            1 if agreed else 0,
                            canonical_version,
                            notes,
                            canonical_plan,
                            res.content,
                            res.prompt_tokens,
                            res.completion_tokens,
                            res.cost_usd,
                            res.latency_ms,
                            turn_id,
                        ),
                    )
                    await conn.commit()
                finally:
                    await conn.close()

                turn_record = {
                    "id": turn_id,
                    "turn_number": turn_counter,
                    "round_number": round_num,
                    "slot_number": slot_num,
                    "is_tie_break": False,
                    "agreed": agreed,
                    "plan_version": canonical_version,
                    "revision_notes": notes,
                    "plan_markdown": canonical_plan,
                    "prompt_tokens": res.prompt_tokens,
                    "completion_tokens": res.completion_tokens,
                    "cost_usd": res.cost_usd,
                    "latency_ms": res.latency_ms,
                    "status": "completed",
                    "endorsed_slots": sorted(list(endorsers)),
                }
                turn_history.append(turn_record)
                stream.publish("turn_done", turn_record)

                # Strict Unanimity Check: all active slots have endorsed the exact same canonical_version
                if len(active_slots) >= 2 and active_slots.issubset(endorsers):
                    consensus_reached = True
                    break

        consensus_status = "unanimous"
        if not consensus_reached:
            # Round-3 Deadlock Fallback: Constrained Consolidation Pass by first active slot (Slot 1)
            consensus_status = "tie_break"
            arbiter_slot = min(active_slots)
            arbiter_model = slot_mapping[str(arbiter_slot)]
            turn_counter += 1
            tb_id = str(uuid.uuid4())

            await update_run_fields(run_id, stage="tie_break")
            stream.publish(
                "stage", {"run_id": run_id, "stage": "tie_break", "slot_number": arbiter_slot}
            )

            conn = await get_db()
            try:
                await conn.execute(
                    """
                    INSERT INTO mode2_turns (
                        id, run_id, turn_number, round_number, slot_number, model_id,
                        is_tie_break, agreed, plan_version, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, 'streaming', ?)
                    """,
                    (
                        tb_id,
                        run_id,
                        turn_counter,
                        MAX_ROUNDS_PER_LLM,
                        arbiter_slot,
                        arbiter_model,
                        canonical_version + 1,
                        utc_now_iso(),
                    ),
                )
                await conn.commit()
            finally:
                await conn.close()

            stream.publish(
                "turn_start",
                {
                    "id": tb_id,
                    "run_id": run_id,
                    "turn_number": turn_counter,
                    "round_number": MAX_ROUNDS_PER_LLM,
                    "slot_number": arbiter_slot,
                    "is_tie_break": True,
                },
            )

            latest_by_slot: dict[int, dict[str, Any]] = {}
            for t in turn_history:
                if t["status"] == "completed":
                    latest_by_slot[t["slot_number"]] = t

            tb_messages = _build_blind_tiebreak_messages(
                prompt=prompt,
                shared_constraints=shared_constraints,
                attachments=attachments,
                latest_drafts_by_slot=[
                    latest_by_slot[s] for s in sorted(latest_by_slot.keys())
                ],
            )

            tb_parser = StreamingTurnParser(
                on_notes_delta=lambda d, tn=turn_counter, sn=arbiter_slot: stream.publish(
                    "token",
                    {
                        "run_id": run_id,
                        "target": "mode2_notes",
                        "turn_number": tn,
                        "slot_number": sn,
                        "delta": d,
                    },
                ),
                on_plan_delta=lambda d, tn=turn_counter, sn=arbiter_slot: stream.publish(
                    "token",
                    {
                        "run_id": run_id,
                        "target": "mode2_plan",
                        "turn_number": tn,
                        "slot_number": sn,
                        "delta": d,
                    },
                ),
            )

            tb_res = await litellm_client.stream_chat(
                model=arbiter_model,
                messages=tb_messages,
                temperature=0.3,
                on_delta=tb_parser.feed,
            )

            total_prompt_tokens += tb_res.prompt_tokens
            total_completion_tokens += tb_res.completion_tokens
            total_cost_usd += tb_res.cost_usd

            _, tb_notes, tb_plan = parse_structured_turn_output(
                tb_res.content, force_disagree=True, fallback_plan=canonical_plan
            )
            canonical_version += 1
            canonical_plan = tb_plan

            conn = await get_db()
            try:
                await conn.execute(
                    """
                    UPDATE mode2_turns
                    SET status = 'completed', agreed = 1, plan_version = ?,
                        revision_notes = ?, plan_markdown = ?, raw_output = ?,
                        prompt_tokens = ?, completion_tokens = ?, cost_usd = ?, latency_ms = ?
                    WHERE id = ?
                    """,
                    (
                        canonical_version,
                        tb_notes,
                        canonical_plan,
                        tb_res.content,
                        tb_res.prompt_tokens,
                        tb_res.completion_tokens,
                        tb_res.cost_usd,
                        tb_res.latency_ms,
                        tb_id,
                    ),
                )
                await conn.commit()
            finally:
                await conn.close()

            stream.publish(
                "turn_done",
                {
                    "id": tb_id,
                    "turn_number": turn_counter,
                    "round_number": MAX_ROUNDS_PER_LLM,
                    "slot_number": arbiter_slot,
                    "is_tie_break": True,
                    "agreed": True,
                    "plan_version": canonical_version,
                    "revision_notes": tb_notes,
                    "plan_markdown": canonical_plan,
                    "prompt_tokens": tb_res.prompt_tokens,
                    "completion_tokens": tb_res.completion_tokens,
                    "cost_usd": tb_res.cost_usd,
                    "latency_ms": tb_res.latency_ms,
                    "status": "completed",
                    "endorsed_slots": sorted(list(active_slots)),
                },
            )

        duration_ms = int((time.perf_counter() - run_t0) * 1000)
        metrics = {
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_cost_usd": round(total_cost_usd, 6),
            "duration_ms": duration_ms,
            "total_turns": turn_counter,
            "final_plan_version": canonical_version,
        }

        await update_run_fields(
            run_id,
            status="completed",
            stage="done",
            final_markdown=canonical_plan,
            consensus_status=consensus_status,
            metrics_json=json.dumps(metrics),
            completed_at=utc_now_iso(),
        )
        stream.publish(
            "done",
            {
                "run_id": run_id,
                "status": "completed",
                "consensus_status": consensus_status,
                "metrics": metrics,
            },
        )
    except asyncio.CancelledError:
        await update_run_fields(
            run_id,
            status="cancelled",
            stage="done",
            error_message="Run cancelled by user.",
            completed_at=utc_now_iso(),
        )
        stream.publish("done", {"run_id": run_id, "status": "cancelled"})
        raise
    except Exception as exc:
        err_msg = str(exc)[:500]
        await update_run_fields(
            run_id,
            status="failed",
            stage="done",
            error_message=err_msg,
            completed_at=utc_now_iso(),
        )
        stream.publish(
            "done", {"run_id": run_id, "status": "failed", "error_message": err_msg}
        )
