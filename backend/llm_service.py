import os
import json
import asyncio
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Tuple
from loguru import logger


class GeminiServerError(Exception):
    """Raised when Gemini returns a 5xx response."""


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2:7b")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# ── Gemini key pool ────────────────────────────────────────────────────────
def _load_gemini_keys() -> List[str]:
    raw = os.getenv("GEMINI_API_KEYS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        single = os.getenv("GEMINI_API_KEY", "")
        if single:
            keys = [single]
    return keys

_gemini_keys: List[str] = _load_gemini_keys()
_gemini_current_idx: int = 0
_gemini_paid_key: str = os.getenv("PAID_GEMINI_API_KEY", "").strip()
_gemini_paid_enabled: bool = os.getenv("PAID_GEMINI_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")

logger.info(
    "LLM config  provider={}  free_gemini_keys={}  paid_key={}  paid_enabled={}  ollama_model={}  groq_model={}",
    LLM_PROVIDER, len(_gemini_keys), "set" if _gemini_paid_key else "not set",
    _gemini_paid_enabled, OLLAMA_MODEL, GROQ_MODEL,
)

# ── Paid cost tracking ─────────────────────────────────────────────────────
_COST_FILE = "/app/data/paid_cost.json"
_INPUT_PRICE_PER_M  = 0.30   # USD per 1M input tokens
_OUTPUT_PRICE_PER_M = 2.50   # USD per 1M output tokens
_cost_lock = asyncio.Lock()


def _load_cost_data() -> dict:
    try:
        with open(_COST_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "total_cost_usd": 0.0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "calls": [],
        }


async def _record_paid_usage(input_tokens: int, output_tokens: int) -> None:
    cost = (input_tokens * _INPUT_PRICE_PER_M + output_tokens * _OUTPUT_PRICE_PER_M) / 1_000_000
    async with _cost_lock:
        data = _load_cost_data()
        data["total_input_tokens"] += input_tokens
        data["total_output_tokens"] += output_tokens
        data["total_cost_usd"] = round(data["total_cost_usd"] + cost, 8)
        data["calls"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 8),
        })
        os.makedirs(os.path.dirname(_COST_FILE), exist_ok=True)
        with open(_COST_FILE, "w") as f:
            json.dump(data, f, indent=2)
    logger.info(
        "paid gemini used  in_tokens={}  out_tokens={}  call_cost=${:.6f}  total_cost=${:.6f}",
        input_tokens, output_tokens, cost, data["total_cost_usd"],
    )


def get_paid_cost_data() -> dict:
    return _load_cost_data()


# ── LLM dispatch ──────────────────────────────────────────────────────────
async def chat_with_llm(messages: List[Dict]) -> str:
    provider = LLM_PROVIDER.lower()
    if provider == "ollama":
        return await _chat_ollama(messages)
    elif provider == "gemini":
        return await _chat_gemini(messages)
    elif provider == "groq":
        return await _chat_groq(messages)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}. Use 'ollama', 'gemini', or 'groq'")


async def _chat_ollama(messages: List[Dict]) -> str:
    url = f"{OLLAMA_HOST}/api/chat"
    logger.debug("ollama request  url={}  model={}", url, OLLAMA_MODEL)
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                url,
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.85,
                        "num_ctx": 4096,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["message"]["content"]
            logger.debug("ollama response  chars={}", len(content))
            return content
    except httpx.ConnectError:
        logger.error("Cannot connect to Ollama at {}  — is the service running?", url)
        raise
    except httpx.HTTPStatusError as e:
        logger.error("Ollama HTTP error  status={}  body={}", e.response.status_code, e.response.text[:500])
        raise
    except Exception:
        logger.exception("Unexpected error calling Ollama")
        raise


_GEMINI_MODEL = "gemini-2.5-flash"


async def _gemini_request(key: str, messages: List[Dict]) -> Tuple[str, int, int]:
    """Returns (text, input_tokens, output_tokens)."""
    system_instruction = None
    contents = []

    for msg in messages:
        if msg["role"] == "system":
            system_instruction = {"parts": [{"text": msg["content"]}]}
        elif msg["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
        elif msg["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": msg["content"]}]})

    request_body: Dict = {
        "contents": contents,
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 8192},
    }
    if system_instruction:
        request_body["systemInstruction"] = system_instruction

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{_GEMINI_MODEL}:generateContent?key={key}",
            json=request_body,
        )
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        input_tokens = usage.get("promptTokenCount", 0)
        output_tokens = usage.get("candidatesTokenCount", 0)
        return text, input_tokens, output_tokens


async def _chat_gemini_paid(messages: List[Dict]) -> str:
    logger.warning("falling back to paid Gemini key")
    try:
        text, input_tokens, output_tokens = await _gemini_request(_gemini_paid_key, messages)
        await _record_paid_usage(input_tokens, output_tokens)
        return text
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if 500 <= status < 600:
            raise GeminiServerError(f"Paid Gemini returned {status}") from e
        logger.error("Paid Gemini key failed  status={}  body={}", status, e.response.text[:300])
        raise


async def _chat_gemini(messages: List[Dict]) -> str:
    global _gemini_current_idx

    if not _gemini_keys:
        if _gemini_paid_key and _gemini_paid_enabled:
            return await _chat_gemini_paid(messages)
        raise ValueError("No Gemini API keys configured. Set GEMINI_API_KEYS or GEMINI_API_KEY.")

    n = len(_gemini_keys)

    for attempt in range(n):
        idx = (_gemini_current_idx + attempt) % n
        key = _gemini_keys[idx]
        try:
            text, _, _ = await _gemini_request(key, messages)
            _gemini_current_idx = idx
            logger.debug("gemini ok  key_idx={}  model={}", idx, _GEMINI_MODEL)
            return text
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 400 <= status < 500:
                logger.warning(
                    "Gemini key_idx={} returned {}  rotating to next key",
                    idx, status,
                )
                continue
            # 5xx: surface immediately, don't rotate
            logger.error("Gemini key_idx={} server error {}  body={}", idx, status, e.response.text[:300])
            raise GeminiServerError(f"Gemini returned {status}") from e

    # All free keys exhausted — try paid fallback
    if _gemini_paid_key and _gemini_paid_enabled:
        return await _chat_gemini_paid(messages)

    raise RuntimeError(f"All {n} Gemini API key(s) exhausted (all returned 4xx errors)")


async def _chat_groq(messages: List[Dict]) -> str:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set")

    logger.debug("groq request  model={}  messages={}", GROQ_MODEL, len(messages))
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_MODEL,
                    "messages": messages,
                    "temperature": 0.85,
                    "max_completion_tokens": 1024,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        logger.error("Groq HTTP error  status={}  body={}", e.response.status_code, e.response.text[:500])
        raise
    except Exception:
        logger.exception("Unexpected error calling Groq")
        raise
