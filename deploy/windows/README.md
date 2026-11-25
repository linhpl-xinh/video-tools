# Chuyển cutpro.asia sang máy Windows

1. **(Không bắt buộc) Khoá đường hầm cũ:** nếu chép được `<TUNNEL_ID>.json` từ máy Mac vào `C:\Users\<bạn>\.cloudflared\` thì bộ cài dùng lại.
   Không có → bộ cài mở trang Cloudflare để bạn đăng nhập + Authorize, tự tạo đường hầm mới và trỏ `cutpro.asia` về máy này. Không cần USB.
2. **Lấy code:** https://github.com/linhpl-xinh/video-tools → Code → Download ZIP, giải nén (vd `C:\cutpro\video-tools`). Hoặc `git clone`.
3. **Cài:** vào `deploy\windows\`, chuột phải **`CAI DAT.cmd`** → *Run as administrator*. Lần đầu mất 10–20 phút (Python, ffmpeg, cloudflared, Git, thư viện, model ~600MB).
4. **Tắt bản trên máy Mac** (để 2 máy không cùng chạy 1 đường hầm):
   ```bash
   launchctl bootout gui/$(id -u)/asia.cutpro.tunnel; launchctl bootout gui/$(id -u)/asia.cutpro.web
   ```
5. Mở https://cutpro.asia từ điện thoại (tắt Wi-Fi) để kiểm tra.

- Web + đường hầm tự bật khi **đăng nhập** Windows (Task Scheduler: `cutpro-web`, `cutpro-tunnel`). Máy phải bật và đăng nhập sẵn; nên đặt Windows tự đăng nhập hoặc không khoá phiên sau khi khởi động lại.
- Cập nhật code: chạy `update.ps1`.
- Nhật ký: `%USERPROFILE%\.cat-tutorial\web.log`, `tunnel.log`.
