import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional
import httpx

from .config import settings
from .models import ModelCatalogItem

NON_CHAT_MODES = {
    "embedding",
    "audio_transcription",
    "audio_speech",
    "image_generation",
    "moderation",
    "rerank",
}


@dataclass
class CompletionResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int


class LiteLLMClient:
    def __init__(self) -> None:
        self._pricing_cache: dict[str, tuple[float, float]] = {}

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.litellm_api_key:
            headers["Authorization"] = f"Bearer {settings.litellm_api_key}"
        return headers

    def _is_excluded(self, model_id: str, mode: Optional[str]) -> bool:
        if mode and mode.lower() in NON_CHAT_MODES:
            return True
        low = model_id.lower()
        return any(pat in low for pat in settings.excluded_patterns)

    @staticmethod
    def _derive_provider(underlying: Optional[str], model_id: str) -> str:
        raw = (underlying or model_id).lower()
        if "claude" in raw or "anthropic" in raw:
            return "Anthropic"
        if "deepseek" in raw:
            return "DeepSeek"
        if "gpt" in raw or "openai" in raw or "o1" in raw or "o3" in raw:
            return "OpenAI"
        if "llama" in raw or "meta" in raw:
            return "Meta"
        if "qwen" in raw:
            return "Qwen"
        if "mistral" in raw or "codestral" in raw:
            return "Mistral"
        if "gemini" in raw or "gemma" in raw or "vertex" in raw:
            return "Google"
        return "LiteLLM"

    async def fetch_models(self) -> list[ModelCatalogItem]:
        async with httpx.AsyncClient(timeout=12.0) as client:
            # Try LiteLLM's rich /model/info endpoint first for mode + alias deduplication + pricing
            try:
                resp = await client.get(
                    f"{settings.litellm_root_url}/model/info",
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    payload = resp.json()
                    raw_items = payload.get("data", [])
                    if isinstance(raw_items, list) and raw_items:
                        return self._parse_model_info(raw_items)
            except Exception:
                pass

            # Fallback to standard OpenAI /v1/models
            resp = await client.get(
                f"{settings.litellm_v1_url}/models",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            items: list[ModelCatalogItem] = []
            seen: set[str] = set()
            for entry in data:
                mid = entry.get("id", "")
                if not mid or mid in seen or self._is_excluded(mid, None):
                    continue
                seen.add(mid)
                items.append(
                    ModelCatalogItem(
                        id=mid,
                        provider=self._derive_provider(None, mid),
                    )
                )
            return sorted(items, key=lambda m: m.id)

    def _parse_model_info(self, raw_items: list[dict[str, Any]]) -> list[ModelCatalogItem]:
        # Group by underlying target model to collapse duplicate aliases cleanly
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in raw_items:
            model_name = item.get("model_name") or ""
            params = item.get("litellm_params") or {}
            info = item.get("model_info") or {}
            mode = info.get("mode")
            if not model_name or self._is_excluded(model_name, mode):
                continue
            underlying = params.get("model") or model_name
            groups.setdefault(underlying, []).append(item)

        catalog: list[ModelCatalogItem] = []
        seen_ids: set[str] = set()

        for underlying, entries in groups.items():
            # Pick canonical entry: prefer model_name matching suffix of underlying target
            underlying_suffix = underlying.split("/")[-1]
            chosen = entries[0]
            for candidate in entries:
                cname = candidate.get("model_name", "")
                if cname == underlying_suffix:
                    chosen = candidate
                    break

            mid = chosen.get("model_name", "")
            if not mid or mid in seen_ids:
                continue
            seen_ids.add(mid)

            info = chosen.get("model_info") or {}
            in_cost = info.get("input_cost_per_token")
            out_cost = info.get("output_cost_per_token")
            max_tok = info.get("max_output_tokens") or info.get("max_tokens")

            if isinstance(in_cost, (int, float)) or isinstance(out_cost, (int, float)):
                self._pricing_cache[mid] = (
                    float(in_cost or 0.0),
                    float(out_cost or 0.0),
                )

            catalog.append(
                ModelCatalogItem(
                    id=mid,
                    provider=self._derive_provider(underlying, mid),
                    underlying_model=underlying,
                    input_cost_per_token=float(in_cost) if isinstance(in_cost, (int, float)) else None,
                    output_cost_per_token=float(out_cost) if isinstance(out_cost, (int, float)) else None,
                    max_tokens=int(max_tok) if isinstance(max_tok, int) else None,
                )
            )

        # Sort frontier / primary models nicely by provider then id
        return sorted(catalog, key=lambda x: (x.provider, x.id))

    def _estimate_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        header_cost: Optional[str],
    ) -> float:
        if header_cost:
            try:
                val = float(header_cost)
                if val > 0:
                    return val
            except ValueError:
                pass
        in_rate, out_rate = self._pricing_cache.get(model, (0.0, 0.0))
        return (prompt_tokens * in_rate) + (completion_tokens * out_rate)

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        on_delta: Optional[Callable[[str], None]] = None,
        temperature: float = 0.6,
        timeout_sec: float = 180.0,
        retries: int = 1,
    ) -> CompletionResult:
        last_err: Optional[Exception] = None

        for attempt in range(retries + 1):
            t0 = time.perf_counter()
            chunks: list[str] = []
            prompt_tokens = 0
            completion_tokens = 0
            header_cost: Optional[str] = None

            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": True,
                "temperature": temperature,
                "stream_options": {"include_usage": True},
            }

            try:
                async with httpx.AsyncClient(timeout=timeout_sec) as client:
                    async with client.stream(
                        "POST",
                        f"{settings.litellm_v1_url}/chat/completions",
                        headers=self._headers(),
                        json=body,
                    ) as resp:
                        if resp.status_code >= 400:
                            err_body = (await resp.aread()).decode("utf-8", errors="replace")
                            # Some upstream models dislike stream_options; fallback without it once
                            if resp.status_code == 400 and "stream_options" in err_body:
                                body.pop("stream_options", None)
                                return await self._stream_without_options(
                                    client, body, model, on_delta, t0
                                )
                            raise RuntimeError(
                                f"HTTP {resp.status_code} from {model}: {err_body[:320]}"
                            )

                        header_cost = resp.headers.get("x-litellm-response-cost")
                        async for raw_line in resp.aiter_lines():
                            line = raw_line.strip()
                            if not line or not line.startswith("data:"):
                                continue
                            data_str = line[5:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                pkt = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            usage = pkt.get("usage")
                            if isinstance(usage, dict):
                                prompt_tokens = int(usage.get("prompt_tokens") or prompt_tokens)
                                completion_tokens = int(
                                    usage.get("completion_tokens") or completion_tokens
                                )

                            choices = pkt.get("choices") or []
                            if choices:
                                delta = choices[0].get("delta") or {}
                                piece = delta.get("content")
                                if piece:
                                    chunks.append(piece)
                                    if on_delta:
                                        on_delta(piece)

                full_text = "".join(chunks)
                latency_ms = int((time.perf_counter() - t0) * 1000)
                if completion_tokens == 0 and full_text:
                    completion_tokens = max(1, len(full_text) // 4)
                cost_usd = self._estimate_cost(
                    model, prompt_tokens, completion_tokens, header_cost
                )
                return CompletionResult(
                    content=full_text,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_err = exc
                if attempt < retries:
                    await asyncio.sleep(1.2 * (attempt + 1))
                    continue
                raise last_err

        raise last_err or RuntimeError("Unknown LiteLLM completion failure")

    async def _stream_without_options(
        self,
        client: httpx.AsyncClient,
        body: dict[str, Any],
        model: str,
        on_delta: Optional[Callable[[str], None]],
        t0: float,
    ) -> CompletionResult:
        chunks: list[str] = []
        async with client.stream(
            "POST",
            f"{settings.litellm_v1_url}/chat/completions",
            headers=self._headers(),
            json=body,
        ) as resp:
            if resp.status_code >= 400:
                err_body = (await resp.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {resp.status_code} from {model}: {err_body[:320]}")
            header_cost = resp.headers.get("x-litellm-response-cost")
            async for raw_line in resp.aiter_lines():
                line = raw_line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    pkt = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = pkt.get("choices") or []
                if choices:
                    piece = (choices[0].get("delta") or {}).get("content")
                    if piece:
                        chunks.append(piece)
                        if on_delta:
                            on_delta(piece)

        full_text = "".join(chunks)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        completion_tokens = max(1, len(full_text) // 4) if full_text else 0
        prompt_tokens = sum(len(m.get("content", "")) for m in body.get("messages", [])) // 4
        cost_usd = self._estimate_cost(model, prompt_tokens, completion_tokens, header_cost)
        return CompletionResult(
            content=full_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )


litellm_client = LiteLLMClient()
