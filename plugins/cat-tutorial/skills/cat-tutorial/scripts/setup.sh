#!/bin/bash
# Cài môi trường cho skill cat-tutorial (không hỏi gì; chạy lại an toàn).
# Môi trường Python dùng chung: ~/.cat-tutorial/venv
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
VENV="$HOME/.cat-tutorial/venv"

need=()
command -v ffmpeg >/dev/null || need+=(ffmpeg)
command -v python3 >/dev/null || need+=(python)
if [ ${#need[@]} -gt 0 ]; then
  if command -v brew >/dev/null; then brew install "${need[@]}"
  else echo "THIẾU: ${need[*]} và không có Homebrew (https://brew.sh)"; exit 2; fi
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "-> Tạo môi trường Python ở $VENV"
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$DIR/requirements.txt"

echo "-> Kiểm tra/tải model nhận diện CLIP (~600MB, chỉ lần đầu)"
"$VENV/bin/python" -c "import sys; sys.path.insert(0, '$DIR'); import local_detect; local_detect._load(); print('   model sẵn sàng')" 2>&1 | grep -v -i warning
chmod +x "$DIR"/*.sh
echo "OK"
