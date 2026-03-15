# Hướng dẫn test Bot Thử Thách AI Meeting

Tất cả test đều chạy ở chế độ local (không cần Google Sheets, không cần Anthropic API key thật).

## Chuẩn bị

```bash
cd telegram-challenge-bot
source .venv/bin/activate

# Đảm bảo .env có TELEGRAM_BOT_TOKEN
# Các biến khác để trống → bot tự dùng fallback
python bot.py
```

---

## Test 1: Đăng ký team (`/start`)

### 1a. Đăng ký lần đầu

**Input** (DM bot):
```
/start Backend Team
```

**Expected output:**
```
✅ Đã đăng ký team: Backend Team (team_1)

Dùng /checkin và /share trong DM với bot để nộp bài nhé!
```

**Kiểm tra** `local_data.json`:
```json
"Teams": [{"team_id": "team_1", "team_name": "Backend Team", ...}]
```

### 1b. Đăng ký trùng user (idempotent)

**Input:** `/start Tên Khác` (cùng user đã đăng ký)

**Expected:** Trả về thông tin team cũ (không tạo team mới)

### 1c. Thiếu tên team

**Input:** `/start`

**Expected:** Hiển thị hướng dẫn và danh sách lệnh.

---

## Test 2: Check-in (`/checkin`)

### 2a. Check-in hợp lệ (ảnh + caption đúng format)

**Input** (DM bot, gửi ảnh bất kỳ với caption):
```
/checkin #post #team_backend #week_1
Checkin 15/03/2026
10 người họp
Thiếu: 1 người
3/5 vấn đề tuần trước đã giải quyết
2 vấn đề mới phát sinh
Tổng tồn: 4 vấn đề
```

**Expected output:**
```
✅ Check-in thành công!

Tuần: 1
Thứ hạng tuần này: #1
Điểm nhận: +10

Hashtag và số liệu hợp lệ.
```

**Kiểm tra** `local_data.json`:
- `Checkins` có 1 entry mới với `week: 1`, `points: 10`, `validated: "TRUE"`
- `Leaderboard` được cập nhật

### 2b. Check-in không có ảnh

**Input** (text thuần, không ảnh):
```
/checkin #post #team_backend #week_2
Checkin 15/03/2026
10 người họp...
```

**Expected:**
```
❌ Check-in bắt buộc phải có ảnh chụp NotebookLM mới nhất.
```

### 2c. Check-in thiếu hashtag `#week_`

**Input** (ảnh + caption):
```
/checkin #post #team_backend
10 người họp, 2 vấn đề phát sinh
```

**Expected:**
```
❌ Thiếu hashtag #week_<so> (ví dụ: #week_1).
```

### 2d. Check-in thiếu hashtag `#team_`

**Input** (ảnh + caption):
```
/checkin #post #week_1
10 người họp
```

**Expected:**
```
❌ Thiếu hashtag #team_<ten_team>.
```

### 2e. Check-in trùng tuần

**Input:** Gửi lại check-in tuần 1 (sau khi đã check-in thành công ở 2a).

**Expected:**
```
⚠️ Team Backend Team đã check-in cho tuần 1 rồi.
```

### 2f. Dùng `/checkin` trong group (không phải DM)

**Expected:**
```
Vui lòng dùng /checkin trong tin nhắn riêng với bot nhé! 🤫
```

### 2g. Check-in khi chưa đăng ký team

**Input** (tài khoản chưa `/start`): gửi check-in bất kỳ

**Expected:**
```
Bạn chưa đăng ký team. Dùng /start TênTeam trước nhé.
```

---

## Test 3: Chia sẻ AI (`/share`)

### 3a. Share hợp lệ

**Input** (DM bot):
```
/share Tuần này tôi dùng Claude để tóm tắt biên bản họp từ Zoom.
Workflow: 1) Export transcript 2) Paste vào Claude 3) Prompt "Tóm tắt 5 ý chính"
Team tiết kiệm 30 phút mỗi tuần. #week_1
```

**Expected output:**
```
🎯 Điểm chia sẻ: XX/100

💡 Tính mới: XX/33
🔧 Tính thực tế: XX/33
📋 Độ rõ workflow: XX/34

Nhận xét: Test mode scoring: bài có ý rõ và có thể áp dụng...
```

**Kiểm tra** `local_data.json`:
- `Shares` có 1 entry với `score > 0`
- `Leaderboard` được cập nhật với `sharing_points`

### 3b. Share quá ngắn

**Input:**
```
/share AI tốt.
```

**Expected:**
```
📝 Gửi /share kèm nội dung bài chia sẻ đầy đủ (ít nhất 30 ký tự).
```

### 3c. Share không đăng ký team

Tương tự check-in: nhắc đăng ký team trước.

---

## Test 4: Leaderboard (`/leaderboard`)

### 4a. Sau khi có data

**Input:** `/leaderboard` (sau khi đã check-in và share)

**Expected output:**
```
🏆 AI Meeting Challenge — Bảng xếp hạng

🥇 Backend Team — 10 điểm (check-in 10 + sharing X)

Check-in: tối đa 100 điểm / 10 tuần | Sharing: chỉ lấy bài cao nhất mỗi team
```

### 4b. Chưa có data

**Input:** `/leaderboard` (xoá `local_data.json` trước)

**Expected:**
```
Chưa có team nào đăng ký.
```

---

## Test 5: Reset data

```bash
# Xoá data để test lại từ đầu
rm local_data.json
```

---

## Checklist nhanh

- [ ] `/start TênTeam` → đăng ký OK
- [ ] `/checkin` (ảnh + caption đúng) → check-in OK, điểm +10
- [ ] `/checkin` (không ảnh) → từ chối đúng
- [ ] `/checkin` trùng tuần → cảnh báo đúng
- [ ] `/share` (>30 ký tự) → điểm > 0
- [ ] `/share` (quá ngắn) → từ chối đúng
- [ ] `/leaderboard` → hiển thị đúng điểm
- [ ] `local_data.json` được tạo và cập nhật đúng
