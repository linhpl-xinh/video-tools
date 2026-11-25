# Triển khai bản web (cutpro.asia)

Kiến trúc: `ui_server.py` chạy chế độ web ở `127.0.0.1:8790` → Cloudflare Tunnel (`cloudflared`) đưa ra `cutpro.asia`. Không mở cổng nào trên router/firewall.

## Máy chủ Linux (khuyên dùng – chạy 24/7)
Cấu hình tối thiểu: Ubuntu 24.04, 4 CPU, 8GB RAM, 80GB ổ.

```bash
sudo apt update && sudo apt install -y ffmpeg python3-venv git
sudo useradd -m cutpro && sudo -iu cutpro
git clone https://github.com/linhpl-xinh/video-tools && cp -r video-tools/plugins/cat-tutorial/skills/cat-tutorial/scripts ~/app
python3 -m venv ~/.cat-tutorial/venv
~/.cat-tutorial/venv/bin/pip install pillow numpy open_clip_torch torch --extra-index-url https://download.pytorch.org/whl/cpu
```
Rồi cài `cloudflared`, chép khoá đường hầm sang (hoặc tạo đường hầm mới và `cloudflared tunnel route dns`), dùng `cloudflared-config.example.yml` và `sudo cloudflared service install`. Bật web bằng `cutpro-web.service`.

## Windows (máy bàn)
Xem [windows/README.md](windows/README.md) — chạy `windows\CAI DAT.cmd`.

## macOS (đang dùng tạm)
- Bản chạy: `~/.cat-tutorial/app` (chép từ `scripts/`, vì launchd hay bị chặn đọc ~/Downloads).
- Tự bật: `~/Library/LaunchAgents/asia.cutpro.web.plist` (chạy `web.sh` kèm `caffeinate -is`) và `asia.cutpro.tunnel.plist` (`cloudflared tunnel run cutpro`).
- Cập nhật code: `rsync -a --delete scripts/ ~/.cat-tutorial/app/ && launchctl kickstart -k gui/$(id -u)/asia.cutpro.web`
- Nhật ký: `~/.cat-tutorial/web.log`, `~/.cat-tutorial/tunnel.log`.

## Giới hạn (biến môi trường)
`CAT_TUTORIAL_MAX_FILE_MB` (500), `CAT_TUTORIAL_MAX_WS_GB` (5), `CAT_TUTORIAL_MIN_FREE_GB` (10), `CAT_TUTORIAL_TTL_H` (24).
