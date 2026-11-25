# Cắt Tutorial – tự động bỏ đoạn in-app/hướng dẫn khỏi video

Kéo một thư mục video thả lên icon **Cat Tutorial**. Công cụ tự xem từng video, tìm các đoạn
quay màn hình điện thoại/app, hướng dẫn từng bước, logo app, kể cả hiệu ứng chuyển cảnh dẫn
vào đó, rồi cắt bỏ và xuất video sạch.

**Chạy hoàn toàn trên máy, miễn phí, không cần tài khoản hay API key, không cần mạng sau khi cài.**

## Cài đặt (mỗi máy làm 1 lần)
Khi dùng qua skill `cat-tutorial`, Claude tự chạy `scripts/setup.sh` ở lần đầu (cài ffmpeg nếu thiếu,
thư viện Python, tải model nhận diện ~1–2GB, vài phút). Máy cần có Homebrew (https://brew.sh).

Muốn có icon kéo-thả trên máy: nhờ Claude chạy
`osacompile -o "<thư mục skill>/scripts/Cat Tutorial.app" "<thư mục skill>/scripts/droplet.applescript"`
rồi kéo app đó vào Dock. App phải nằm trong `scripts/` vì nó gọi `ui.sh` nằm cạnh nó.

## Sử dụng
1. **Kéo thả một hoặc nhiều thư mục** lên icon **Cat Tutorial**, hoặc mở app rồi bấm **Chọn thư mục**
   (giữ `⌘` để chọn nhiều). Giao diện tự mở trong trình duyệt và bắt đầu nhận diện. 20 video ngắn mất khoảng 1 phút.
   - Kéo thêm thư mục khi giao diện đang mở, hoặc bấm **+ Thêm thư mục**: thư mục mới được **thêm vào**,
     không mất thư mục cũ. Thả trùng thư mục đã có thì bỏ qua.
   - Thả **thư mục cha** chứa nhiều thư mục con: công cụ tự lấy từng thư mục con có video.
   - Video được nhóm theo thư mục. Bấm tên thư mục để thu gọn/mở rộng, bấm **×** để gỡ thư mục
     khỏi danh sách (không xoá file).
2. **Soát nhanh ở màn Tổng quan** (nút trên cùng): mỗi video hiện khung **cuối cùng được giữ**
   (viền xanh) và khung **đầu tiên bị cắt** (viền đỏ). Khung xanh sạch thì bấm **✓ Duyệt**,
   hoặc **✓ Duyệt cả thư mục**. Video nào cần sửa thì bấm vào ô để mở chi tiết.
3. **Chỉnh chi tiết ở màn Từng video**:
   - **Dòng thời gian**: vùng **đỏ** sẽ bị cắt. Kéo **tay nắm trắng** để chỉnh, bấm vào dải để tua.
   - **Soát chỗ cắt**: 3 khung giữ (viền xanh) và 3 khung cắt (viền đỏ). Nút bên phải:
     **‹** sớm hơn 1 khung, **›** muộn hơn 1 khung, **⤷** tua tới chỗ cắt, **✕** bỏ đoạn cắt.
   - **Cắt đến hết**: tua tới chỗ muốn cắt rồi bấm. Dùng khi máy giữ sót cảnh mồi.
   - **Cắt một đoạn ở giữa**: tua tới đầu đoạn, bấm **✂ Cắt đoạn** (phím `I`),
     tua tới cuối đoạn, bấm lại (phím `O`). `Esc` để huỷ.
   - Tích **Xem thử bản cắt** để phát và tự nhảy qua các đoạn bị cắt.
   - Bấm **✓ Duyệt video này** → tự chuyển sang video chưa duyệt tiếp theo.
   - Nút **⋯**: xuất riêng video này, xem bản đã xuất, khôi phục gợi ý của máy, không cắt video này.
   - Phím tắt: `Space` phát/dừng, `←` `→` từng khung, `Shift`+`←` `→` 1 giây.
4. Bấm **Xuất N video** (góc phải trên). Nếu còn video chưa duyệt, công cụ sẽ hỏi lại.
   Video của thư mục nào xuất vào `da_cat_tutorial/` **bên trong chính thư mục đó**, giữ nguyên tên file.
   Video gốc không bị đụng tới.

Video đã xuất mà chỉnh lại sẽ hiện nhãn **Cần xuất lại**. Giao diện sáng/tối tự theo cài đặt của máy.
Danh sách thư mục, chỗ cắt đã chỉnh và trạng thái duyệt được **tự lưu** — đóng công cụ rồi mở lại vẫn còn.
Muốn làm lô mới từ đầu: nút **⋯** góc trên → **Xoá danh sách** (không xoá file nào).
File bị đổi tên đuôi (vd thêm `.mp4`) vẫn được nhận lại khi mở lại.
Đóng tab trình duyệt là xong; công cụ tự tắt sau khoảng 2 phút.

Chạy hàng loạt không cần giao diện (xuất thẳng và tạo `bao_cao.html`): `./run.sh "/đường/dẫn/thư mục"`.

## Soát trước khi xuất (bắt buộc)
Trong giao diện, xem phần **Kiểm tra từng mối cắt** của từng video:
- Khung viền xanh còn lộ điện thoại, vệt laser, icon máy quay, mép lật trang → bấm ◀ 1 khung.
- Nghe phần cuối video: nếu lời đọc hướng dẫn bắt đầu từ lúc còn ở cảnh nội dung
  (vd "first click the…") thì video bị kết thúc giữa câu. Công cụ chỉ nhìn hình, không nghe tiếng.
- Cảnh "mồi" không phải điện thoại (vd cảnh người thật nói "để mình chỉ cách làm") có thể còn sót
  một đoạn ngắn trước chỗ cắt.
- Video báo **Lỗi** thì chụp màn hình giao diện, kèm file `~/.cat-tutorial/ui.log`, gửi người phụ trách.

## Cách công cụ nhận diện
1. Lấy 4 khung/giây, dùng model nhận diện ảnh CLIP (mã nguồn mở, chạy trên máy) chấm xem khung
   giống "điện thoại / giao diện app" hay "ảnh thành phẩm".
2. So từng khung với cụm khung chắc chắn là tutorial và cụm khung chắc chắn là nội dung
   trong cùng video, rồi lấp khoảng hở và bỏ khung lẻ.
3. Ở mỗi ranh giới, dò hiệu ứng chuyển cảnh theo từng khung gốc (laser, lật trang, nhoè…)
   và cắt trước khung đầu tiên của hiệu ứng, chừa thêm 1 khung an toàn.

Kết quả thử trên 20 video PN.1911: 19/20 khớp bản cắt tay trong ±1 khung, video còn lại giữ thêm
0,5 giây cảnh mồi.

## Tuỳ chỉnh (cho người phụ trách)
| Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|
| `CAT_TUTORIAL_BACKEND` | `local` | `claude` để dùng Claude API (cần API key, nhận diện thông minh hơn) |
| `CAT_TUTORIAL_OUTDIR` | `da_cat_tutorial` | Tên thư mục xuất |
| `CAT_TUTORIAL_WORKERS` | `4` | Số video xử lý song song |

Các ngưỡng nhận diện nằm đầu file `local_detect.py` (`TUT_PROMPTS`, `CON_PROMPTS`, `MAX_GAP`…).
Gặp kiểu video mới bị nhận sai thì chỉnh ở đó.

Chạy bằng dòng lệnh: `./run.sh "/đường/dẫn/thư mục"`.
