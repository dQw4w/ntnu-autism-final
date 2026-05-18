import os
import sys
import json
import logging
import socket
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List
from loguru import logger

from characters import CHARACTERS
from scenarios import SCENARIOS
from llm_service import chat_with_llm, GeminiServerError, get_paid_cost_data


# ── Loguru setup ──────────────────────────────────────────────────────────────

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG",
    colorize=True,
)

# Route uvicorn / fastapi stdlib logs through loguru
class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[assignment]
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
for _name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
    logging.getLogger(_name).handlers = [_InterceptHandler()]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def _get_scenario(character_id: str, scenario_id: str):
    if character_id not in SCENARIOS:
        return None
    for s in SCENARIOS[character_id]:
        if s["id"] == scenario_id:
            return s
    return None


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    port = int(os.environ.get("PORT", 8000))
    local_ip = _get_local_ip()
    logger.info("\n" + "=" * 52)
    logger.info("  🌈  自閉症互動體驗平台")
    logger.info("=" * 52)
    logger.info("  本機：http://localhost:{}", port)
    logger.info("  區網：http://{}:{}  ← 同 WiFi 裝置用這個", local_ip, port)
    logger.info("=" * 52)
    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="自閉症互動體驗平台", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ────────────────────────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    character_id: str
    scenario_id: str
    messages: List[Message]


class HelperRequest(BaseModel):
    character_id: str
    scenario_id: str
    messages: List[Message]


class CompletionCheckRequest(BaseModel):
    character_id: str
    scenario_id: str
    messages: List[Message]


# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "OK!"}


@app.get("/api/characters")
def get_characters():
    return [
        {
            "id": k,
            "name": v["name"],
            "age": v["age"],
            "gender": v["gender"],
            "level": v["level"],
            "description": v["description"],
            "avatar": v["avatar"],
            "color": v["color"],
            "gradient": v["gradient"],
            "traits": v["traits"],
        }
        for k, v in CHARACTERS.items()
    ]


@app.get("/api/characters/{character_id}/scenarios")
def get_scenarios(character_id: str):
    if character_id not in SCENARIOS:
        raise HTTPException(status_code=404, detail="Character not found")
    return SCENARIOS[character_id]


@app.post("/api/chat")
async def chat(request: ChatRequest):
    if request.character_id not in CHARACTERS:
        raise HTTPException(status_code=404, detail="Character not found")

    character = CHARACTERS[request.character_id]
    scenario = _get_scenario(request.character_id, request.scenario_id)

    system_prompt = character["system_prompt"]
    if scenario:
        system_prompt += (
            f"\n\n【當前情境】\n"
            f"情境：{scenario['name']}\n"
            f"{scenario['context']}\n"
            f"使用者扮演的角色：{scenario['role']}"
        )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in request.messages:
        messages.append({"role": msg.role, "content": msg.content})

    logger.info("chat  character={}  scenario={}  turns={}", request.character_id, request.scenario_id, len(request.messages))
    try:
        response = await chat_with_llm(messages)
        return {"response": response}
    except GeminiServerError as e:
        logger.warning("chat Gemini server error  character={}  scenario={}", request.character_id, request.scenario_id)
        raise HTTPException(status_code=503, detail="gemini_server_error")
    except Exception as e:
        logger.exception("chat endpoint failed  character={}  scenario={}", request.character_id, request.scenario_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/helper")
async def helper(request: HelperRequest):
    if request.character_id not in CHARACTERS:
        raise HTTPException(status_code=404, detail="Character not found")

    if not request.messages:
        return {"advice": "開始對話後，我可以給你一些溝通建議！試著跟對方說說話吧。"}

    character = CHARACTERS[request.character_id]
    scenario = _get_scenario(request.character_id, request.scenario_id)
    char_name = character["name"]

    conversation_text = "\n".join(
        f"{'你（使用者）' if m.role == 'user' else char_name}: {m.content}"
        for m in request.messages[-12:]
    )

    scenario_info = ""
    if scenario:
        scenario_info = f"情境：{scenario['name']}\n目標：{scenario['goal']}\n"

    helper_prompt = (
        f"你是一個專業的自閉症溝通輔導顧問。你正在觀察一段使用者與自閉症者的互動，給予使用者建議。\n\n"
        f"【角色資訊】\n"
        f"姓名：{char_name}（{character['age']}歲）\n"
        f"障礙程度：{character['level']}\n"
        f"主要特質：{', '.join(character['traits'])}\n\n"
        f"【情境】\n{scenario_info}\n"
        f"【對話記錄】\n{conversation_text}\n\n"
        f"請給予使用者2-3條簡短、具體、實用的建議。格式：\n\n"
        f"🔍 **觀察**：（一句話說明{char_name}最近行為的意義）\n\n"
        f"💡 **建議**：（具體告訴使用者下一步可以怎麼做）\n\n"
        f"✅ **做得好**：（如果使用者有做對的地方，給予肯定；如果沒有，省略此項）\n\n"
        f"用繁體中文回應，語氣溫和且具教育性，聚焦於正向改進。"
    )

    messages = [
        {"role": "system", "content": helper_prompt},
        {"role": "user", "content": "請根據以上對話給予建議。"},
    ]

    logger.info("helper  character={}  turns={}", request.character_id, len(request.messages))
    try:
        advice = await chat_with_llm(messages)
        return {"advice": advice}
    except Exception as e:
        logger.exception("helper endpoint failed  character={}", request.character_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/check-completion")
async def check_completion(request: CompletionCheckRequest):
    if request.character_id not in CHARACTERS:
        raise HTTPException(status_code=404, detail="Character not found")

    scenario = _get_scenario(request.character_id, request.scenario_id)
    character = CHARACTERS[request.character_id]

    if not scenario or not request.messages:
        return {"completed": False, "summary": ""}

    conversation_text = "\n".join(
        f"{'使用者' if m.role == 'user' else character['name']}: {m.content}"
        for m in request.messages
    )

    check_prompt = (
        f"你是一個評估系統。根據以下對話，判斷使用者是否已完成任務目標。\n\n"
        f"任務目標：{scenario['goal']}\n"
        f"成功條件：{scenario['success_condition']}\n\n"
        f"對話記錄：\n{conversation_text}\n\n"
        f"請回應一個 JSON 格式（只回應 JSON，不要其他文字）：\n"
        f'{{"completed": true或false, "summary": "一段話（繁體中文）說明完成情況和使用者的溝通表現亮點"}}'
    )

    messages = [
        {"role": "system", "content": check_prompt},
        {"role": "user", "content": "請評估是否完成任務。"},
    ]

    logger.info("check-completion  character={}  turns={}", request.character_id, len(request.messages))
    last_err = None
    for attempt in range(3):
        try:
            response = await chat_with_llm(messages)
            cleaned = response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            result = json.loads(cleaned)
            if "completed" not in result:
                raise ValueError("missing 'completed' field")

            return result
        except Exception as e:
            last_err = e
            logger.warning("check-completion attempt {}/3 failed: {}", attempt + 1, e)

    logger.error("check-completion all retries failed: {}", last_err)
    return {
        "completed": len(request.messages) >= 6,
        "summary": "（評估系統發生錯誤）無法自動判斷，請自行回顧對話是否達成任務目標。",
    }


@app.get("/api/paid-cost")
def paid_cost():
    return get_paid_cost_data()


# ── Static frontend (must be LAST) ────────────────────────────────────────────

FRONTEND_DIR = os.environ.get(
    "FRONTEND_DIR",
    os.path.join(os.path.dirname(__file__), "..", "frontend"),
)

if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    logger.warning("Frontend dir not found: {}", FRONTEND_DIR)

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
