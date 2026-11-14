import asyncio
import json
import random
import re
import time
import uuid
from typing import Any, Optional

from .attachments import format_attachments_block
from .db import get_db, get_prior_completed_runs, update_run_fields, utc_now_iso
from .job_manager import RunEventStream
from .litellm_client import CompletionResult, litellm_client


def _build_mode1_messages(
    *,
    prompt: str,
    shared_constraints: Optional[str],
    attachments: list[dict[str, Any]],
    prior_runs: list[dict[str, Any]],
) -> list[dict[str, str]]:
    sys_parts = [
        "You are an independent, rigorous analytical model.",
        "Respond strictly in well-structured GitHub-Flavored Markdown (headings, bullet lists, tables, fenced code blocks with language tags, or LaTeX math where helpful).",
        "Prioritize factual accuracy, deep technical insight, clarity, and completeness.",
    ]
    if shared_constraints and shared_constraints.strip():
        sys_parts.append(f"Additional constraints:\n{shared_constraints.strip()}")

    messages: list[dict[str, str]] = [{"role": "system", "content": "\n\n".join(sys_parts)}]

    # Include compact prior thread context if this is a follow-up run
    for pr in prior_runs:
        if pr.get("final_markdown"):
            messages.append({"role": "user", "content": pr["prompt"]})
            messages.append({"role": "assistant", "content": pr["final_markdown"]})

    att_block = format_attachments_block(attachments)
    user_body = f"{att_block}\n\n### Request\n{prompt}" if att_block else prompt
    messages.append({"role": "user", "content": user_body})
    return messages


def parse_peer_ratings_json(
    raw_text: str, expected_labels: list[str]
) -> dict[str, dict[str, Any]]:
    """Resiliently parse peer evaluation JSON from model output."""
    cleaned = raw_text.strip()
    # Extract JSON block if wrapped in ```json ... ```
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    candidate = fence_match.group(1) if fence_match else cleaned
    if not fence_match:
        brace_start = cleaned.find("{")
        brace_end = cleaned.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            candidate = cleaned[brace_start : brace_end + 1]

    parsed_map: dict[str, dict[str, Any]] = {}
    try:
        obj = json.loads(candidate)
        ratings_list = obj.get("ratings") if isinstance(obj, dict) else obj
        if isinstance(ratings_list, list):
            for item in ratings_list:
                if not isinstance(item, dict):
                    continue
                lbl = str(item.get("label") or item.get("response") or "").strip()
                acc = float(item.get("accuracy", 7))
                ins = float(item.get("insight", 7))
                crit = str(item.get("critique") or item.get("comment") or "").strip()
                parsed_map[lbl] = {
                    "accuracy": max(1.0, min(10.0, round(acc, 1))),
                    "insight": max(1.0, min(10.0, round(ins, 1))),
                    "critique": crit or "Evaluated response.",
                }
        elif isinstance(obj, dict):
            for k, item in obj.items():
                if isinstance(item, dict) and ("accuracy" in item or "insight" in item):
                    acc = float(item.get("accuracy", 7))
                    ins = float(item.get("insight", 7))
                    crit = str(item.get("critique") or item.get("comment") or "").strip()
                    parsed_map[k.strip()] = {
                        "accuracy": max(1.0, min(10.0, round(acc, 1))),
                        "insight": max(1.0, min(10.0, round(ins, 1))),
                        "critique": crit or "Evaluated response.",
                    }
    except Exception:
        pass

    # Normalize label matching (e.g. "A" vs "Response A")
    final_out: dict[str, dict[str, Any]] = {}
    for lbl in expected_labels:
        short = lbl.replace("Response ", "").strip()
        match = (
            parsed_map.get(lbl)
            or parsed_map.get(short)
            or parsed_map.get(f"Response {short}")
        )
        if match:
            final_out[lbl] = match
        else:
            final_out[lbl] = {
                "accuracy": 7.0,
                "insight": 7.0,
                "critique": "Rating parsed with default neutral baseline.",
            }
    return final_out


def select_auto_chairman(scored_models: list[dict[str, Any]]) -> str:
    """
    Pick highest avg_total (Accuracy + Insight out of 20).
    Tie-breaker 1: highest avg_accuracy.
    Tie-breaker 2: lowest latency_ms.
    """
    ranked = sorted(
        scored_models,
        key=lambda m: (
            -(m.get("avg_total") or 0.0),
            -(m.get("avg_accuracy") or 0.0),
            m.get("latency_ms") or 999_999,
        ),
    )
    return ranked[0]["model_id"]


async def execute_mode1_run(
    *,
    stream: RunEventStream,
    session_id: str,
    run_id: str,
    run_index: int,
    prompt: str,
    models: list[str],
    chairman_spec: Optional[str],
    shared_constraints: Optional[str],
    attachments: list[dict[str, Any]],
) -> None:
    run_t0 = time.perf_counter()
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost_usd = 0.0

    try:
        prior_runs = await get_prior_completed_runs(session_id, run_index)
        base_messages = _build_mode1_messages(
            prompt=prompt,
            shared_constraints=shared_constraints,
            attachments=attachments,
            prior_runs=prior_runs,
        )

        # Initialize Stage 1 response rows
        resp_ids: dict[int, str] = {}
        conn = await get_db()
        try:
            for idx, mid in enumerate(models):
                rid = str(uuid.uuid4())
                resp_ids[idx] = rid
                await conn.execute(
                    """
                    INSERT INTO mode1_responses (id, run_id, slot_index, model_id, status, content)
                    VALUES (?, ?, ?, ?, 'streaming', '')
                    """,
                    (rid, run_id, idx, mid),
                )
            await conn.commit()
        finally:
            await conn.close()

        stream.publish(
            "stage",
            {"run_id": run_id, "stage": "stage1_opinions", "models": models},
        )

        # Stage 1: Parallel Independent Generation
        async def _run_single_opinion(slot_idx: int, model_id: str) -> dict[str, Any]:
            rid = resp_ids[slot_idx]
            try:
                res: CompletionResult = await litellm_client.stream_chat(
                    model=model_id,
                    messages=base_messages,
                    temperature=0.65,
                    on_delta=lambda d, s=slot_idx, m=model_id: stream.publish(
                        "token",
                        {
                            "run_id": run_id,
                            "target": "stage1",
                            "slot_index": s,
                            "model_id": m,
                            "delta": d,
                        },
                    ),
                )
                c = await get_db()
                try:
                    await c.execute(
                        """
                        UPDATE mode1_responses
                        SET status = 'completed', content = ?, prompt_tokens = ?,
                            completion_tokens = ?, cost_usd = ?, latency_ms = ?
                        WHERE id = ?
                        """,
                        (
                            res.content,
                            res.prompt_tokens,
                            res.completion_tokens,
                            res.cost_usd,
                            res.latency_ms,
                            rid,
                        ),
                    )
                    await c.commit()
                finally:
                    await c.close()

                payload = {
                    "id": rid,
                    "slot_index": slot_idx,
                    "model_id": model_id,
                    "status": "completed",
                    "content": res.content,
                    "prompt_tokens": res.prompt_tokens,
                    "completion_tokens": res.completion_tokens,
                    "cost_usd": res.cost_usd,
                    "latency_ms": res.latency_ms,
                }
                stream.publish("opinion_done", payload)
                return payload
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                err_txt = str(exc)[:300]
                c = await get_db()
                try:
                    await c.execute(
                        "UPDATE mode1_responses SET status = 'failed', error_message = ? WHERE id = ?",
                        (err_txt, rid),
                    )
                    await c.commit()
                finally:
                    await c.close()
                payload = {
                    "id": rid,
                    "slot_index": slot_idx,
                    "model_id": model_id,
                    "status": "failed",
                    "content": "",
                    "error_message": err_txt,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_usd": 0.0,
                    "latency_ms": 0,
                }
                stream.publish("opinion_done", payload)
                return payload

        stage1_results = await asyncio.gather(
            *[_run_single_opinion(i, m) for i, m in enumerate(models)]
        )

        for r in stage1_results:
            total_prompt_tokens += r.get("prompt_tokens", 0)
            total_completion_tokens += r.get("completion_tokens", 0)
            total_cost_usd += r.get("cost_usd", 0.0)

        succeeded = [
            r for r in stage1_results if r["status"] == "completed" and r["content"].strip()
        ]
        if len(succeeded) < 2:
            errors = "; ".join(
                f"{r['model_id']}: {r.get('error_message', 'empty')}"
                for r in stage1_results
                if r["status"] != "completed"
            )
            raise RuntimeError(
                f"Council requires at least 2 working model responses, only {len(succeeded)} succeeded. ({errors})"
            )

        # Stage 2: Self-Excluded Anonymized Peer Review
        await update_run_fields(run_id, stage="stage2_ratings")
        stream.publish("stage", {"run_id": run_id, "stage": "stage2_ratings"})

        async def _run_peer_review(reviewer: dict[str, Any]) -> list[dict[str, Any]]:
            reviewer_model = reviewer["model_id"]
            peers = [p for p in succeeded if p["model_id"] != reviewer_model]
            rng = random.SystemRandom()
            shuffled_peers = list(peers)
            rng.shuffle(shuffled_peers)

            letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            label_to_target: dict[str, str] = {}
            anon_blocks: list[str] = []
            expected_labels: list[str] = []

            for idx, peer in enumerate(shuffled_peers):
                lbl = f"Response {letters[idx]}"
                expected_labels.append(lbl)
                label_to_target[lbl] = peer["model_id"]
                anon_blocks.append(f"=== {lbl} ===\n{peer['content']}\n=== END {lbl} ===")

            review_sys = (
                "You are an impartial, blind technical peer reviewer. "
                "Evaluate each anonymized response to the user's prompt on two dimensions:\n"
                "1. accuracy (integer or 1-decimal score from 1 to 10): factual correctness, rigor, absence of hallucinations or bugs.\n"
                "2. insight (integer or 1-decimal score from 1 to 10): depth of reasoning, nuance, non-obvious clarity, and practical value.\n\n"
                "Respond ONLY with valid JSON matching this exact schema:\n"
                '{"ratings": [{"label": "Response A", "accuracy": 8, "insight": 9, "critique": "Concise 1-2 sentence justification."}]}'
            )
            review_user = (
                f"### Original User Prompt\n{prompt}\n\n"
                f"### Anonymized Candidate Responses\n\n" + "\n\n".join(anon_blocks)
            )

            try:
                res = await litellm_client.stream_chat(
                    model=reviewer_model,
                    messages=[
                        {"role": "system", "content": review_sys},
                        {"role": "user", "content": review_user},
                    ],
                    temperature=0.2,
                )
                parsed = parse_peer_ratings_json(res.content, expected_labels)
                per_item_cost = res.cost_usd / max(1, len(expected_labels))

                saved_rows: list[dict[str, Any]] = []
                c = await get_db()
                try:
                    for lbl in expected_labels:
                        target_mid = label_to_target[lbl]
                        p_item = parsed[lbl]
                        rat_id = str(uuid.uuid4())
                        row_dict = {
                            "id": rat_id,
                            "run_id": run_id,
                            "reviewer_model_id": reviewer_model,
                            "target_model_id": target_mid,
                            "anon_label": lbl,
                            "accuracy": p_item["accuracy"],
                            "insight": p_item["insight"],
                            "critique": p_item["critique"],
                            "latency_ms": res.latency_ms,
                            "cost_usd": per_item_cost,
                            "_prompt_tokens": res.prompt_tokens if lbl == expected_labels[0] else 0,
                            "_completion_tokens": res.completion_tokens if lbl == expected_labels[0] else 0,
                        }
                        await c.execute(
                            """
                            INSERT INTO mode1_ratings (
                                id, run_id, reviewer_model_id, target_model_id, anon_label,
                                accuracy, insight, critique, latency_ms, cost_usd
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                rat_id,
                                run_id,
                                reviewer_model,
                                target_mid,
                                lbl,
                                p_item["accuracy"],
                                p_item["insight"],
                                p_item["critique"],
                                res.latency_ms,
                                per_item_cost,
                            ),
                        )
                        saved_rows.append(row_dict)
                    await c.commit()
                finally:
                    await c.close()

                stream.publish(
                    "reviewer_done",
                    {
                        "reviewer_model_id": reviewer_model,
                        "ratings": [
                            {k: v for k, v in r.items() if not k.startswith("_")}
                            for r in saved_rows
                        ],
                    },
                )
                return saved_rows
            except asyncio.CancelledError:
                raise
            except Exception:
                # Graceful fallback if one reviewer fails Stage 2
                return []

        nested_ratings = await asyncio.gather(*[_run_peer_review(r) for r in succeeded])
        all_ratings: list[dict[str, Any]] = [item for sub in nested_ratings for item in sub]

        for r in all_ratings:
            total_prompt_tokens += r.get("_prompt_tokens", 0)
            total_completion_tokens += r.get("_completion_tokens", 0)
            total_cost_usd += r.get("cost_usd", 0.0)

        # Compute aggregated scores per Stage 1 response
        scored_models: list[dict[str, Any]] = []
        conn = await get_db()
        try:
            for s_resp in succeeded:
                mid = s_resp["model_id"]
                incoming = [rt for rt in all_ratings if rt["target_model_id"] == mid]
                if incoming:
                    avg_acc = round(sum(x["accuracy"] for x in incoming) / len(incoming), 2)
                    avg_ins = round(sum(x["insight"] for x in incoming) / len(incoming), 2)
                else:
                    avg_acc = 7.5
                    avg_ins = 7.5
                avg_tot = round(avg_acc + avg_ins, 2)
                await conn.execute(
                    """
                    UPDATE mode1_responses
                    SET avg_accuracy = ?, avg_insight = ?, avg_total = ?
                    WHERE id = ?
                    """,
                    (avg_acc, avg_ins, avg_tot, s_resp["id"]),
                )
                entry = {
                    **s_resp,
                    "avg_accuracy": avg_acc,
                    "avg_insight": avg_ins,
                    "avg_total": avg_tot,
                }
                scored_models.append(entry)
            await conn.commit()
        finally:
            await conn.close()

        # Resolve Chairman model
        succeeded_ids = {s["model_id"] for s in succeeded}
        if not chairman_spec or chairman_spec == "auto":
            resolved_chairman = select_auto_chairman(scored_models)
        elif chairman_spec in succeeded_ids or chairman_spec not in models:
            # Either succeeded in council, or is a dedicated 6th Chairman model
            resolved_chairman = chairman_spec
        else:
            # Selected chairman was in council but failed in Stage 1 -> graceful fallback
            resolved_chairman = select_auto_chairman(scored_models)

        await update_run_fields(
            run_id, stage="stage3_chairman", resolved_chairman=resolved_chairman
        )
        stream.publish(
            "stage",
            {
                "run_id": run_id,
                "stage": "stage3_chairman",
                "resolved_chairman": resolved_chairman,
                "scores": [
                    {
                        "model_id": m["model_id"],
                        "avg_accuracy": m["avg_accuracy"],
                        "avg_insight": m["avg_insight"],
                        "avg_total": m["avg_total"],
                    }
                    for m in scored_models
                ],
            },
        )

        # Stage 3: Chairman Synthesis (keep candidates anonymized to Chairman too!)
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        ranked_candidates = sorted(
            scored_models, key=lambda x: -(x["avg_total"] or 0.0)
        )
        candidate_dossiers: list[str] = []
        for idx, cand in enumerate(ranked_candidates):
            cid = f"Candidate {letters[idx]}"
            critiques = [
                f"- ({rt['accuracy']}/10 Acc, {rt['insight']}/10 Ins): {rt['critique']}"
                for rt in all_ratings
                if rt["target_model_id"] == cand["model_id"]
            ]
            critique_txt = "\n".join(critiques) if critiques else "- No peer critiques recorded."
            candidate_dossiers.append(
                f"### {cid} — Peer Score: {cand['avg_total']}/20 "
                f"(Accuracy: {cand['avg_accuracy']}/10, Insight: {cand['avg_insight']}/10)\n\n"
                f"#### {cid} Response:\n{cand['content']}\n\n"
                f"#### Peer Critiques for {cid}:\n{critique_txt}"
            )

        chair_sys = (
            "You are the Chairman of an analytical council. You are given the user's request, "
            "multiple independent anonymized candidate responses, and blind peer-review scores/critiques.\n"
            "Your task is to synthesize the single best, definitive, self-contained final response in GitHub-Flavored Markdown:\n"
            "- Combine the strongest insights, proofs, examples, and architectural nuances across candidates.\n"
            "- Correct or discard any errors flagged by peer reviewers.\n"
            "- Do NOT mention 'Candidate A/B', 'the council', or peer scores in your final answer—write directly to the user as an authoritative, cohesive final document."
        )
        if shared_constraints and shared_constraints.strip():
            chair_sys += f"\n\nAdditional constraints:\n{shared_constraints.strip()}"

        att_block = format_attachments_block(attachments)
        chair_user = (
            (f"{att_block}\n\n" if att_block else "")
            + f"## Original User Prompt\n{prompt}\n\n"
            + "## Anonymized Council Responses & Peer Evaluations\n\n"
            + "\n\n---\n\n".join(candidate_dossiers)
        )

        chair_messages: list[dict[str, str]] = [{"role": "system", "content": chair_sys}]
        for pr in prior_runs:
            if pr.get("final_markdown"):
                chair_messages.append({"role": "user", "content": pr["prompt"]})
                chair_messages.append({"role": "assistant", "content": pr["final_markdown"]})
        chair_messages.append({"role": "user", "content": chair_user})

        try:
            chair_res = await litellm_client.stream_chat(
                model=resolved_chairman,
                messages=chair_messages,
                temperature=0.45,
                on_delta=lambda d: stream.publish(
                    "token",
                    {
                        "run_id": run_id,
                        "target": "chairman",
                        "model_id": resolved_chairman,
                        "delta": d,
                    },
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # If dedicated 6th chairman failed (e.g. 0 quota model picked as chairman), fallback to top-scored council model
            fallback_chair = select_auto_chairman(scored_models)
            if fallback_chair == resolved_chairman:
                raise
            resolved_chairman = fallback_chair
            await update_run_fields(run_id, resolved_chairman=resolved_chairman)
            stream.publish(
                "stage",
                {
                    "run_id": run_id,
                    "stage": "stage3_chairman",
                    "resolved_chairman": resolved_chairman,
                },
            )
            chair_res = await litellm_client.stream_chat(
                model=resolved_chairman,
                messages=chair_messages,
                temperature=0.45,
                on_delta=lambda d: stream.publish(
                    "token",
                    {
                        "run_id": run_id,
                        "target": "chairman",
                        "model_id": resolved_chairman,
                        "delta": d,
                    },
                ),
            )

        total_prompt_tokens += chair_res.prompt_tokens
        total_completion_tokens += chair_res.completion_tokens
        total_cost_usd += chair_res.cost_usd
        duration_ms = int((time.perf_counter() - run_t0) * 1000)

        metrics = {
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_cost_usd": round(total_cost_usd, 6),
            "duration_ms": duration_ms,
            "chairman_latency_ms": chair_res.latency_ms,
        }

        await update_run_fields(
            run_id,
            status="completed",
            stage="done",
            resolved_chairman=resolved_chairman,
            final_markdown=chair_res.content,
            metrics_json=json.dumps(metrics),
            completed_at=utc_now_iso(),
        )
        stream.publish(
            "done",
            {
                "run_id": run_id,
                "status": "completed",
                "resolved_chairman": resolved_chairman,
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
