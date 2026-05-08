#!/bin/bash
set -e

detach_str=""
while (( "$#" )); do
    case "$1" in
        -d|--detach)
            echo "--detach 模式"
            detach_str="-d"
            shift
            ;;
        -?*)
            echo "Unknown option: $1"
            exit 1
            ;;
        *)
            break
            ;;
    esac
done

project_path="./"
if [ -n "$1" ]; then
    project_path="$1"
fi
if [[ ! $project_path =~ /$ ]]; then
    project_path=$project_path/
fi

export PROJECT_NAME=$(sed -n "s/^[[:space:]]*name[[:space:]]*=[[:space:]]*['\"]\([^'\"]*\)['\"].*/\1/p" ${project_path}pyproject.toml)
export PROJECT_VERSION=$(sed -n "s/^[[:space:]]*version[[:space:]]*=[[:space:]]*['\"]\([^'\"]*\)['\"].*/\1/p" ${project_path}pyproject.toml)

# ── Guard: image must exist ───────────────────────────────────────────────────
if ! docker image inspect ${PROJECT_NAME}:${PROJECT_VERSION} > /dev/null 2>&1; then
    echo "❌ 找不到 image ${PROJECT_NAME}:${PROJECT_VERSION}"
    echo "   請先執行 ./build.sh 來建立 image"
    exit 1
fi

MODEL=${OLLAMA_MODEL:-qwen2:7b}

# ── Start ollama first (no-op if already running) ─────────────────────────────
docker compose up -d ollama

# ── Wait for ollama ───────────────────────────────────────────────────────────
echo "▶ 等待 Ollama 就緒..."
TRIES=0
MAX_TRIES=40
until curl -sf --max-time 3 http://localhost:11434/api/tags > /dev/null 2>&1; do
    TRIES=$((TRIES + 1))
    if [ "$TRIES" -ge "$MAX_TRIES" ]; then
        echo ""
        echo "❌ Ollama 超過 2 分鐘未就緒，請檢查："
        docker compose logs ollama --tail 20
        exit 1
    fi
    printf '.'; sleep 3
done
echo ""

# ── Pull model if missing ─────────────────────────────────────────────────────
if ! docker compose exec ollama ollama list | grep -q "$MODEL"; then
    echo "▶ 下載模型 $MODEL（首次需要幾分鐘）..."
    docker compose exec ollama ollama pull "$MODEL"
fi

# ── Start app ─────────────────────────────────────────────────────────────────
echo "🚀 Starting Docker containers..."
docker compose up --no-deps ${detach_str} app
echo "✅ Docker containers are up and running."

# ── Print URLs (only in detach mode, otherwise logs are streaming) ────────────
if [ -n "$detach_str" ]; then
    LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null \
        || ipconfig getifaddr en1 2>/dev/null \
        || echo "127.0.0.1")
    echo ""
    echo "  本機：http://localhost:8000"
    echo "  區網：http://$LOCAL_IP:8000"
fi
