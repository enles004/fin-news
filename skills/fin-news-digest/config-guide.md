# Hướng dẫn Quản trị Cấu hình Fin-News (config-guide.md)

Tài liệu này chứa bảng tra cứu tác vụ và quy tắc quản lý cấu hình khi người dùng yêu cầu thêm/bớt nguồn, đổi cấu hình, watchlist...

## Bảng ánh xạ Yêu cầu → Lệnh CLI

| Yêu cầu của người dùng | Lệnh CLI tương ứng | Ghi chú |
|---|---|---|
| Chạy bản tin mặc định hằng ngày | `run` | Gồm `fetch`, `prepare` và dọn cache |
| Hoàn tất phân loại và gom cụm | `finish` | Gom kết quả `result-*.txt`, cập nhật cache, gom cụm |
| In gói tóm tắt và liên kết nguồn | `brief` | Hiển thị các cụm hàng đầu kèm link bài viết gốc |
| Xem thời gian thực thi các bước | `stats` | Đọc thời gian từ file nhật ký |
| Thu thập tin tức tùy chỉnh | `fetch [--groups ...] [--only ...] [--limit N] [--since 7d] [--query ...]` | Hỗ trợ lọc nhóm, nguồn, từ khóa |
| Chuẩn bị các lô phân loại | `prepare` | Khử trùng lặp, lọc nguồn hỗn hợp, chia batch |
| Gom cụm và chấm điểm tin nâng cao | `cluster [--skip-merge]` | Tạo clusters-raw.json và merge-input.json |
| Gộp các cụm tin tương đồng (tuỳ chọn) | `merge` | Áp dụng kết quả từ subagent cluster-merger |
| Lấy toàn văn khi cần đào sâu | `fulltext <cluster_id> ...` | Tải nội dung chi tiết bài viết |
| Báo cáo sức khoẻ nguồn | `health` | Hiển thị trạng thái các nguồn tin |
| Thêm nguồn tin mới | `add-source <URL> [--id ID] [--group G]` | Tự động dò RSS và kiểm tra thật |
| Kiểm tra thử một nguồn | `test-source <ID>` | Kiểm tra khả năng kết nối và lấy tin |
| Xem cấu hình | `config get <file> <key>` | Đọc giá trị cấu hình |
| Thay đổi cấu hình | `config set <file> <key> <value>` | Ghi đè cấu hình người dùng |
| Khôi phục cấu hình mặc định | `config unset <file> <key>` | Xoá cấu hình người dùng |
| Chẩn đoán hệ thống | `doctor` | Kiểm tra Python, quyền ghi, mạng, nguồn tin |

## Các quy tắc quản lý cấu hình

1. **Quy tắc Lưu hay Không lưu (One-off vs Save):**
   - Nếu người dùng chỉ yêu cầu một lần (hoặc chưa rõ ý định): chạy với cờ tương ứng (ví dụ `--limit N` hoặc `--groups G`).
   - Nếu người dùng nói "cập nhật luôn / từ giờ / lưu lại / save": áp dụng thay đổi bằng `config set`, thông báo sau (file, giá trị cũ → mới, cách hoàn tác), và hệ thống tự động ghi vào `CHANGELOG.md`.
   - Nếu chưa rõ, hỏi người dùng: *"Bạn muốn áp dụng cho một lần chạy này hay lưu lại dùng lâu dài?"*.

2. **Quy tắc Nguồn hỏng (Source Health):**
   - Mọi nguồn lỗi hoặc rỗng phải được báo cáo công khai trong mục "Lưu ý về nguồn" của bản tin (tên nguồn, chi tiết lỗi, thời điểm lỗi).
   - Tuyệt đối không tự ý xóa nguồn, sửa nguồn hay bỏ qua nguồn hỏng trong im lặng.

3. **Quy tắc Mở rộng Tham số (Impact Scope & Verified Tools):**
   - Trước khi thực hiện bất kỳ yêu cầu nào vượt ngoài các tham số và công cụ hiện có:
     a. Báo cáo phạm vi ảnh hưởng (file nào bị thêm/sửa, bản tin hàng ngày có thay đổi định dạng không, tốn thêm token không).
     b. Xác định rõ công cụ và quyền nào thực sự sẵn sàng (script, thư viện chuẩn, kết nối mạng — kiểm tra thực tế, không đoán).
     c. Đề xuất phương án và chỉ bắt tay vào làm sau khi người dùng phê duyệt.
