---
name: fin-news-digest
description: Quy trình thu thập, phân loại song song và tổng hợp bản tin tài chính Việt Nam hằng ngày
---

# Kỹ năng Tổng hợp Bản tin Tài chính (Fin-News Digest)

Kỹ năng điều phối quy trình thu thập, phân loại song song bằng subagent Haiku và tổng hợp bản tin tài chính Việt Nam hằng ngày.

Khi người dùng yêu cầu thêm/bớt nguồn, đổi cấu hình, watchlist… đọc file này:
`${CLAUDE_PLUGIN_ROOT}/skills/fin-news-digest/config-guide.md`

## Quy tắc giao tiếp (Bắt buộc)
1. Thông báo trạng thái: Tối đa một câu ngắn gọn cho mỗi giai đoạn từ tập hợp sau:
   - "Đang thu thập tin…"
   - "Đang phân loại…"
   - "Đang tổng hợp bản tin…"
2. Tuyệt đối không bao giờ nhắc đến đường dẫn file, cluster ID (như c-001), mã thoát (exit code), JSON, tên agent/model, tên công cụ, hay trích dẫn nguyên văn đầu ra của CLI.
3. Không tường thuật từng bước (no step-by-step narration).
4. Nếu có lỗi, giải thích bằng lời văn thông thường điều gì đã xảy ra và người dùng có thể làm gì.
5. Thông điệp cuối cùng gửi người dùng là bản tin hoàn chỉnh, kèm tối đa một dòng "Lưu ý:" khi có sự cố thật sự.

## Lệnh CLI chính
- Windows: `"${CLAUDE_PLUGIN_ROOT}\run.cmd" <subcommand>`
- Linux/macOS: `"${CLAUDE_PLUGIN_ROOT}/run.sh" <subcommand>`

| Lệnh | Mô tả |
|---|---|
| `run` | Thu thập tin mới, lọc thời gian và chuẩn bị các lô batch |
| `finish` | Gom kết quả phân loại, lưu cache và gom cụm tin |
| `brief` | Xuất danh sách cụm tin tiêu biểu kèm đường dẫn bài viết gốc |
| `stats` | Hiển thị thời gian thực thi các bước của lượt chạy gần nhất |
| `health` | Kiểm tra tình trạng kết nối các nguồn báo |

## Quy trình thực thi mặc định (Default Procedure)

### Bước 0: Kiểm tra môi trường
Nếu lệnh CLI đầu tiên thất bại do thiếu Python hoặc uv: đọc `${CLAUDE_PLUGIN_ROOT}/INSTALL.md`, giải thích ngắn gọn bằng lời văn thông thường những gì sẽ cài đặt và hỏi ý kiến người dùng trước khi tiến hành.

### Bước 1: Thu thập và chuẩn bị
Gửi thông báo: "Đang thu thập tin…"
Chạy launcher với lệnh `run`. Nếu CLI báo không có bài viết mới, thông báo cho người dùng và kết thúc.

### Bước 2: Phân loại song song (System 1)
Gửi thông báo: "Đang phân loại…"
Từ danh sách file batch (`batch-NN.json`) do `run` in ra:
Dispatch `ceil(new_articles / batch_size)` subagent `fin-news:news-classifier` trong một tin nhắn duy nhất, mỗi subagent chỉ nhận đường dẫn file batch trong prompt và chỉ định rõ `model: "haiku"`.

### Bước 3: Hoàn tất phân loại và gom cụm
Chạy launcher với lệnh `finish`.
Nếu lệnh trả về mã thoát 3 và các dòng `RERUN <đường dẫn batch>`: re-dispatch subagent `fin-news:news-classifier` (kèm `model: "haiku"`) một lượt duy nhất cho các batch đó, sau đó gọi lại `finish`.

### Bước 4: Đọc brief và liên kết nguồn
Chạy launcher với lệnh `brief` để nhận danh sách các cụm tin chấm điểm cao nhất kèm đường link bài báo gốc và đoạn lede.
Mô hình chính tự gộp các cụm tin có nội dung trùng lặp rõ rệt trong quá trình đọc brief và sử dụng liên kết từ cả hai cụm.
(Chỉ dùng `fulltext` khi người dùng yêu cầu đào sâu, chi tiết hoặc khi 2 nguồn trong top 5 mâu thuẫn số liệu, tối đa 3 cụm, mỗi cụm ≤ 2 bài. Nếu có bài báo trả về mang nhãn `[chỉ có tóm tắt RSS]`, hãy thông báo bằng lời văn thân thiện rằng một số bài chỉ tóm tắt được từ đoạn trích ngắn của nguồn tin).

### Bước 5: Tổng hợp và lưu trữ bản tin
Gửi thông báo: "Đang tổng hợp bản tin…"
Tổng hợp bản tin theo đúng Cấu trúc Bản tin bên dưới (dung lượng khoảng 700–900 từ).
Lưu bản tin hoàn chỉnh vào `<FIN_NEWS_HOME>/digests/YYYY-MM-DD.md`.
In toàn bộ bản tin ra màn hình cho người dùng.

## Cấu trúc Bản tin (Digest Template)
Tiêu đề: `# Bản tin Tài chính — DD/MM/YYYY`

### 1. Tiêu điểm hôm nay
Chọn đúng 5 mục quan trọng nhất (theo `profile.digest_items`). Mỗi mục gồm:
- **Tiêu đề in đậm**
- 1–2 câu tóm tắt nội dung cốt lõi và tác động.
- Tối đa 2 liên kết bài viết theo định dạng `[Tên báo](url)`.

### 2. Điểm tin
Chỉ hiển thị các chủ đề có tin tức trong ngày. Mỗi chủ đề là một tiêu đề mục nhỏ kèm các gạch đầu dòng ngắn gọn (mỗi dòng ≤ 25 từ) và đúng 1 liên kết nguồn.
Thứ tự các chủ đề bắt buộc:
1. Vĩ mô & Chính sách
2. Ngân hàng & Tiền tệ
3. Chứng khoán & Doanh nghiệp
4. Bất động sản
5. Vàng & Ngoại tệ
6. Năng lượng & Hàng hoá
7. Trái phiếu

### 3. Theo dõi
Chỉ xuất hiện khi danh sách `profile.watchlist` không rỗng và có tin tức khớp với mã/từ khóa theo dõi.

### 4. Lưu ý về nguồn
Chỉ xuất hiện khi kết quả lệnh `brief` có khối `NGUỒN LỖI` (hoặc lệnh `health`) ghi nhận nguồn tin gặp lỗi kết nối ("Báo X hôm nay không đọc được").

### Quy tắc biên tập nội dung
- Tuyệt đối không dùng các thuật ngữ kỹ thuật trong đầu ra bản tin gửi người dùng: cấm xuất hiện các từ `watchlist`, `config set`, `cluster`, `URL` (thay bằng từ "liên kết"), `[Suy luận]`.
- Bỏ qua các mục không có tin tức (omit empty sections / không hiển thị phần rỗng).
- Chỉ dùng các liên kết có trong kết quả lệnh `brief`; tuyệt đối không tự bịa đặt hay chỉnh sửa liên kết.
- Khi 2 nguồn đưa số liệu mâu thuẫn, nêu rõ điều này trong một vế câu.
- Đánh dấu suy luận hoặc phân tích thêm của mô hình bằng cụm từ "(nhận định của AI)".
- Không loại bỏ tin tức chỉ vì tin đó chỉ có một nguồn duy nhất.
