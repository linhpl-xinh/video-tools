# Video tools – plugin cho Claude Code

Hiện có 1 plugin:

| Plugin | Làm gì |
|---|---|
| **cat-tutorial** | Tự nhận diện và cắt bỏ đoạn in-app / tutorial (quay điện thoại, hướng dẫn bấm CapCut/TikTok, logo app, kêu gọi vào profile, kể cả hiệu ứng chuyển cảnh dẫn vào) khỏi hàng loạt video. Giữ phần khoe kết quả, xuất vào `da_cat_tutorial/` cạnh video gốc, soát từng mối cắt. Chạy hoàn toàn trên máy, không cần API key. |

## Cài đặt (mỗi người làm 1 lần)

Repo công khai, không cần tài khoản hay đăng nhập GitHub.

**1. Thêm marketplace và cài plugin** — gõ trong ô chat của Claude Code:
```
/plugin marketplace add linhpl-xinh/video-tools
/plugin install cat-tutorial@video-tools
```
(Hoặc ngoài terminal: `claude plugin marketplace add linhpl-xinh/video-tools` rồi `claude plugin install cat-tutorial@video-tools`.)

**2. Dùng** — nói bình thường với Claude, ví dụ:
- "Cắt phần in-app tutorial ra khỏi các video trong thư mục ~/Downloads/PN.1911"
- "Mở giao diện để mình tự duyệt chỗ cắt cho 2 thư mục này"
- "Video tải từ Drive bị mất đuôi .mp4, sửa giúp"

Hoặc gọi thẳng: `/cat-tutorial:cat-tutorial`.

Lần đầu dùng, Claude tự cài ffmpeg (cần [Homebrew](https://brew.sh)), thư viện Python và tải model nhận diện (~1–2GB, vài phút).

## Cập nhật
Gõ `/plugin` → **Marketplaces** → chọn `video-tools` → **Update marketplace**, hoặc:
```
/plugin marketplace update video-tools
/plugin update cat-tutorial@video-tools
```
Muốn tự cập nhật: `/plugin` → Marketplaces → bật auto-update cho `video-tools`.

## Bản web (cutpro.asia)
Ngoài plugin, giao diện cắt còn chạy được như một trang web: người dùng kéo thả video lên, duyệt chỗ cắt rồi tải bản đã cắt về (.zip), không cần cài gì.

- Bật: `CAT_TUTORIAL_WEB=1` (xem `scripts/web.sh`), nghe ở `127.0.0.1:8790`, mở ra Internet bằng Cloudflare Tunnel — không mở cổng router.
- Mỗi trình duyệt một khu riêng (cookie ngẫu nhiên); các lệnh đọc ổ đĩa máy chủ (chọn/dán thư mục, mở Finder) bị tắt.
- Giới hạn mặc định: 500MB/video, 5GB/người, chừa 10GB ổ trống, tự xoá sau 24 giờ. Đổi bằng `CAT_TUTORIAL_MAX_FILE_MB`, `CAT_TUTORIAL_MAX_WS_GB`, `CAT_TUTORIAL_MIN_FREE_GB`, `CAT_TUTORIAL_TTL_H`.
- Video được tải lên theo mảnh 32MB vì Cloudflare (gói Free) chặn request >100MB.

## Dành cho người bảo trì
- Code skill: `plugins/cat-tutorial/skills/cat-tutorial/` (`SKILL.md`, `scripts/`, `references/`).
- Mỗi lần phát hành: sửa code → **tăng `version`** trong `plugins/cat-tutorial/.claude-plugin/plugin.json` (vd 1.0.0 → 1.0.1) → commit → push. Không tăng version thì máy mọi người vẫn giữ bản cũ.
- Sau khi chỉnh thuật toán nhận diện, chạy lại bộ kiểm tra trong `references/cach-nhan-dien.md` trước khi phát hành.
- Thêm plugin mới: tạo `plugins/<tên>/` và thêm một mục vào `.claude-plugin/marketplace.json`.
