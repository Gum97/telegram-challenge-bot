# Bot Thử Thách AI Meeting

Bot Telegram quản lý cuộc thi ứng dụng AI vào công việc: check-in hàng tuần, chia sẻ workflow AI, bảng xếp hạng tự động.

## Tính năng

- **Đăng ký team** — mỗi user đăng ký một team qua DM
- **Check-in hàng tuần** — nộp ảnh NotebookLM + tóm tắt buổi họp, AI xác thực
- **Chia sẻ AI** — gửi bài mô tả workflow AI, bot chấm điểm bằng OpenAI (tối đa 3 chủ đề khác nhau/tuần)
- **Bảng xếp hạng** — tự động cập nhật sau mỗi lần nộp, gửi tự động vào group mỗi thứ 2
- **Lưu dữ liệu** — Google Sheets (production) hoặc JSON local (test/dev)

## Chạy nhanh với Docker

```bash
# 1. Cấu hình biến môi trường
cp .env.example .env
# Chỉnh sửa .env

# 2. (Nếu dùng Google Sheets) đặt file credentials
cp ~/Downloads/service-account.json credentials.json

# 3. Build và chạy
docker compose up -d

# Xem log
docker compose logs -f
```

## Chạy thủ công (Python)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Chỉnh sửa .env

python bot.py
```

## Biến môi trường

| Biến | Bắt buộc | Mặc định | Mô tả |
|------|:--------:|----------|-------|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Token từ [@BotFather](https://t.me/BotFather) |
| `GROUP_CHAT_ID` | ❌ | — | Chat ID group để forward thông báo |
| `OPENAI_API_KEY` | ❌ | — | API key OpenAI (bỏ trống → dùng heuristic) |
| `OPENAI_MODEL` | ❌ | `gpt-4o` | Model OpenAI |
| `SPREADSHEET_ID` | ❌ | — | ID Google Sheets (bỏ trống → lưu JSON local) |
| `GOOGLE_SHEETS_CREDENTIALS_FILE` | ❌ | `credentials.json` | Đường dẫn file service account |
| `TOTAL_WEEKS` | ❌ | `10` | Số tuần thử thách |
| `CHECKIN_POINTS` | ❌ | `20` | Điểm mỗi lần check-in |
| `MAX_SHARES_PER_WEEK` | ❌ | `3` | Số bài share tối đa mỗi tuần |

## Các lệnh bot

### DM (tin nhắn riêng)

| Lệnh | Chức năng |
|------|-----------|
| `/start` | Chào mừng + menu chính |
| `/dangki` | Đăng ký tên team |
| `/checkin` | Nộp check-in hàng tuần (kèm ảnh NotebookLM) |
| `/share` | Gửi bài chia sẻ workflow AI |
| `/help` | Hướng dẫn sử dụng |
| `/cancel` | Huỷ thao tác đang thực hiện |

### Group

| Lệnh | Chức năng |
|------|-----------|
| `/leaderboard` | Xem bảng xếp hạng (tự xoá sau 10 giây) |

## Định dạng check-in

Gửi **ảnh chụp NotebookLM** kèm caption:

```
#post #week_1
Checkin 12/03/2026
10 người họp
Thiếu: 1 người
3/5 vấn đề tuần trước đã giải quyết
2 vấn đề mới phát sinh
Tổng tồn: 4 vấn đề
```

## Định dạng share

Gửi bài mô tả cách team ứng dụng AI, tối thiểu 30 ký tự:

```
#share #week_1
Vấn đề: Viết unit test cho module thanh toán tốn 2 ngày.
Giải pháp: Dùng ChatGPT với prompt "Viết unit test cho hàm X, cover edge case Y".
Kết quả: Coverage 40% → 85%, phát hiện 3 bug, tiết kiệm 1.5 ngày.
```

**Lưu ý:** Mỗi bài phải là một vấn đề / giải pháp AI khác nhau. Bot sẽ từ chối nếu trùng chủ đề với bài đã nộp trong tuần.

## Hệ thống tính điểm

| Loại | Điểm | Ghi chú |
|------|------|---------|
| Check-in | 10đ/tuần | Tối đa 100đ (10 tuần) |
| Sharing | 0–100đ/bài | Chỉ lấy điểm **cao nhất** của team |
| **Tổng** | **Tối đa 200đ** | Check-in + Sharing |

Bài sharing chấm theo 3 tiêu chí:
- **Tính mới** (0–33đ) — ý tưởng độc đáo, chưa phổ biến
- **Tính thực tế** (0–33đ) — có số liệu trước/sau, đã áp dụng thật
- **Độ rõ workflow** (0–34đ) — mô tả rõ input → tool → output

## Google Sheets

Tạo spreadsheet với 4 tab:

| Tab | Headers |
|-----|---------|
| `Teams` | `team_id`, `team_name`, `telegram_user_id`, `username`, `registered_at` |
| `Checkins` | `id`, `team_id`, `team_name`, `week`, `submitted_at`, `rank`, `points`, `summary_text`, `has_screenshot`, `validated`, `member_count` |
| `Shares` | `id`, `team_id`, `team_name`, `week`, `submitted_at`, `content`, `score`, `scored_at`, `feedback` |
| `Leaderboard` | `team_id`, `team_name`, `checkin_points`, `sharing_points`, `total_points`, `last_updated` |

Tạo Service Account trên Google Cloud → share spreadsheet cho email service account (Editor) → đặt file JSON vào `credentials.json`.

## Chế độ test local

Khi không có Google Sheets credentials hoặc OpenAI API key:
- Dữ liệu lưu vào `local_data.json` (tự tạo)
- Chấm điểm bằng heuristic
- Mọi tính năng hoạt động bình thường
