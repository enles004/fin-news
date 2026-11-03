# Hướng dẫn Cài đặt & Khởi tạo (INSTALL.md)

Tài liệu này dành cho người dùng và các trợ lý AI hỗ trợ cài đặt hệ thống **Fin-News Workflow**.

## 1. Yêu cầu Hệ thống
- Hệ điều hành: Windows, macOS, hoặc Linux.
- Môi trường chạy: Python ≥ 3.11 hoặc `uv`.
- Không yêu cầu quyền Administrator hay root.

## 2. Kiểm tra & Cài đặt Môi trường

Trước khi cài đặt bất kỳ công cụ nào, AI **phải hỏi ý kiến người dùng** và nhận được sự đồng ý. Tuyệt đối không cài đặt ngầm.

### Trên Windows
1. Mở PowerShell và kiểm tra:
   ```powershell
   python --version
   uv --version
   ```
2. Nếu máy chưa có Python ≥ 3.11 và chưa có `uv`, hỏi người dùng:
   > *"Hệ thống chưa có Python 3.11+ hoặc uv. Bạn có muốn cài đặt uv (không cần quyền Admin) để tiếp tục không?"*
3. Khi được đồng ý:
   - Lưu ý thiết lập execution policy nếu bị chặn script:
     ```powershell
     Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
     ```
   - Chạy lệnh cài đặt `uv`:
     ```powershell
     irm https://astral.sh/uv/install.ps1 | iex
     ```
   - Cài đặt Python 3.12 thông qua `uv`:
     ```powershell
     uv python install 3.12
     ```

### Trên macOS & Linux
1. Kiểm tra:
   ```bash
   python3 --version
   uv --version
   ```
2. Nếu thiếu, hỏi người dùng và cài đặt qua:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   uv python install 3.12
   ```

## 3. Cấu hình Thư mục Dữ liệu (`FIN_NEWS_HOME`)

Mặc định toàn bộ dữ liệu cấu hình cá nhân, cache và bản tin lưu tại `~/.fin-news/`.
Bạn có thể thay đổi bằng biến môi trường `FIN_NEWS_HOME`:

- Windows (PowerShell):
  ```powershell
  $env:FIN_NEWS_HOME = "D:\fin_news_data"
  [Environment]::SetEnvironmentVariable("FIN_NEWS_HOME", "D:\fin_news_data", "User")
  ```
- Linux / macOS:
  ```bash
  export FIN_NEWS_HOME="$HOME/fin_news_data"
  ```

## 4. Chẩn đoán Hệ thống (`doctor`)

Chạy lệnh kiểm tra tính toàn vẹn của môi trường:
- Windows:
  ```cmd
  run.cmd doctor
  ```
- Linux / macOS:
  ```bash
  ./run.sh doctor
  ```

Lệnh `doctor` sẽ kiểm tra:
- Phiên bản Python ≥ 3.11
- Quyền ghi vào thư mục `FIN_NEWS_HOME`
- Kết nối mạng
- Tình trạng các nguồn tin trong danh sách

## 5. Chạy thử Lần đầu

Kiểm tra quá trình thu thập tin mẫu:
```cmd
run.cmd run --limit 2
```

## 6. Cài đặt Plugin Claude Code (Cài plugin)

Plugin Fin-News là plugin độc lập, tự chứa (self-contained) với plugin root nằm ngay tại thư mục gốc của repository.

### Kiểm tra tính hợp lệ
Trước khi cài đặt, bạn có thể kiểm tra tính hợp lệ của manifest và cấu trúc plugin bằng lệnh:
```bash
claude plugin validate <path to fin-news>
```

### Các tùy chọn cài đặt:

- **(a) Dùng thử khi phát triển (try it):**
  Chạy Claude với tùy chọn chỉ định thư mục:
  ```bash
  claude --plugin-dir "<path to fin-news>"
  ```
  Sau khi chỉnh sửa mã nguồn hoặc prompt/agent, thực hiện lệnh `/reload-plugins` trong phiên Claude để nạp lại plugin mà không cần khởi động lại.

- **(b) Cài đặt cố định (permanent), từ GitHub (khuyến nghị):**
  Thêm marketplace từ repo công khai:
  ```bash
  claude plugin marketplace add enles004/fin-news
  ```
  (Trong một session Claude: `/plugin marketplace add enles004/fin-news`. Nếu muốn cài từ một bản sao trên máy, thay `enles004/fin-news` bằng đường dẫn thư mục repo.)
  Sau đó cài đặt plugin từ marketplace `fin-news`:
  ```bash
  claude plugin install fin-news@fin-news
  ```
  *(hoặc sử dụng giao diện lệnh `/plugin ...` trực tiếp trong một session Claude).*

- **(c) Phân phối qua Git host (distribution):**
  Để phân phối qua một Git host, chính repository này hoạt động như một marketplace vì plugin root là repo root (file `.claude-plugin/marketplace.json` trỏ tới `./`).

### Lệnh kích hoạt
Sau khi cài đặt, bạn có thể gọi lệnh với định danh đầy đủ theo scope:
```text
/fin-news:tin-tai-chinh
```
Lệnh này sẽ tự động kích hoạt kỹ năng `fin-news:fin-news-digest` và các subagent `fin-news:news-classifier`, `fin-news:cluster-merger`.
