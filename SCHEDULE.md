# Thiết lập Lịch Chạy Tự Động (SCHEDULE.md)

Fin-News Workflow có thể được kích hoạt tự động theo lịch hằng ngày (ví dụ: 06:30 sáng mỗi ngày trước giờ giao dịch chứng khoán) độc lập trên từng máy tính.

## 1. Lệnh Thực Thi Lập Lịch

Lệnh chạy nền thu thập và chuẩn bị dữ liệu:
- Windows:
  ```cmd
  G:\alright\fin-news\run.cmd run
  ```
- Linux / macOS:
  ```bash
  /path/to/fin-news/run.sh run
  ```

Sau khi lệnh `run` kết thúc, các batch đã sẵn sàng cho agent xử lý tổng hợp bản tin.

---

## 2. Thiết lập trên các Nền tảng

### Windows Task Scheduler
Tạo tác vụ chạy lúc 06:30 sáng hàng ngày bằng PowerShell:
```powershell
$action = New-ScheduledTaskAction -Execute "G:\alright\fin-news\run.cmd" -Argument "run"
$trigger = New-ScheduledTaskTrigger -Daily -At 6:30am
Register-ScheduledTask -TaskName "FinNewsDaily" -Action $action -Trigger $trigger -Description "Gom tin tài chính hằng ngày"
```

### macOS (launchd)
Tạo file `~/Library/LaunchAgents/com.finnews.daily.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.finnews.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/path/to/fin-news/run.sh</string>
        <string>run</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
</dict>
</plist>
```
Nạp lịch:
```bash
launchctl load ~/Library/LaunchAgents/com.finnews.daily.plist
```

### Linux (cron)
Chỉnh sửa crontab với `crontab -e`:
```text
30 6 * * * /path/to/fin-news/run.sh run >> /path/to/fin-news/cron.log 2>&1
```

### Sử dụng Lệnh `/schedule` trong Claude
Nếu sử dụng Claude Code, bạn có thể gõ trực tiếp:
```text
/schedule "06:30 hằng ngày: Chạy lệnh /fin-news:tin-tai-chinh và xuất bản tin"
```

---

## 3. Cách Kiểm Tra Lịch Đã Chạy Thành Công

Sau thời điểm lên lịch, kiểm tra các dấu hiệu sau:
1. Thư mục ngày mới đã được tạo:
   - Thư mục dữ liệu: `<FIN_NEWS_HOME>/data/YYYY-MM-DD/`
   - File `raw.json`, `articles.json` và các file `batches/batch-*.json` đã được sinh ra.
2. Kiểm tra file trạng thái nguồn:
   - `<FIN_NEWS_HOME>/data/YYYY-MM-DD/health.json` ghi nhận tình trạng fetch.
3. Khi phiên tổng hợp hoàn tất:
   - File bản tin hoàn chỉnh xuất hiện tại `<FIN_NEWS_HOME>/digests/YYYY-MM-DD.md`.
