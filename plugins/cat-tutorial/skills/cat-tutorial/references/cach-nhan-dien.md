# Cách nhận diện (chế độ offline) và cách chỉnh khi sai

Code: `scripts/local_detect.py` (nhận diện), `scripts/cat_tutorial.py` (trích khung, cắt, xuất, báo cáo),
`scripts/ui_server.py` + `scripts/ui/index.html` (giao diện).

## Thuật toán
1. **Chấm từng khung (4 khung/giây)** bằng CLIP ViT-B-32 (`laion2b_s34b_b79k`): xác suất khung giống
   `TUT_PROMPTS` (điện thoại, giao diện app, tay cầm máy, bút cảm ứng, trang profile, logo app, lưới ảnh)
   so với `CON_PROMPTS` (ảnh chân dung/thời trang full màn hình, người thật ngoài trời).
2. **Tâm cụm trong cùng video**: khung chắc chắn tutorial (p > `SEED_HI`=0.75) và khung chắc chắn nội dung
   (p < `SEED_LO`=0.05 và cách mọi khung tutorial ≥2s). Mỗi khung gán nhãn theo tâm gần hơn — vì cảnh
   tutorial trong 1 video cùng bàn/cùng máy nên rất giống nhau, kể cả khi màn hình điện thoại đang hiện ảnh nội dung.
3. **Làm sạch nhãn**: bỏ khung tutorial lẻ (khung loé sáng giữa 2 ảnh nội dung) → lấp khoảng nội dung
   ≤ `MAX_GAP`=2s kẹp giữa tutorial → bỏ đoạn tutorial < `MIN_TUT`=1s hoặc không có khung chắc chắn.
4. **Tinh chỉnh ranh giới tới từng khung**: trong cửa sổ `SEARCH_BACK`=2s trước mốc (+1s sau), tính độ thay đổi
   cục bộ lớn nhất giữa 2 khung liên tiếp (lưới 8×8). Các chuỗi thay đổi mạnh (> `STRONG`=25, ≥0.08s) là ứng viên
   hiệu ứng chuyển cảnh; chọn chuỗi làm khung **trước** giống nội dung và khung **sau** giống tutorial nhất
   (đo bằng tâm cụm). Lần ngược qua các khung thay đổi > `WEAK`=10 (tối đa 0.5s), thêm 1 khung mở màn nếu đổi nhẹ,
   rồi **chừa thêm 1 khung an toàn**.

## Lỗi đã gặp → cách đã sửa
| Hiện tượng | Nguyên nhân | Sửa |
|---|---|---|
| Phần tutorial bị đứt quãng, còn sót mẩu | điện thoại hiện ảnh Santa nên CLIP chấm ≈0 | gán nhãn theo tâm cụm trong video (bước 2) + lấp khoảng 2s |
| Cắt sớm gần 2s (PN.1911 v7) | khung loé sáng khi chuyển 2 ảnh nội dung bị chấm là tutorial rồi được lấp nối | bỏ khung lẻ TRƯỚC khi lấp khoảng |
| Bắt nhầm hiệu ứng chuyển giữa 2 ảnh nội dung | chọn chuỗi thay đổi gần mốc nhất | chấm ứng viên bằng độ chênh "trước giống nội dung / sau giống tutorial" |
| Lọt 1 khung đầu hiệu ứng (vệt laser nhỏ) | ranh giới đúng khung nhưng khung đó đã có mép hiệu ứng | chừa 1 khung an toàn |
| Chỉ nhận 3/15 video | file mất đuôi `.mp4` (tên `…._`) | `is_video()` đọc header file; `out_name()` xuất tên có `.mp4` |

Giới hạn còn lại: cảnh mồi không phải điện thoại (PN.1911 v18: cảnh xe jeep "I'll demonstrate…") vẫn được giữ;
không nghe tiếng nên lời đọc có thể bị ngắt giữa câu.

## Kiểm tra lại sau khi chỉnh ngưỡng
Điểm cắt tay chuẩn của lô `~/Downloads/PN.1911 - noel photoshoot` (giây, video `noel photoshoot N.mp4`, tutorial kéo tới hết video):

```
1:3.7 2:6.4 3:3.95 4:6.92 5:7.5 6:8.55 7:6.12 8:5.1 9:6.2 10:7.18
11:5.78 12:5.1 13:5.75 14:5.25 15:3.88 16:3.88 17:5.1 18:7.22 19:6.93 20:7.9
```
(v18: 7.22 là đầu cảnh jeep mồi; máy cắt ~7.72 lúc bắt đầu lật trang — chấp nhận được.)

Đo nhanh độ lệch (khung @30fps) chỉ bằng nhận diện, không xuất:
```python
import sys; sys.path.insert(0, "<thư mục skill>/scripts")
import cat_tutorial as c, local_detect as L
from pathlib import Path
GT = {1:3.7, 2:6.4, ...}
for n, gt in GT.items():
    p = Path(f"~/Downloads/PN.1911 - noel photoshoot/noel photoshoot {n}.mp4").expanduser()
    segs, _ = L.find_segments(p, c.probe(p), c.extract, lambda m: None)
    print(n, round((c.merge(segs)[0][0] - gt) * 30, 1) if segs else "KHÔNG THẤY")
```
Mục tiêu: |lệch| ≤ 1 khung ở ≥19/20 video, không video nào bị cắt mất nội dung (lệch âm lớn).

## Biến môi trường
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `CAT_TUTORIAL_BACKEND` | `local` | `claude` = dùng Claude API (cần `ANTHROPIC_API_KEY`) |
| `CAT_TUTORIAL_OUTDIR` | `da_cat_tutorial` | tên thư mục xuất (đổi để không ghi đè bản cũ) |
| `CAT_TUTORIAL_WORKERS` | `4` | số video xử lý song song |
| `CAT_TUTORIAL_NO_OPEN` | — | đặt =1 để không tự mở trình duyệt/báo cáo |
| `CAT_TUTORIAL_PORT` | ngẫu nhiên | cổng cố định cho giao diện |
