# Hướng dẫn Khắc phục Sự cố (TROUBLESHOOT.md)

Tài liệu hướng dẫn xử lý các lỗi thường gặp trong quá trình vận hành Fin-News.

## 1. Dữ liệu nén Gzip không đọc được
- **Hiện tượng:** Feed trả về nội dung nhị phân khó đọc hoặc lỗi `ElementTree.ParseError`.
- **Nguyên nhân:** Một số trang báo (VietnamPlus, Tinnhanhchungkhoan, Nhân Dân) trả dữ liệu nén gzip mà không gắn header `Content-Encoding: gzip`.
- **Giải pháp:** Hàm `fetch.fetch_url` tự động kiểm tra 2 byte đầu tiên (`0x1f 0x8b`) và giải nén bằng `gzip.decompress()` kể cả khi không có header. Nếu gặp trang mới tương tự, kiểm tra lại dữ liệu thô.

## 2. Thử thách Cookie JavaScript (Lao Động style)
- **Hiện tượng:** Trang báo không trả RSS ngay mà trả trang HTML chứa script `document.cookie="D1N=..."; window.location.reload(true);`.
- **Giải pháp:** Hệ thống đã tích hợp bộ giải mã regex: trích xuất giá trị cookie từ script, đính kèm vào header `Cookie: NAME=VALUE` và tự động gửi lại request. Nếu trang đổi tên cookie hoặc thuật toán, cập nhật regex tại `fetch.fetch_url`.

## 3. Nguồn tin trả về 404 hoặc bị thay đổi đường dẫn RSS
- **Hiện tượng:** Lệnh `test-source <ID>` báo lỗi HTTP 404 hoặc `SourceHealth status="error"`.
- **Giải pháp:**
  1. Chạy lệnh tự động dò lại feed:
     ```cmd
     run.cmd add-source https://trang-bao.vn
     ```
  2. Nếu tìm được URL mới, cập nhật qua `config set`:
     ```cmd
     run.cmd config set sources sources.<ID>.url "https://trang-bao.vn/rss/moi.rss"
     ```

## 4. Mạng bị chặn hoặc Lỗi SSL / Chứng chỉ
- **Hiện tượng:** `urllib.error.URLError: [SSL: CERTIFICATE_VERIFY_FAILED]`.
- **Giải pháp:**
  - Kiểm tra kết nối mạng bằng `run.cmd doctor`.
  - Trên mạng doanh nghiệp chặn kiểm tra thu hồi chứng chỉ (revocation check), cần cấu hình cờ `--ssl-revoke-best-effort` cho curl hoặc cập nhật certifi/root CA của Windows.

## 5. Thiếu Python ≥ 3.11 hoặc uv
- **Hiện tượng:** Chạy `python` báo *Python was not found...* từ Windows Store alias.
- **Giải pháp:**
  - Chạy launcher `run.cmd` (hoặc `run.sh`). Launcher sẽ hỏi bạn có đồng ý cài đặt `uv` hay không.
  - Sau khi đồng ý, `uv` và Python 3.12 sẽ được cài đặt tự động vào thư mục người dùng mà không cần quyền quản trị viên.

## 6. Khóa tiến trình bị kẹt (Stale Lock)
- **Hiện tượng:** Báo lỗi `Another run is currently active (started at ...). Exiting.`.
- **Nguyên nhân:** Lượt chạy trước bị ngắt đột ngột (tắt máy, kill process) khiến file `.lock` chưa kịp xoá tại `data/YYYY-MM-DD/.lock`.
- **Giải pháp:**
  - Khóa sẽ tự động được coi là hết hạn (stale) và bị ghi đè nếu tồn tại quá 2 giờ.
  - Nếu cần chạy ngay lập tức, xoá file lock thủ công:
    ```powershell
    Remove-Item "$env:FIN_NEWS_HOME\data\YYYY-MM-DD\.lock" -Force
    ```

## 7. Các mã thoát trong quy trình (Pipeline Exit Codes)
- **Mã thoát 3 (`collect` hoặc `merge`):**
  - Khi chạy `collect`: một số bài viết bị thiếu kết quả phân loại hoặc sai schema. Kỹ năng sẽ tự động khởi chạy lại các ID lỗi một lần duy nhất.
  - Khi chạy `merge`: file `merge-result.json` có nhóm cluster không hợp lệ (ID lạ, trùng lặp hoặc singleton). Hệ thống đã áp dụng các nhóm hợp lệ còn lại và thoát mã 3 để kỹ năng có thể chạy lại subagent `cluster-merger` một lần.
- **Mã thoát 4 (`merge`):**
  - Không tìm thấy `merge-result.json`. Cần đảm bảo subagent `cluster-merger` đã hoàn thành và lưu file trước khi chạy lệnh `merge`.
- **Trạng thái trích xuất fulltext (`fulltext/_status.json`):** Trạng thái mỗi bài gồm `"full"` (toàn văn), `"summary_only"` (bóc tách rỗng, chuyển dùng summary_raw của RSS) hoặc `"error"` (lỗi tải URL, không bị nuốt lỗi).
