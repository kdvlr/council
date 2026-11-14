import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from app.config import settings
from app.db import get_run_detail, init_db, create_session_and_run
from app.job_manager import RunEventStream
from app.litellm_client import CompletionResult
from app.mode1_engine import (
    execute_mode1_run,
    parse_peer_ratings_json,
    select_auto_chairman,
)
from app.mode2_engine import (
    StreamingTurnParser,
    execute_mode2_run,
    parse_structured_turn_output,
)


def test_parse_peer_ratings_json():
    raw = """```json
    {
      "ratings": [
        {"label": "Response A", "accuracy": 9, "insight": 8.5, "critique": "Solid proof."},
        {"label": "B", "accuracy": 6, "insight": 7, "critique": "Missed edge case."}
      ]
    }
    ```"""
    parsed = parse_peer_ratings_json(raw, ["Response A", "Response B"])
    assert parsed["Response A"]["accuracy"] == 9.0
    assert parsed["Response A"]["insight"] == 8.5
    assert parsed["Response B"]["accuracy"] == 6.0
    assert parsed["Response B"]["critique"] == "Missed edge case."


def test_select_auto_chairman_tie_breaking():
    # Tie on avg_total=17.0 -> higher accuracy wins; tie on accuracy -> lower latency wins
    candidates = [
        {"model_id": "m1", "avg_total": 17.0, "avg_accuracy": 8.5, "latency_ms": 900},
        {"model_id": "m2", "avg_total": 17.0, "avg_accuracy": 9.0, "latency_ms": 1500},
        {"model_id": "m3", "avg_total": 17.0, "avg_accuracy": 9.0, "latency_ms": 800},
    ]
    assert select_auto_chairman(candidates) == "m3"


def test_streaming_turn_parser_and_structured_extract():
    notes_chunks: list[str] = []
    plan_chunks: list[str] = []
    parser = StreamingTurnParser(notes_chunks.append, plan_chunks.append)

    sample = (
        "<AGREED>false</AGREED>\n"
        "<NOTES>\n- Added rollback step\n</NOTES>\n"
        "<PLAN>\n# Migration Plan\n1. Backup DB\n2. Apply schema\n</PLAN>"
    )
    for ch in [sample[i : i + 7] for i in range(0, len(sample), 7)]:
        parser.feed(ch)

    assert "Added rollback" in "".join(notes_chunks)
    assert "# Migration Plan" in "".join(plan_chunks)

    agreed, notes, plan = parse_structured_turn_output(sample)
    assert agreed is False
    assert "Added rollback step" in notes
    assert plan.startswith("# Migration Plan")


@pytest.mark.asyncio
async def test_mode1_self_excluded_review_and_auto_chairman(tmp_path: Path):
    settings.db_path = tmp_path / "test_m1.db"
    await init_db()

    session_id, run_id, run_index = await create_session_and_run(
        session_id=None,
        mode="council",
        prompt="Explain distributed consensus.",
        models=["model-a", "model-b", "model-c"],
        chairman_spec="auto",
        shared_constraints=None,
        attachments=[],
    )

    seen_review_prompts: list[tuple[str, str]] = []

    async def fake_stream_chat(*, model, messages, on_delta=None, **kwargs):
        sys_txt = messages[0]["content"]
        usr_txt = messages[-1]["content"]
        if "blind technical peer reviewer" in sys_txt:
            seen_review_prompts.append((model, usr_txt))
            out = json.dumps(
                {
                    "ratings": [
                        {"label": "Response A", "accuracy": 9, "insight": 9, "critique": "Great"},
                        {"label": "Response B", "accuracy": 8, "insight": 8, "critique": "Good"},
                    ]
                }
            )
            return CompletionResult(out, 50, 40, 0.001, 200)
        if "Chairman of an analytical council" in sys_txt:
            if on_delta:
                on_delta("# Final Synthesis\nCombined best insights.")
            return CompletionResult("# Final Synthesis\nCombined best insights.", 100, 60, 0.002, 300)
        body = f"Unique answer body from {model}"
        if on_delta:
            on_delta(body)
        return CompletionResult(body, 30, 25, 0.0005, 150)

    stream = RunEventStream(run_id)
    with patch("app.mode1_engine.litellm_client.stream_chat", side_effect=fake_stream_chat):
        await execute_mode1_run(
            stream=stream,
            session_id=session_id,
            run_id=run_id,
            run_index=run_index,
            prompt="Explain distributed consensus.",
            models=["model-a", "model-b", "model-c"],
            chairman_spec="auto",
            shared_constraints=None,
            attachments=[],
        )

    # Verify self-exclusion: no reviewer ever saw its own unique answer body!
    assert len(seen_review_prompts) == 3
    for reviewer_model, prompt_body in seen_review_prompts:
        assert f"Unique answer body from {reviewer_model}" not in prompt_body

    detail = await get_run_detail(run_id)
    assert detail is not None
    assert detail["status"] == "completed"
    assert detail["final_markdown"].startswith("# Final Synthesis")
    assert len(detail["ratings"]) == 6  # 3 models * 2 peer reviews each


@pytest.mark.asyncio
async def test_mode2_canonical_unanimity_requires_proposer_reapproval(tmp_path: Path):
    """
    Verify:
    - R1 Slot 1 drafts v1
    - R1 Slot 2 modifies into v2 (agreed=false)
    - R1 Slot 3 agrees with v2 (agreed=true) -> NOT unanimous yet because Slot 1 hasn't approved v2!
    - R2 Slot 1 agrees with v2 (agreed=true) -> NOW all 3 slots endorse v2 -> early exit at Turn 4!
    - Also verify ZERO mention of LLM/AI/council in any prompt sent to models.
    """
    settings.db_path = tmp_path / "test_m2.db"
    await init_db()

    session_id, run_id, run_index = await create_session_and_run(
        session_id=None,
        mode="conversation",
        prompt="Create a zero-downtime migration plan.",
        models=["alpha", "beta", "gamma"],
        chairman_spec=None,
        shared_constraints=None,
        attachments=[],
    )

    call_idx = 0
    captured_prompts: list[str] = []

    async def fake_stream_chat(*, model, messages, on_delta=None, **kwargs):
        nonlocal call_idx
        call_idx += 1
        full_prompt = "\n".join(m["content"] for m in messages)
        captured_prompts.append(full_prompt)

        if call_idx == 1:
            txt = "<AGREED>false</AGREED><NOTES>- Initial plan</NOTES><PLAN># Plan v1\nStep 1</PLAN>"
        elif call_idx == 2:
            txt = "<AGREED>false</AGREED><NOTES>- Added Step 2</NOTES><PLAN># Plan v2\nStep 1\nStep 2</PLAN>"
        else:
            txt = "<AGREED>true</AGREED><NOTES>- Looks solid</NOTES><PLAN># Plan v2\nStep 1\nStep 2</PLAN>"

        if on_delta:
            on_delta(txt)
        return CompletionResult(txt, 40, 30, 0.001, 120)

    stream = RunEventStream(run_id)
    with patch("app.mode2_engine.litellm_client.stream_chat", side_effect=fake_stream_chat):
        await execute_mode2_run(
            stream=stream,
            session_id=session_id,
            run_id=run_id,
            run_index=run_index,
            prompt="Create a zero-downtime migration plan.",
            models=["alpha", "beta", "gamma"],
            shared_constraints=None,
            attachments=[],
        )

    assert call_idx == 4  # Exited right after R2-Slot1 endorsed v2!
    for p in captured_prompts:
        low = p.lower()
        assert "llm" not in low
        assert "council" not in low
        assert "alpha" not in low and "beta" not in low and "gamma" not in low

    detail = await get_run_detail(run_id)
    assert detail is not None
    assert detail["status"] == "completed"
    assert detail["consensus_status"] == "unanimous"
    assert detail["final_markdown"] == "# Plan v2\nStep 1\nStep 2"
    assert len(detail["turns"]) == 4


@pytest.mark.asyncio
async def test_mode2_deadlock_triggers_tiebreak_after_3_rounds(tmp_path: Path):
    settings.db_path = tmp_path / "test_m2_tb.db"
    await init_db()

    session_id, run_id, run_index = await create_session_and_run(
        session_id=None,
        mode="conversation",
        prompt="Plan architecture.",
        models=["m1", "m2", "m3"],
        chairman_spec=None,
        shared_constraints=None,
        attachments=[],
    )

    call_idx = 0

    async def always_disagree(*, model, messages, on_delta=None, **kwargs):
        nonlocal call_idx
        call_idx += 1
        if "Disputed Trade-offs" in messages[0]["content"]:
            txt = "<AGREED>true</AGREED><NOTES>- Consolidated</NOTES><PLAN># Final Agreed Plan\n## Disputed Trade-offs & Open Decisions\n- Item A</PLAN>"
        else:
            txt = f"<AGREED>false</AGREED><NOTES>- Edit {call_idx}</NOTES><PLAN># Draft {call_idx}</PLAN>"
        return CompletionResult(txt, 20, 20, 0.0005, 100)

    stream = RunEventStream(run_id)
    with patch("app.mode2_engine.litellm_client.stream_chat", side_effect=always_disagree):
        await execute_mode2_run(
            stream=stream,
            session_id=session_id,
            run_id=run_id,
            run_index=run_index,
            prompt="Plan architecture.",
            models=["m1", "m2", "m3"],
            shared_constraints=None,
            attachments=[],
        )

    # 3 models * 3 rounds = 9 turns + 1 constrained consolidation pass = 10 calls
    assert call_idx == 10
    detail = await get_run_detail(run_id)
    assert detail is not None
    assert detail["consensus_status"] == "tie_break"
    assert "Disputed Trade-offs" in detail["final_markdown"]
