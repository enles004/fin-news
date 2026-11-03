# Fin-News Workflow — Hướng dẫn cho AI Agents (AGENTS.md)

Tài liệu tóm tắt một trang cho bất kỳ AI nào (Claude, Gemini, Orca workers,...) tham gia vận hành hoặc phát triển hệ thống Fin-News.

## 1. Cấu trúc Dự án
```text
fin-news/
├── .claude-plugin/     # Plugin manifest (plugin.json) & local marketplace (marketplace.json)
├── agents/             # Subagents Claude Code (news-classifier, cluster-merger)
├── commands/           # Slash commands Claude Code (tin-tai-chinh)
├── core/
│   ├── fin_news/       # Gói Python stdlib (config, fetch, dedupe, health, batches, cluster, pipeline, lock, doctor, cache)
│   └── cli.py          # Entrypoint CLI chính: fetch | prepare | collect | cluster | finish | brief | stats | merge | fulltext | health | config | doctor | run
├── defaults/           # Cấu hình gốc (sources.json, topics.json, profile.json)
├── prompts/            # Prompts hệ thống (merge.md)
├── skills/             # Skills Claude Code (fin-news-digest/SKILL.md, config-guide.md)
├── tests/              # Bộ kiểm thử unittest stdlib
├── run.cmd / run.sh    # Bộ khởi động mỏng (tự tìm Python 3.11+ hoặc uv)
└── AGENTS.md, INSTALL.md, SCHEDULE.md, CONFIGURE.md, TROUBLESHOOT.md
```

## 2. Vị trí Lưu trữ Dữ liệu (`FIN_NEWS_HOME`)
- Mặc định: `~/.fin-news/` (hoặc biến môi trường `FIN_NEWS_HOME`).
- Cấu trúc thư mục người dùng:
  - `config/`: Chứa các file `.json` người dùng ghi đè lên defaults, và `CHANGELOG.md`.
  - `cache/`: Chứa `classified.json` lưu trữ kết quả phân loại tái sử dụng.
  - `logs/`: Chứa nhật ký thời gian chạy từng bước `YYYY-MM-DD.log`.
  - `data/YYYY-MM-DD/`: Chứa `raw.json`, `health.json`, `articles.json`, `batches/`, `clusters-raw.json`, `merge-input.json`, `merge-result.json`, `clusters.json`, `fulltext/`.
  - `digests/`: Chứa bản tin đã xuất bản theo ngày `YYYY-MM-DD.md`.
- Thứ tự gộp cấu hình: Defaults < User config < CLI flags.
- Cấu hình fulltext trong profile.json: `fulltext_articles_per_cluster` (mặc định 2, số bài tối đa mỗi cụm), `fulltext_max_chars` (mặc định 3500, giới hạn ký tự bài viết), và `body_hints` (gợi ý thẻ trích xuất toàn cục; tương ứng `sources.<id>.body_hints` cho từng nguồn).

## 3. Các Lệnh CLI Thường dùng
- `run.cmd doctor [--fulltext]`: Kiểm tra môi trường hệ thống hoặc kiểm tra bóc tách toàn văn tất cả nguồn.
- `run.cmd run`: Chạy gom tin (`fetch`), dọn cache và chuẩn bị phân loại (`prepare`).
- `run.cmd finish`: Gom kết quả phân loại, lưu cache và gom cụm tin trong một lệnh (mã thoát 3 nếu có batch cần chạy lại `RERUN`).
- `run.cmd brief`: Xuất danh sách cụm tin hàng đầu kèm liên kết nguồn bài viết gốc (và khối `NGUỒN LỖI` khi có lỗi kết nối feed RSS).
- `run.cmd stats`: In thời gian thực thi các bước của lượt chạy gần nhất.
- `run.cmd collect`: Gom kết quả phân loại từ các subagent (mã thoát 3 nếu có bài lỗi).
- `run.cmd cluster [--skip-merge]`: Gom cụm các bài viết và tạo `merge-input.json` (hoặc xuất thẳng `clusters.json` nếu có `--skip-merge`).
- `run.cmd merge`: Gộp các cụm tin tương đồng từ `merge-result.json` (mã thoát 3 nếu có nhóm lỗi, mã 4 nếu thiếu file).
- `run.cmd fulltext <cluster_id> ...`: Lấy toàn văn các cụm được đánh dấu `needs_fulltext`.
- `run.cmd test-source <ID> [--fulltext]`: Kiểm tra feed RSS hoặc kiểm tra trích xuất toàn văn một nguồn.
- `run.cmd health`: In báo cáo sức khoẻ nguồn tin.
- `run.cmd config get|set|unset <file> <key> [value]`: Quản trị cấu hình.

## 4. Các Thành phần Claude Code Plugin
- Plugin root chính là repo root (`fin-news/`).
- Slash command: `/fin-news:tin-tai-chinh` (tự động kích hoạt skill `fin-news:fin-news-digest`).
- Subagents: `fin-news:news-classifier` (phân loại song song System 1) và `fin-news:cluster-merger` (tuỳ chọn gộp cụm nâng cao), đều dùng `model: haiku`.

## 5. Các Quy Tắc Cốt Lõi
1. **One-off vs Save:** Người dùng chưa rõ ý định thì hỏi "một lần hay lưu lại?". Người dùng nói "cập nhật luôn / từ giờ" thì cập nhật ngay bằng `config set`, ghi vào `CHANGELOG.md` và thông báo sau.
2. **Source Health:** Mọi nguồn lỗi/rỗng đều phải báo cáo minh bạch trong bản tin, không tự sửa hay xoá ngầm.
3. **Mở rộng chức năng:** Báo cáo phạm vi ảnh hưởng và công cụ khả dụng thực tế trước khi xây dựng tính năng mới.
4. **Không phụ thuộc thư viện thứ ba:** Chỉ dùng thư viện chuẩn Python ≥ 3.11. Không `pip install`.
