#!/bin/bash
# Mở giao diện Cắt Tutorial (tuỳ chọn: thư mục video). Dùng bởi app kéo-thả.
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$HOME/.cat-tutorial/venv"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if [ ! -x "$VENV/bin/python" ]; then
  osascript -e 'display alert "Chưa cài đặt" message "Hãy mở file Cai dat.command trước."'
  exit 1
fi
if [ "${CAT_TUTORIAL_BACKEND:-local}" = "claude" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
  ANTHROPIC_API_KEY="$(security find-generic-password -s cat-tutorial-anthropic -w 2>/dev/null)"
  export ANTHROPIC_API_KEY
fi
mkdir -p "$HOME/.cat-tutorial"
exec "$VENV/bin/python" -I "$DIR/ui_server.py" "$@" >>"$HOME/.cat-tutorial/ui.log" 2>&1
