#!/usr/bin/env bash
#
# 在 Linux / macOS 下启动 A3 案例管理后端（FastAPI + Uvicorn）。
# 将工作目录切换到 backend 根目录后运行 uvicorn，确保加载 backend/.env。
# 若 backend/.venv 不存在或不完整，将自动创建（创建时仅升级 pip）；否则自动 source activate。
# 每次启动前会执行 pip install -e .（不含 .[dev]），以同步项目依赖。
#
# 用法:
#   ./scripts/run-backend.sh
#   ./scripts/run-backend.sh --listen-host 127.0.0.1 --port 8080 --no-reload
#   ./scripts/run-backend.sh --help
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$BACKEND_ROOT"

ensure_venv() {
  local py="$BACKEND_ROOT/.venv/bin/python"
  if [[ -x "$py" ]]; then
    return 0
  fi
  echo "未检测到可用虚拟环境（$py），正在创建 .venv..." >&2
  local base_python=""
  if command -v python3 >/dev/null 2>&1; then
    base_python=$(command -v python3)
  elif command -v python >/dev/null 2>&1; then
    base_python=$(command -v python)
  else
    echo "错误: 未找到 python3 或 python。请安装 Python 3.11+ 后重试。" >&2
    exit 1
  fi
  "$base_python" -m venv "$BACKEND_ROOT/.venv"
  py="$BACKEND_ROOT/.venv/bin/python"
  if [[ ! -x "$py" ]]; then
    echo "错误: 创建虚拟环境失败。若 .venv 已存在但不完整，请删除该目录后重试。" >&2
    exit 1
  fi
  "$py" -m pip install --upgrade pip
}

LISTEN_HOST="0.0.0.0"
PORT="8000"
RELOAD_ARGS=(--reload)

usage() {
  cat <<'EOF'
在 Linux / macOS 下启动 A3 案例管理后端（FastAPI + Uvicorn）。

说明:
  每次启动前会在 .venv 中执行 pip install -e .（不含 .[dev]）。

用法:
  ./scripts/run-backend.sh [--listen-host HOST] [--port PORT] [--no-reload]

选项:
  --listen-host   监听地址，默认 0.0.0.0
  --port          监听端口，默认 8000
  --no-reload     关闭热重载
  -h, --help      显示本说明

示例:
  ./scripts/run-backend.sh --listen-host 127.0.0.1 --port 8080 --no-reload
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --listen-host)
      LISTEN_HOST="${2:?missing value for --listen-host}"
      shift 2
      ;;
    --port)
      PORT="${2:?missing value for --port}"
      shift 2
      ;;
    --no-reload)
      RELOAD_ARGS=()
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      echo "使用 --help 查看说明。" >&2
      exit 1
      ;;
  esac
done

ensure_venv

if [[ -f "$BACKEND_ROOT/.venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "$BACKEND_ROOT/.venv/bin/activate"
fi

echo "同步项目依赖: pip install -e ." >&2
"$BACKEND_ROOT/.venv/bin/python" -m pip install -e "$BACKEND_ROOT"

echo "工作目录: $BACKEND_ROOT"
if ((${#RELOAD_ARGS[@]})); then
  echo "启动: python -m uvicorn app.main:app --host $LISTEN_HOST --port $PORT ${RELOAD_ARGS[*]}"
else
  echo "启动: python -m uvicorn app.main:app --host $LISTEN_HOST --port $PORT"
fi

exec python -m uvicorn app.main:app \
  --host "$LISTEN_HOST" \
  --port "$PORT" \
  "${RELOAD_ARGS[@]}"
