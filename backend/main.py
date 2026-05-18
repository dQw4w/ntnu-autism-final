import os
import sys
import json
import logging
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from characters import CHARACTERS
from scenarios import SCENARIOS
from llm_service import chat_with_llm, GeminiServerError, get_paid_cost_data
from database import init_db, get_db, User, Session as DBSession


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
    await init_db()
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


class CreateUserRequest(BaseModel):
    nickname: str

class CreateSessionRequest(BaseModel):
    user_id: int
    character_id: str
    scenario_id: str

class SaveSessionRequest(BaseModel):
    messages: List[Message]
    result: Optional[bool] = None
    summary: Optional[str] = None

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


# ── User & Session records ────────────────────────────────────────────────────

@app.post("/api/users")
async def create_user(request: CreateUserRequest, db: AsyncSession = Depends(get_db)):
    nick = request.nickname.strip()[:50]
    if not nick:
        raise HTTPException(status_code=400, detail="Nickname cannot be empty")
    user = User(nickname=nick)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("new user  id={}  nickname={}", user.id, user.nickname)
    return {"id": user.id, "nickname": user.nickname}


@app.post("/api/sessions")
async def create_session(request: CreateSessionRequest, db: AsyncSession = Depends(get_db)):
    sess = DBSession(
        user_id=request.user_id,
        character_id=request.character_id,
        scenario_id=request.scenario_id,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    logger.info("new session  id={}  user={}  char={}  scenario={}", sess.id, request.user_id, request.character_id, request.scenario_id)
    return {"id": sess.id}


@app.post("/api/sessions/{session_id}/save")
async def save_session(session_id: int, request: SaveSessionRequest, db: AsyncSession = Depends(get_db)):
    sess = await db.get(DBSession, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    sess.saved_at = datetime.now(timezone.utc)
    sess.result = request.result
    sess.summary = request.summary
    sess.messages_json = json.dumps([{"role": m.role, "content": m.content} for m in request.messages], ensure_ascii=False)
    await db.commit()
    logger.info("session saved  id={}  result={}", session_id, request.result)
    return {"ok": True}


# ── Admin panel ───────────────────────────────────────────────────────────────

_CHAR_NAMES = {k: v["name"] for k, v in CHARACTERS.items()}
_SCENARIO_NAMES = {
    sid: s["name"]
    for scenarios in SCENARIOS.values()
    for s in scenarios
    for sid in [s["id"]]
}

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(token: str = "", db: AsyncSession = Depends(get_db)):
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token or token != admin_token:
        raise HTTPException(status_code=403, detail="Invalid or missing ?token=")

    users_result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = users_result.scalars().all()

    sessions_result = await db.execute(select(DBSession).order_by(DBSession.started_at.desc()))
    sessions = sessions_result.scalars().all()

    user_map = {u.id: u.nickname for u in users}

    total = len(sessions)
    judged = [s for s in sessions if s.result is not None]
    completed = sum(1 for s in judged if s.result)
    rate = f"{completed/len(judged)*100:.0f}%" if judged else "—"

    def fmt_dt(dt):
        if not dt:
            return "—"
        return dt.strftime("%Y-%m-%d %H:%M") if dt else "—"

    def result_badge(r):
        if r is None:
            return "<span style='color:#6b7280'>— 未評估</span>"
        return "<span style='color:#16a34a'>✅ 完成</span>" if r else "<span style='color:#dc2626'>❌ 未完成</span>"

    rows_html = ""
    for s in sessions:
        msgs = json.loads(s.messages_json) if s.messages_json else []
        char_name = _CHAR_NAMES.get(s.character_id, s.character_id)
        scenario_name = _SCENARIO_NAMES.get(s.scenario_id, s.scenario_id)
        nickname = user_map.get(s.user_id, f"uid:{s.user_id}")

        chat_html = "".join(
            f"<div style='margin:4px 0;padding:6px 10px;border-radius:6px;"
            f"background:{'#dbeafe' if m['role']=='user' else '#f3f4f6'};'>"
            f"<b>{'你' if m['role']=='user' else char_name}</b>：{m['content']}</div>"
            for m in msgs
        )

        rows_html += f"""
        <tr>
          <td>{s.id}</td>
          <td><b>{nickname}</b></td>
          <td>{char_name}</td>
          <td>{scenario_name}</td>
          <td>{fmt_dt(s.started_at)}</td>
          <td>{fmt_dt(s.saved_at)}</td>
          <td>{result_badge(s.result)}</td>
          <td>{len(msgs)}</td>
          <td style='max-width:200px;font-size:12px'>{s.summary or '—'}</td>
          <td>
            <details>
              <summary style='cursor:pointer;color:#6c63ff'>展開（{len(msgs)} 則）</summary>
              <div style='margin-top:8px;font-size:13px'>{chat_html or '（無訊息）'}</div>
            </details>
          </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>管理後台 — 自閉症互動體驗</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 24px; background: #f9fafb; color: #111; }}
    h1 {{ margin: 0 0 4px; font-size: 22px; }}
    .stats {{ display: flex; gap: 20px; margin: 16px 0 24px; flex-wrap: wrap; }}
    .stat {{ background: white; border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px 22px; }}
    .stat-n {{ font-size: 28px; font-weight: 800; color: #6c63ff; }}
    .stat-l {{ font-size: 13px; color: #6b7280; margin-top: 2px; }}
    .filter {{ margin-bottom: 16px; }}
    .filter input {{ padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px; width: 220px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    th {{ background: #6c63ff; color: white; padding: 10px 12px; text-align: left; font-size: 13px; white-space: nowrap; }}
    td {{ padding: 9px 12px; border-bottom: 1px solid #f3f4f6; font-size: 13px; vertical-align: top; }}
    tr:hover td {{ background: #fafafa; }}
    details summary::-webkit-details-marker {{ display: none; }}
  </style>
</head>
<body>
  <h1>🛠 管理後台</h1>
  <p style="color:#6b7280;margin:0 0 12px">自閉症互動體驗平台・用戶記錄</p>

  <div class="stats">
    <div class="stat"><div class="stat-n">{len(users)}</div><div class="stat-l">總用戶數</div></div>
    <div class="stat"><div class="stat-n">{total}</div><div class="stat-l">總對話場次</div></div>
    <div class="stat"><div class="stat-n">{completed}/{len(judged)}</div><div class="stat-l">完成 / 已評估</div></div>
    <div class="stat"><div class="stat-n">{rate}</div><div class="stat-l">完成率</div></div>
  </div>

  <div class="filter">
    <input id="filter" placeholder="🔍 輸入暱稱篩選..." oninput="filterRows(this.value)">
  </div>

  <table id="tbl">
    <thead>
      <tr>
        <th>#</th><th>暱稱</th><th>角色</th><th>情境</th>
        <th>開始時間</th><th>儲存時間</th><th>結果</th>
        <th>訊息數</th><th>摘要</th><th>對話紀錄</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>

  <script>
    function filterRows(q) {{
      q = q.toLowerCase();
      document.querySelectorAll('#tbl tbody tr').forEach(r => {{
        r.style.display = r.cells[1].textContent.toLowerCase().includes(q) ? '' : 'none';
      }});
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(html)


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
