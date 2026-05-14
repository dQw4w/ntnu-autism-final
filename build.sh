#!/bin/bash
set -e

NO_CACHE=""
FRONTEND_BUST=""
while (( "$#" )); do
    case "$1" in
        -n|--no-cache)
            echo "--no-cache 模式（重裝 dependencies）"
            NO_CACHE="--no-cache"
            shift
            ;;
        -f|--frontend)
            echo "--frontend 模式（強制重建 frontend 層）"
            FRONTEND_BUST="--build-arg FRONTEND_BUST=$(date +%s)"
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

echo "▶ Building ${PROJECT_NAME}:${PROJECT_VERSION}..."
docker build --progress=plain $NO_CACHE $FRONTEND_BUST \
    -t ${PROJECT_NAME}:${PROJECT_VERSION} \
    -f backend/Dockerfile \
    .

echo ""
echo "✅ Build 完成：${PROJECT_NAME}:${PROJECT_VERSION}"
echo "   執行 ./up.sh 來啟動服務"
