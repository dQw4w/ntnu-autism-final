# 理解光譜的另一面 — 自閉症互動體驗平台

透過與 AI 模擬的自閉症者互動，認識自閉症光譜的多元面貌。

## 角色

| 角色 | 年齡 | 程度 | 特質 |
| --- | --- | --- | --- |
| 🧒 小宇 | 5歲 | 中重度自閉症 | 仿說、感官敏感、固著行為 |
| 👦 阿強 | 17歲 | 高功能／亞斯伯格 | 計畫固著、特殊興趣（天文）、白目發言 |
| 👧 小星 | 20歲 | 輕度自閉症 | 說話大聲、容易分心、需要明確指令 |

每個角色各有 3 個情境，共 9 個互動關卡。輔導顧問 AI 可隨時分析對話並給予溝通建議。

## 快速啟動

### 方式一：Docker（推薦）

```bash
cp .env.example .env
docker compose up -d

# 等待 Ollama 啟動後，下載模型（首次需要幾分鐘）
docker exec -it ntnu-autism-final-ollama-1 ollama pull qwen2:7b

# 開啟瀏覽器
open http://localhost:8000
```

### 方式二：本機開發

```bash
# 建立虛擬環境
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# 設定環境變數（選擇其中一個 LLM）
export LLM_PROVIDER=ollama          # 需要本機跑 Ollama
# export LLM_PROVIDER=gemini        # 需要 GEMINI_API_KEY
# export LLM_PROVIDER=groq          # 需要 GROQ_API_KEY

# 從 backend 目錄啟動
cd backend
FRONTEND_DIR=../frontend uvicorn main:app --reload --port 8000

# 開啟瀏覽器
open http://localhost:8000
```

## LLM 設定

| Provider | 費用 | 中文支援 | 設定方式 |
| --- | --- | --- | --- |
| **Ollama** | 免費（本地） | ⭐⭐⭐ qwen2:7b 推薦 | 安裝 Ollama |
| **Gemini** | 免費（15次/分鐘） | ⭐⭐⭐ | 申請 GEMINI_API_KEY |
| **Groq** | 免費（有速率限制） | ⭐⭐ | 申請 GROQ_API_KEY |

## 專案結構

```text
ntnu-autism-final/
├── backend/
│   ├── main.py          # FastAPI 主程式
│   ├── characters.py    # 三個角色定義與 system prompt
│   ├── scenarios.py     # 每個角色的情境設定
│   ├── llm_service.py   # LLM 整合（Ollama / Gemini / Groq）
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html       # 單頁應用
│   ├── css/style.css
│   └── js/app.js
├── docker-compose.yml
└── .env.example
```

## API

| 方法 | 路由 | 說明 |
| --- | --- | --- |
| GET | `/api/characters` | 取得所有角色 |
| GET | `/api/characters/{id}/scenarios` | 取得角色情境 |
| POST | `/api/chat` | 對話（character_id, scenario_id, messages） |
| POST | `/api/helper` | 取得輔導建議 |
| POST | `/api/check-completion` | 評估任務完成度 |
