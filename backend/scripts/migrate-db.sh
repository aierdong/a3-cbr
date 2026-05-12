#!/usr/bin/env bash
#
# 在 Linux / macOS 下于 backend 根目录执行 Alembic 数据库迁移。
# 连接串来自 app.core.config.settings.alembic_database_url（与 alembic/env.py 一致）。
# 若 backend/.venv 不存在或不完整，将自动创建并 pip install -e .；否则自动 source activate。
# 需已配置 backend/.env 或环境变量，且 PostgreSQL 可访问。
#
# 用法:
#   ./scripts/migrate-db.sh
#   ./scripts/migrate-db.sh --operation downgrade --revision -1
#   ./scripts/migrate-db.sh --operation current
#   ./scripts/migrate-db.sh --help
#
# --operation:
#   upgrade   — 默认 --revision head
#   downgrade — 未指定 --revision 时默认为 -1（回退一个版本）
#   current | history | heads — 只读信息，忽略 --revision
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
  echo "未检测到可用虚拟环境（$py），正在创建 .venv 并安装依赖..." >&2
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
  "$py" -m pip install -e "$BACKEND_ROOT"
}

OPERATION="upgrade"
REVISION=""

usage() {
  cat <<'EOF'
在 Linux / macOS 下于 backend 根目录执行 Alembic 数据库迁移。

用法:
  ./scripts/migrate-db.sh [--operation OP] [--revision REV]
  ./scripts/migrate-db.sh [-o OP] [-r REV]

--operation (-o):
  upgrade    默认 --revision head
  downgrade  未指定 --revision 时默认为 -1（回退一个版本）
  current | history | heads  只读信息，忽略 --revision

示例:
  ./scripts/migrate-db.sh
  ./scripts/migrate-db.sh -o downgrade -r -1
  ./scripts/migrate-db.sh --operation current
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --operation | -o)
      OPERATION="${2:?missing value for --operation}"
      shift 2
      ;;
    --revision | -r)
      REVISION="${2:?missing value for --revision}"
      shift 2
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

case "$OPERATION" in
  upgrade)
    [[ -z "$REVISION" ]] && REVISION="head"
    echo "执行: alembic upgrade $REVISION"
    "$BACKEND_ROOT/.venv/bin/alembic" upgrade "$REVISION"
    ;;
  downgrade)
    [[ -z "$REVISION" ]] && REVISION="-1"
    echo "执行: alembic downgrade $REVISION"
    "$BACKEND_ROOT/.venv/bin/alembic" downgrade "$REVISION"
    ;;
  current)
    echo "执行: alembic current"
    "$BACKEND_ROOT/.venv/bin/alembic" current
    ;;
  history)
    echo "执行: alembic history"
    "$BACKEND_ROOT/.venv/bin/alembic" history
    ;;
  heads)
    echo "执行: alembic heads"
    "$BACKEND_ROOT/.venv/bin/alembic" heads
    ;;
  *)
    echo "不支持的 --operation: $OPERATION（应为 upgrade|downgrade|current|history|heads）" >&2
    exit 1
    ;;
esac
