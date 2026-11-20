#!/usr/bin/env bash
# Playwright 用真实 `siku serve --with-ui` 提供 UI 与 API 同源服务。
# 每次运行使用临时 HOME/vault/data，避免读取宿主真实配置。
set -euo pipefail
cd "$(dirname "$0")/../.."

PORT="${SIKU_E2E_PORT:-8765}"
if [ ! -f ui/dist/index.html ]; then
  (cd ui && npm run build)
fi

work="$(mktemp -d)"
export HOME="$work/home"
export XDG_CONFIG_HOME="$work/home"
export APPDATA="$work/home"
mkdir -p "$work/home" "$work/vault" "$work/data"
while IFS= read -r name; do unset "$name"; done < <(compgen -e | grep '^SIKU_' || true)
unset DASHSCOPE_API_KEY 2>/dev/null || true

uv run siku serve \
  --host 127.0.0.1 \
  --port "$PORT" \
  --vault "$work/vault" \
  --data-dir "$work/data" \
  --with-ui \
  --ui-dir ui/dist &
server_pid=$!

cleanup() {
  kill "$server_pid" 2>/dev/null || true
  wait "$server_pid" 2>/dev/null || true
  rm -rf "$work"
}
trap cleanup EXIT INT TERM

wait "$server_pid"
