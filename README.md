# Bot Thử Thách AI Meeting

Bot Telegram để quản lý thử thách AI Meeting: check-in hàng tuần, chia sẻ bài viết AI, bảng xếp hạng tự động.

## Tính năng

- **Check-in hàng tuần**: Team nộp ảnh NotebookLM + tóm tắt buổi họp qua DM
- **Chia sẻ AI**: Team gửi bài viết về workflow AI, bot chấm điểm bằng Claude
- **Bảng xếp hạng**: Tự động cập nhật sau mỗi lần nộp bài
- **Lưu dữ liệu**: Google Sheets (production) hoặc JSON local (test)

## Cài đặt

### Yêu cầu

- Python 3.11+
- Telegram Bot Token (từ [@BotFather](https://t.me/BotFather))
- (Tuỳ chọn) Anthropic API Key để chấm điểm AI thật
- (Tuỳ chọn) Google Sheets credentials để lưu dữ liệu production

### Cài đặt nhanh

```bash
cd telegram-challenge-bot

# Tạo virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Cài thư viện
pip install -r requirements.txt

# Cấu hình
cp .env.example .env
# Chỉnh sửa .env với các giá trị thật
```

### Biến môi trường

| Biến | Bắt buộc | Mô tả |
|------|----------|-------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Token từ BotFather |
| `GROUP_CHAT_ID` | ❌ | Chat ID group Telegram để forward kết quả |
| `ANTHROPIC_API_KEY` | ❌ | API key Anthropic (bỏ trống → dùng heuristic) |
| `ANTHROPIC_MODEL` | ❌ | Model Claude (mặc định: `claude-sonnet-4-6`) |
| `SPREADSHEET_ID` | ❌ | ID Google Sheets (bỏ trống → lưu local JSON) |
| `GOOGLE_SHEETS_CREDENTIALS_FILE` | ❌ | Đường dẫn file credentials (mặc định: `credentials.json`) |
| `TOTAL_WEEKS` | ❌ | Tổng số tuần thử thách (mặc định: 10) |
| `CHECKIN_POINTS` | ❌ | Điểm mỗi lần check-in (mặc định: 10) |

## Chạy bot

```bash
source .venv/bin/activate
python bot.py
```

**Chạy nền (production):**
```bash
nohup python bot.py > bot.log 2>&1 &
```

## Các lệnh bot

| Lệnh | Nơi dùng | Chức năng |
|------|----------|-----------|
| `/start TênTeam` | DM hoặc group | Đăng ký team |
| `/checkin` | DM (kèm ảnh + caption) | Nộp check-in hàng tuần |
| `/share <nội dung>` | DM | Gửi bài chia sẻ AI để chấm điểm |
| `/leaderboard` | Mọi nơi | Xem bảng xếp hạng hiện tại |

## Định dạng check-in

Gửi ảnh chụp NotebookLM và đặt caption theo mẫu:

```
/checkin #post #team_tên_team #week_số
Checkin DD/MM/YYYY
X người họp
Thiếu: Y người
A/B vấn đề tuần trước đã giải quyết
C vấn đề mới phát sinh
Tổng tồn: D vấn đề
```

**Ví dụ:**
```
/checkin #post #team_backend #week_1
Checkin 12/03/2026
10 người họp
Thiếu: 1 người
3/5 vấn đề tuần trước đã giải quyết
2 vấn đề mới phát sinh
Tổng tồn: 4 vấn đề
```

## Định dạng chia sẻ AI

```
/share Tuần này tôi dùng Claude để tự động tóm tắt biên bản họp.
Workflow: 1) Xuất transcript Zoom... #week_1
```

Nội dung tối thiểu 30 ký tự. Bot sẽ chấm theo 3 tiêu chí:
- **Tính mới** (0–33): Ý tưởng độc đáo, chưa phổ biến
- **Tính thực tế** (0–33): Áp dụng được ngay
- **Độ rõ workflow** (0–34): Có bước cụ thể, dễ làm theo

## Hệ thống tính điểm

- **Check-in**: 10 điểm/tuần, ai nộp trước được điểm trước. Tối đa 100 điểm.
- **Sharing**: 0–100 điểm/bài, **chỉ lấy điểm cao nhất** của mỗi team.
- **Tổng điểm** = điểm check-in + điểm sharing cao nhất.

## Google Sheets (production)

Xem hướng dẫn chi tiết trong [SETUP.md](SETUP.md).

Cần tạo spreadsheet với 4 tab: `Teams`, `Checkins`, `Shares`, `Leaderboard`.

## Chế độ test local

Khi chưa có Google Sheets credentials hoặc Anthropic API key:
- Dữ liệu lưu vào `local_data.json` (tự động tạo)
- Chấm điểm bằng heuristic (không cần API)
- Tất cả tính năng hoạt động bình thường, chỉ thiếu AI thật

Xem [TEST_GUIDE.md](TEST_GUIDE.md) để biết các test case cụ thể.
