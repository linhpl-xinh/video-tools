#!/bin/bash
# Chạy Cắt Tutorial ở chế độ web (nhiều người dùng qua Internet, tải lên / tải về).
# Mặc định nghe ở 127.0.0.1:8790 — mở ra ngoài bằng Cloudflare Tunnel, không mở cổng trực tiếp.
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export CAT_TUTORIAL_WEB=1
export CAT_TUTORIAL_PORT="${CAT_TUTORIAL_PORT:-8790}"
mkdir -p "$HOME/.cat-tutorial"
exec "$HOME/.cat-tutorial/venv/bin/python" -I "$DIR/ui_server.py"
