---
name: cat-tutorial
description: Tự nhận diện và cắt bỏ đoạn in-app / tutorial (quay màn hình điện thoại, hướng dẫn bấm app CapCut/TikTok, logo app, kêu gọi vào profile, kể cả hiệu ứng chuyển cảnh dẫn vào) khỏi hàng loạt video quảng cáo/khoe hiệu ứng AI, giữ lại phần khoe kết quả, xuất ra thư mục da_cat_tutorial và soát từng mối cắt. Dùng skill này bất cứ khi nào người dùng muốn bỏ/cắt phần tutorial, in-app, hướng dẫn, đoạn quay điện thoại khỏi video hoặc cả thư mục video (vd "cắt phần in-app tutorial ra khỏi các video trong thư mục PN.xxxx", "bỏ đoạn hướng dẫn cuối clip", "cut the tutorial part out of these TikToks"), muốn mở giao diện duyệt/chỉnh điểm cắt, hoặc video tải từ Google Drive bị mất đuôi .mp4 không mở được — kể cả khi họ không nhắc tên công cụ.
---

# Cắt Tutorial

Video dạng "khoe hiệu ứng AI" thường có 2 phần: **nội dung** (ảnh/video thành phẩm full màn hình, cảnh hook) rồi **tutorial in-app** (quay điện thoại, bấm CapCut/TikTok, logo app, profile). Skill này giữ phần nội dung, bỏ phần tutorial, xuất video sạch và soát kỹ chỗ cắt.

Công cụ chạy **hoàn toàn trên máy** (model nhận diện ảnh CLIP + dò hiệu ứng chuyển cảnh theo từng khung), không cần API key. Trên lô PN.1911 (20 video) nó khớp bản cắt tay ±1 khung ở 19/20 video. Với kiểu video mới, độ chính xác chưa được kiểm chứng — vì vậy bước soát (QC) không được bỏ.

Mọi script nằm trong `${CLAUDE_SKILL_DIR}/scripts/` (thư mục chứa file SKILL.md này).

## Quy trình

### 1. Chuẩn bị (lần đầu trên máy)
Nếu chưa có `~/.cat-tutorial/venv/bin/python`, chạy `bash ${CLAUDE_SKILL_DIR}/scripts/setup.sh` (cài ffmpeg nếu thiếu, thư viện Python, tải model ~600MB — vài phút, chạy nền nếu được). Dùng `~/.cat-tutorial/venv/bin/python -I` cho mọi script Python của skill.

### 2. Kiểm tra đầu vào
- Xác định (các) thư mục video. Thư mục cha chứa nhiều thư mục con có video cũng được — giao diện tự tách.
- **File mất đuôi `.mp4`** (tên kết thúc bằng `._`, `.._` — hay gặp khi tải nhiều file từ Google Drive vì zip cắt tên dài): công cụ vẫn nhận theo nội dung nên cắt được bình thường. Nhưng Finder sẽ hiện icon trắng và không mở được, nên nói với người dùng và đề nghị chạy `fix_extensions.py <thư mục>` (có `--dry-run` để xem trước; ghi nhật ký hoàn tác ở `~/.cat-tutorial/rename_logs/`). Đổi tên là thay đổi file của người dùng — hỏi trước, trừ khi họ đã đồng ý. Nếu đang có giao diện mở thư mục đó, đổi tên xong thì giao diện tự nhận lại tên mới khi mở lại.
- **Đừng ghi đè kết quả cũ**: nếu `<thư mục>/da_cat_tutorial/` đã có file (vd bản cắt tay), xuất sang tên khác bằng biến `CAT_TUTORIAL_OUTDIR=da_cat_tutorial_v2` và nói rõ với người dùng, hoặc hỏi họ.

### 3. Chọn cách chạy
- **Người dùng muốn tự xem/duyệt/chỉnh** (nhắc giao diện, muốn xem trước, muốn kéo chỉnh): mở giao diện duyệt.
  `nohup bash ${CLAUDE_SKILL_DIR}/scripts/ui.sh "<thư mục 1>" "<thư mục 2>" >/dev/null 2>&1 &`
  Trình duyệt tự mở. Giao diện có: màn Tổng quan (cặp khung Giữ/Cắt của mọi video + nút Duyệt), màn Từng video (timeline kéo chỉnh, ‹ › chỉnh từng khung, phím I/O cắt đoạn giữa, "Cắt đến hết"), nút Xuất. Danh sách và trạng thái duyệt được tự lưu ở `~/.cat-tutorial/session.json`. Nếu đã có giao diện đang chạy, lệnh trên chỉ thêm thư mục vào đó. Hướng dẫn chi tiết cho người dùng: [references/huong-dan-giao-dien.md](references/huong-dan-giao-dien.md).
- **Người dùng giao cho Claude làm hết** ("cắt giúp", "xử lý thư mục này"): chạy hàng loạt
  `CAT_TUTORIAL_NO_OPEN=1 bash ${CLAUDE_SKILL_DIR}/scripts/run.sh "<thư mục>" </dev/null`
  Khoảng 4 giây/video (4 video song song); lô >30 video thì chạy nền. Kết quả: `<thư mục>/da_cat_tutorial/*.mp4` + `bao_cao.html` (thời điểm cắt, ảnh trước/sau mỗi mối cắt). Log in ra từng video: `✓ tên: a-b s` là đoạn đã bỏ.

### 4. Soát (QC) — bắt buộc trước khi báo xong
Khách của người dùng đã từng phàn nàn vì lỗi lọt khung, nên soát đến từng khung:
1. `python ${CLAUDE_SKILL_DIR}/scripts/qc_sheet.py "<thư mục>/da_cat_tutorial" /tmp/qc.jpg` rồi **xem ảnh** (Read). Mỗi hàng là ~10 khung cuối của 1 video đã xuất.
2. Khung cuối phải là nội dung sạch. Lọt dù chỉ 1 khung có mép điện thoại, vệt laser, icon máy quay, mép lật trang, nhoè chuyển động lạ → cắt lại video đó sớm hơn:
   `python ${CLAUDE_SKILL_DIR}/scripts/recut.py "<video gốc>" "<thư mục>/da_cat_tutorial" --keep-until <giây>`
   (lấy mốc từ log/bao_cao.html, lùi 1–2 khung = 1/fps giây mỗi khung; soát lại ảnh sau khi cắt).
3. Ngược lại, nếu thấy máy cắt mất cả phần nội dung (vd video giữ <2s, hoặc cắt từ 0s) → mở video xem kỹ, cắt lại bằng `recut.py --cut a-b`, hoặc mở giao diện cho người dùng tự quyết.
4. Video có tutorial ở giữa (log có nhiều đoạn) → soát thêm quanh từng mối nối bằng cách trích khung (`ffmpeg -ss <t> ...`) hoặc xem `bao_cao.html`.

### 5. Báo cáo
Ngắn gọn, theo từng thư mục: số video, đã xuất vào đâu, video nào đã sửa tay sau QC và vì sao. Luôn nhắc các giới hạn có thật:
- Công cụ chỉ nhìn hình, không nghe tiếng: nếu lời đọc hướng dẫn bắt đầu khi còn ở cảnh nội dung (vd "first click the…"), video kết thúc giữa câu — người dùng cần nghe lại phần cuối.
- Cảnh "mồi" không phải điện thoại (người thật nói "để mình chỉ cách làm") có thể còn sót một đoạn ngắn.

## Khi nhận diện sai nhiều
Đọc [references/cach-nhan-dien.md](references/cach-nhan-dien.md) (cách thuật toán chạy, các ngưỡng, lỗi đã gặp và cách sửa, bộ điểm cắt chuẩn PN.1911 để kiểm tra lại sau khi chỉnh). Có thể chuyển sang `CAT_TUTORIAL_BACKEND=claude` (dùng Claude API, cần `ANTHROPIC_API_KEY`) cho video khó.
