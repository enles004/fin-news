# fin-news

Plugin cho Claude Code, tự động tổng hợp bản tin kinh tế và tài chính Việt Nam mỗi ngày từ nhiều nguồn báo.

## Tính năng

- Thu thập tin từ các báo kinh tế và tài chính hàng đầu, loại bỏ bài trùng lặp.
- Nhóm các bài cùng một sự kiện và xếp hạng tin nổi bật.
- Bản tin tóm tắt theo chủ đề, mỗi tin kèm liên kết về bài gốc.
- Báo cáo nguồn nào đang gặp sự cố.
- Thêm nguồn, đổi chủ đề hoặc điều chỉnh số lượng bài ngay trong khi sử dụng.

## Cài đặt

```
/plugin marketplace add enles004/fin-news
/plugin install fin-news@fin-news
```

## Sử dụng

```
/fin-news:tin-tai-chinh
```

Bản tin hiển thị ngay trong Claude và được lưu theo ngày.

## Yêu cầu

Python 3.11 trở lên, hoặc [uv](https://docs.astral.sh/uv/). Hỗ trợ Windows, macOS và Linux. Hướng dẫn chi tiết nằm trong [INSTALL.md](INSTALL.md).

## Giấy phép

[MIT](LICENSE)
