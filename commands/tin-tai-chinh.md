---
name: tin-tai-chinh
description: Thu thập, phân loại và tổng hợp bản tin tài chính Việt Nam hằng ngày
usage: /fin-news:tin-tai-chinh [preset|yêu cầu tự do]
---

Kích hoạt skill `fin-news:fin-news-digest` để thực hiện toàn bộ luồng công việc:
1. Chạy pipeline thu thập tin tức và chuẩn bị các lô phân loại (`run`).
2. Điều phối subagent Haiku phân loại tin song song (`fin-news:news-classifier`).
3. Hoàn tất phân loại, gom cụm (`finish`), và đọc gói tóm tắt kèm liên kết nguồn (`brief`).
4. Tổng hợp và hiển thị bản tin trong phiên làm việc, đồng thời lưu file vào `digests/YYYY-MM-DD.md`.
