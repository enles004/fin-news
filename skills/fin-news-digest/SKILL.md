---
name: fin-news-digest
description: Quy trình thu thập, phân loại song song và tổng hợp bản tin tài chính Việt Nam hằng ngày
---

# Kỹ năng Tổng hợp Bản tin Tài chính (Fin-News Digest)

Kỹ năng này điều phối quy trình phân tích tin tức tài chính Việt Nam kết hợp giữa công cụ dòng lệnh Python (CLI) và các subagent Claude.

## 1. Bảng ánh xạ Yêu cầu → Lệnh CLI (theo Spec §6)

| Yêu cầu của người dùng | Lệnh CLI tương ứng | Ghi chú |
|---|---|---|
| Chạy bản tin mặc định hằng ngày | `run` | Gồm `fetch` và `prepare` |
| Thu thập tin tức tùy chỉnh | `fetch [--groups ...] [--only ...] [--limit N] [--since 7d] [--query ...]` | Hỗ trợ lọc nhóm, nguồn, từ khóa |
| Chuẩn bị các lô phân loại | `prepare` | Khử trùng lặp, lọc nguồn hỗn hợp, chia batch 25 bài |
| Tổng hợp kết quả phân loại | `collect` | Gộp `result-NN.json`, trả mã thoát 3 nếu có bài lỗi |
| Gom cụm và chấm điểm tin | `cluster [--skip-merge]` | Tạo clusters-raw.json và merge-input.json (hoặc xuất thẳng clusters.json nếu có cờ) |
| Gộp các cụm tin tương đồng | `merge` | Áp dụng kết quả từ subagent cluster-merger, ghi clusters.json (mã thoát 3 nếu có lỗi nhóm) |
| Lấy toàn văn các cụm điểm cao | `fulltext <cluster_id> ...` | Tải nội dung chi tiết bài viết |
| Báo cáo sức khoẻ nguồn | `health` | Hiển thị trạng thái các nguồn tin |
| Thêm nguồn tin mới | `add-source <URL> [--id ID] [--group G]` | Tự động dò RSS và kiểm tra thật |
| Kiểm tra thử một nguồn | `test-source <ID>` | Kiểm tra khả năng kết nối và lấy tin |
| Xem cấu hình | `config get <file> <key>` | Đọc giá trị cấu hình |
| Thay đổi cấu hình | `config set <file> <key> <value>` | Ghi đè cấu hình người dùng |
| Khôi phục cấu hình mặc định | `config unset <file> <key>` | Xoá cấu hình người dùng |
| Chẩn đoán hệ thống | `doctor` | Kiểm tra Python, quyền ghi, mạng, nguồn tin |

## 2. Quy tắc quan trọng

1. **Quy tắc Lưu hay Không lưu (One-off vs Save):**
   - Nếu người dùng chỉ yêu cầu một lần (hoặc chưa rõ ý định): chạy với cờ tương ứng (ví dụ `--limit N` hoặc `--groups G`).
   - Nếu người dùng nói "cập nhật luôn / từ giờ / lưu lại / save": áp dụng thay đổi bằng `config set`, thông báo sau (file, giá trị cũ → mới, cách hoàn tác), và tự động ghi vào `CHANGELOG.md`.
   - Nếu chưa rõ, hỏi người dùng: *"Bạn muốn áp dụng cho một lần chạy này hay lưu lại dùng lâu dài?"*.
2. **Quy tắc Nguồn hỏng (Source Health):**
   - Mọi nguồn lỗi hoặc rỗng phải được báo cáo công khai trong mục "Sức khoẻ nguồn" của bản tin (tên nguồn, chi tiết lỗi, thời điểm lỗi từ khi nào).
   - Tuyệt đối không tự ý xóa nguồn, sửa nguồn hay bỏ qua nguồn hỏng trong im lặng.
3. **Quy tắc Mở rộng Tham số (Impact Scope & Verified Tools):**
   - Trước khi thực hiện bất kỳ yêu cầu nào vượt ngoài các tham số và công cụ hiện có:
     a. Báo cáo phạm vi ảnh hưởng (file nào bị thêm/sửa, bản tin hàng ngày có thay đổi định dạng không, tốn thêm token không).
     b. Xác định rõ công cụ và quyền nào thực sự sẵn sàng (script, thư viện chuẩn, kết nối mạng — kiểm tra thực tế, không đoán).
     c. Đề xuất phương án và chỉ bắt tay vào làm sau khi người dùng phê duyệt.

## 3. Quy trình thực thi chính (Main Procedure)

### Thiết lập môi trường và launcher:
- **Cách gọi launcher theo hệ điều hành:**
  - Trên Windows: `"${CLAUDE_PLUGIN_ROOT}\run.cmd" <subcommand>`
  - Trên Linux / macOS: `"${CLAUDE_PLUGIN_ROOT}/run.sh" <subcommand>`
  Tất cả các lệnh con trong Bảng ánh xạ ở Mục 1 (`run`, `fetch`, `prepare`, `collect`, `cluster`, `merge`, `fulltext`, `health`, `add-source`, `test-source`, `config`, `doctor`) đều là tham số `<subcommand>` truyền cho launcher tương ứng ở trên.
- **Vị trí dữ liệu (`FIN_NEWS_HOME`):**
  Dữ liệu lưu trữ luôn nằm tại `FIN_NEWS_HOME` (mặc định là `~/.fin-news`), nằm hoàn toàn bên ngoài thư mục plugin để đảm bảo an toàn và bảo toàn nguyên vẹn qua các lần cập nhật plugin.

### Các bước thực hiện:
1. **Khởi chạy chuẩn bị:**
   Chạy launcher với lệnh `run` (hoặc `fetch` theo tham số rồi `prepare`).
2. **Phân loại song song (System 1):**
   Đọc danh sách các file batch được tạo trong `data/YYYY-MM-DD/batches/batch-NN.json` (nằm trong `FIN_NEWS_HOME`).
   Khởi chạy các subagent `fin-news:news-classifier` song song, truyền rõ ràng tham số `model: "haiku"` trên mọi lượt dispatch. Mỗi subagent tuân thủ hướng dẫn từ `${CLAUDE_PLUGIN_ROOT}/prompts/classify.md`, xử lý lô tin trong `batch-NN.json` và ghi kết quả vào `result-NN.json` tương ứng.
3. **Thu thập kết quả:**
   Chạy launcher với lệnh `collect`.
   Nếu lệnh trả về mã thoát 3 (còn ID lỗi/thiếu): khởi chạy lại `fin-news:news-classifier` (kèm `model: "haiku"`) một lượt duy nhất cho các ID được báo.
4. **Gom cụm sơ bộ:**
   Chạy launcher với lệnh `cluster` để tạo `clusters-raw.json` và `merge-input.json`.
5. **Gộp cụm tương đồng (Second Pass):**
   Khởi chạy subagent `fin-news:cluster-merger` (truyền rõ ràng `model: "haiku"` trên mọi lượt dispatch) để đọc `merge-input.json`, đánh giá và gộp cụm theo hướng dẫn trong `${CLAUDE_PLUGIN_ROOT}/prompts/merge.md`, rồi ghi kết quả vào `merge-result.json`.
   Chạy launcher với lệnh `merge`. Nếu lệnh trả về mã thoát 3 (có nhóm lỗi): chạy lại subagent `fin-news:cluster-merger` (kèm `model: "haiku"`) một lượt duy nhất.
   Sau khi lệnh thành công, đọc danh sách các cụm ứng viên được in ra màn hình.
6. **Trích xuất tin toàn văn:**
   Với các cụm được đánh dấu `needs_fulltext: true`, chạy launcher với lệnh `fulltext <cluster_id> ...`.
7. **Tổng hợp bản tin (System 2):**
   Tổng hợp thông tin theo hướng dẫn trong `${CLAUDE_PLUGIN_ROOT}/prompts/synthesize.md` và mẫu `${CLAUDE_PLUGIN_ROOT}/prompts/digest-template.md`.
   Đảm bảo 4 phần theo đúng thứ tự:
   - 1. Tiêu điểm hôm nay
   - 2. Theo chủ đề
   - 3. Theo dõi (Watchlist)
   - 4. Sức khoẻ nguồn
8. **Lưu trữ và xuất bản:**
   Ghi bản tin hoàn chỉnh vào `digests/YYYY-MM-DD.md` trong thư mục `FIN_NEWS_HOME` và in ra trong giao diện chat cho người dùng đọc.
