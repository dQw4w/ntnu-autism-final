import os
import httpx
from typing import List, Dict
from loguru import logger

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2:7b")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

logger.info(
    "LLM config  provider={} model={}  host={}",
    LLM_PROVIDER,
    OLLAMA_MODEL if LLM_PROVIDER == "ollama" else GROQ_MODEL,
    OLLAMA_HOST if LLM_PROVIDER == "ollama" else "—",
)


async def chat_with_llm(messages: List[Dict]) -> str:
    provider = LLM_PROVIDER.lower()
    logger.debug("chat_with_llm  provider={}  messages={}", provider, len(messages))
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
        logger.error(
            "Ollama HTTP error  status={}  body={}",
            e.response.status_code,
            e.response.text[:500],
        )
        raise
    except Exception:
        logger.exception("Unexpected error calling Ollama")
        raise


async def _chat_gemini(messages: List[Dict]) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set")

    system_instruction = None
    contents = []

    for msg in messages:
        if msg["role"] == "system":
            system_instruction = msg["content"]
        elif msg["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
        elif msg["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": msg["content"]}]})

    request_body: Dict = {
        "contents": contents,
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 1024},
    }
    if system_instruction:
        request_body["system_instruction"] = {"parts": [{"text": system_instruction}]}

    logger.debug("gemini request  messages={}", len(contents))
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}",
                json=request_body,
            )
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except httpx.HTTPStatusError as e:
        logger.error("Gemini HTTP error  status={}  body={}", e.response.status_code, e.response.text[:500])
        raise
    except Exception:
        logger.exception("Unexpected error calling Gemini")
        raise


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
                    "max_tokens": 1024,
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
