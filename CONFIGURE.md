# Hướng dẫn Quản lý Cấu hình (CONFIGURE.md)

Tài liệu này quy định cách thức AI và người dùng tùy biến và vận hành hệ thống Fin-News.

## 1. Bảng Tác vụ Cấu hình Thường gặp (Spec §6)

| Nhu cầu người dùng | Cách thực hiện |
|---|---|
| Thêm nguồn tin mới | `run.cmd add-source <URL> [--id ID] [--group G]` |
| Lọc theo nhóm nguồn hoặc chủ đề một lần | `run.cmd fetch --groups chuyen-tai-chinh --topics chung-khoan` |
| Đổi số bài tối đa mỗi nguồn một lần | `run.cmd fetch --limit 15` |
| Đổi số bài tối đa mỗi nguồn vĩnh viễn | `run.cmd config set profile max_per_source 15` |
| Tìm kiếm tin tức theo từ khoá | `run.cmd fetch --query "lãi suất" --since 7d` |
| Thêm mã chứng khoán / doanh nghiệp theo dõi | `run.cmd config set profile watchlist '["VIC", "HPG", "VND"]'` |
| Tạm tắt một nguồn | `run.cmd config set sources sources.<ID>.enabled false` |
| Khôi phục cài đặt gốc | `run.cmd config unset <file> <key>` |

---

## 2. Các Quy Tắc Cốt Lõi Bắt Buộc Dành Cho AI

Mọi trợ lý AI làm việc với codebase này phải tuân thủ nghiêm ngặt 3 quy tắc sau:

### Quy tắc 1: Lưu lại hay Chạy một lần (One-off vs Save)
- Nếu người dùng chưa nêu rõ: hãy hỏi *"Bạn muốn áp dụng cho một lần chạy này hay lưu lại dùng lâu dài?"*.
- Nếu người dùng đã nói rõ *"cập nhật luôn / từ giờ / lưu lại / save"*:
  1. Thực hiện thay đổi ngay lập tức vào cấu hình người dùng bằng `config set`.
  2. Báo cáo rõ ràng sau đó: file đã sửa, giá trị cũ → mới, và hướng dẫn hoàn tác (`config unset`).
  3. Mọi thay đổi đều được hệ thống tự động ghi nhật ký vào `<FIN_NEWS_HOME>/config/CHANGELOG.md`.

### Quy tắc 2: Minh bạch Sức khoẻ Nguồn (Source Health)
- Bất kỳ nguồn tin nào gặp lỗi kết nối, lỗi phân tích XML, hoặc trả về 0 bài viết đều phải được liệt kê đầy đủ trong mục **Sức khoẻ nguồn** của bản tin hàng ngày (kèm tên nguồn, chi tiết lỗi, và thời điểm phát sinh lỗi).
- AI **tuyệt đối không tự ý xóa nguồn, sửa nguồn hay che giấu nguồn hỏng**.

### Quy tắc 3: Báo cáo Phạm vi & Công cụ Có sẵn trước khi Dựng mới (Impact Scope & Verified Tools)
Khi người dùng đưa ra yêu cầu vượt quá các tham số sẵn có (ví dụ: cào dữ liệu từ trang web không có RSS, gửi email, tích hợp Telegram):
1. **Báo cáo phạm vi ảnh hưởng:**
   - Những file nào sẽ được tạo/sửa?
   - Định dạng bản tin hằng ngày có bị thay đổi không?
   - Có phát sinh thêm token / chi phí không?
2. **Xác nhận công cụ khả dụng thực tế:**
   - Kiểm tra các script, thư viện chuẩn và quyền truy cập mạng hiện có (kiểm tra thực tế bằng lệnh, không phỏng đoán).
3. **Chỉ triển khai sau khi được phê duyệt:**
   - Trình bày phương án cụ thể và chỉ viết code sau khi người dùng đồng ý.
