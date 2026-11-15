# Council

Multi-LLM deliberation and blind consensus planning web application built with **FastAPI**, **React 19 (Material 3)**, and **LiteLLM**.

## Modes

### 1. Independent Contextless Council (`2–5 LLMs + Chairman`)
- **Stage 1 — Parallel First Opinions**: Sends your prompt simultaneously to up to 5 distinct LLMs with live token streaming.
- **Stage 2 — Self-Excluded Anonymized Peer Review**: Each LLM grades only the *other* \(N - 1\) shuffled, anonymized responses (`Response A`, `Response B`, …) on **Accuracy (1–10)** and **Insight (1–10)** with qualitative critiques.
- **Stage 3 — Chairman Synthesis**: A pinned or automatically selected top-scored Chairman LLM synthesizes the definitive Markdown response.

### 2. Blind Consensus Plan Mode (`2–3 LLMs, Max 3 Rounds Each`)
- **Blind Randomization**: Shuffles 2–3 LLMs into `Participant 1..3` (identities hidden behind a spoiler toggle).
- **Zero Peer-LLM Awareness**: Each model operates in a 1-on-1 user-relay framing with no awareness of other LLMs or a council.
- **Sequential Rolling Broadcast**: `Participant 1 → Participant 2 → Participant 3` across up to 3 rounds per LLM, streaming structured **Revision Notes** and a **Standalone Canonical Markdown Plan** with a live **Turn-to-Turn Diff Viewer**.
- **Convergence**: Exits early as soon as all active participants endorse the exact same canonical plan version, or runs a constrained consolidation pass after Round 3.

## Quick Start

```bash
cp .env.example .env
# Edit .env with your LITELLM_BASE_URL and LITELLM_API_KEY
docker compose up --build -d
```

## Antigravity Skill

A serverless version of Council that runs inside Antigravity using built-in agents lives in [`skills/council`](skills/council/README.md).
