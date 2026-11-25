#!/bin/bash
# Chạy engine cắt tutorial cho các thư mục/file được truyền vào.
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$HOME/.cat-tutorial/venv"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ ! -x "$VENV/bin/python" ]; then
  echo "Chưa cài đặt. Hãy mở file 'Cai dat.command' trước."; read -r -p "Nhấn Enter để đóng..."; exit 1
fi
# Chế độ mặc định 'local' chạy hoàn toàn trên máy. Chỉ chế độ 'claude' mới cần API key.
if [ "${CAT_TUTORIAL_BACKEND:-local}" = "claude" ]; then
  if [ -z "$ANTHROPIC_API_KEY" ]; then
    ANTHROPIC_API_KEY="$(security find-generic-password -s cat-tutorial-anthropic -w 2>/dev/null)"
    export ANTHROPIC_API_KEY
  fi
  if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "Chế độ claude cần API key. Hãy chạy lại 'Cai dat.command'."; read -r -p "Nhấn Enter để đóng..."; exit 1
  fi
fi

"$VENV/bin/python" -I "$DIR/cat_tutorial.py" "$@"
code=$?
echo
if [ $code -eq 0 ]; then
  osascript -e 'display notification "Đã cắt xong, xem thư mục da_cat_tutorial" with title "Cắt Tutorial"'
  echo "XONG. Video đã cắt nằm trong thư mục da_cat_tutorial cạnh video gốc."
else
  echo "Có lỗi (mã $code). Chụp màn hình cửa sổ này gửi người phụ trách."
fi
read -r -p "Nhấn Enter để đóng..."
