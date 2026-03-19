"""
bot.py - Bot Telegram chính cho thử thách AI Meeting.

Luồng hoạt động:
- /start      → Chào mừng + hiện menu buttons
- /help       → Hướng dẫn chi tiết
- /dangki     → Đăng ký tên team (ConversationHandler)
- /checkin    → Nộp check-in hàng tuần (DM)
- /share      → Chia sẻ bài viết AI (DM)
- /leaderboard → Xem bảng xếp hạng
"""

import asyncio
import logging
import re
from datetime import time, timezone, timedelta

from telegram import (
    BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats,
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
)
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import sheets
import scoring
import storage
import leaderboard as lb

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
ICT = timezone(timedelta(hours=7))

# ConversationHandler states — dangki
WAITING_TEAM_NAME = 0
# ConversationHandler states — checkin
WAITING_CHECKIN_PHOTO = 10
WAITING_CHECKIN_CONTENT = 11
# ConversationHandler states — share
WAITING_SHARE_CONTENT = 20


# ── Helpers ──────────────────────────────────────────────────────────────

def _is_dm(update: Update) -> bool:
    return update.effective_chat.type == ChatType.PRIVATE


def _username(update: Update) -> str:
    user = update.effective_user
    return user.username or user.full_name or str(user.id)


def _extract_week(text: str) -> int | None:
    m = re.search(r"#week_(\d+)", text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_member_count(text: str) -> int | None:
    """Trích số người tham dự từ text.
    Ưu tiên pattern 'X/Y người' (trích X), sau đó 'X người'.
    """
    m = re.search(r"(\d+)\s*/\s*\d+\s*(?:người|thành viên|members?)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*(?:người|thành viên|members?|người họp|người tham)", text, re.IGNORECASE)
    return int(m.group(1)) if m else None




def _main_menu_keyboard(registered: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if not registered:
        rows.append([InlineKeyboardButton("📝 Đăng ký team", callback_data="menu_dangki")])
    rows.extend([
        [InlineKeyboardButton("📋 Check-in tuần", callback_data="menu_checkin")],
        [InlineKeyboardButton("💡 Chia sẻ bài AI", callback_data="menu_share")],
        [InlineKeyboardButton("❓ Trợ giúp", callback_data="menu_help")],
    ])
    return InlineKeyboardMarkup(rows)


async def _dm_only(update: Update, command: str) -> bool:
    if _is_dm(update):
        return True
    await update.message.reply_text(
        f"Vui lòng dùng /{command} trong tin nhắn riêng với bot nhé!"
    )
    return False


# ── /start ───────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    existing = sheets.get_team_by_user(user.id)

    registered = existing is not None
    if existing:
        text = (
            f"👋 Chào mừng trở lại, {user.first_name}!\n"
            f"🏷 Team của bạn: {existing['team_name']}\n\n"
            "Chọn chức năng bên dưới:"
        )
    else:
        text = (
            f"👋 Chào mừng {user.first_name} đến với Bot Thử Thách AI Meeting!\n\n"
            "Bạn chưa đăng ký team. Bấm \"📝 Đăng ký team\" để bắt đầu."
        )

    await update.message.reply_text(text, reply_markup=_main_menu_keyboard(registered))


# ── /help ────────────────────────────────────────────────────────────────

HELP_TEXT = (
    "📖 Hướng dẫn sử dụng bot:\n\n"
    "1️⃣ /dangki — Đăng ký tên team của bạn\n"
    "2️⃣ /checkin — Nộp check-in hàng tuần (chỉ trong DM)\n"
    "   Gửi ảnh chụp NotebookLM kèm caption:\n"
    "   #post #week_<số> + tóm tắt số liệu\n"
    "3️⃣ /share — Chia sẻ bài viết AI (chỉ trong DM)\n"
    "   Gửi /share kèm nội dung bài (tối thiểu 30 ký tự)\n"
    "4️⃣ /leaderboard — Xem bảng xếp hạng (trong group)\n\n"
    "⚠️ Lưu ý: /checkin và /share chỉ hoạt động trong DM với bot.\n"
    "🏆 Bảng xếp hạng xem trong group hoặc tự động gửi hàng tuần."
)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    registered = sheets.get_team_by_user(user.id) is not None
    await update.message.reply_text(HELP_TEXT, reply_markup=_main_menu_keyboard(registered))


# ── Callback query handler (xử lý buttons) ──────────────────────────────

async def _safe_edit(query, text: str, reply_markup=None) -> None:
    """Edit message, bỏ qua lỗi nếu nội dung không thay đổi."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    registered = sheets.get_team_by_user(user.id) is not None
    kb = _main_menu_keyboard(registered)

    data = query.data
    # menu_dangki, menu_checkin, menu_share → xử lý bởi ConversationHandler
    if data == "menu_help":
        await _safe_edit(query, HELP_TEXT, reply_markup=kb)


# ── /dangki (ConversationHandler) ────────────────────────────────────────

async def dangki_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Xử lý khi bấm button 'Đăng ký team'."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    existing = sheets.get_team_by_user(user.id)
    if existing:
        await _safe_edit(
            query,
            f"✅ Bạn đã đăng ký team: {existing['team_name']}\n"
            "Nếu muốn đổi tên, liên hệ admin.",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        return ConversationHandler.END

    await _safe_edit(query, "📝 Nhập tên team của bạn:")
    return WAITING_TEAM_NAME


async def cmd_dangki(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    existing = sheets.get_team_by_user(user.id)
    if existing:
        await update.message.reply_text(
            f"✅ Bạn đã đăng ký team: {existing['team_name']}\n"
            "Nếu muốn đổi tên, liên hệ admin.",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        return ConversationHandler.END

    await update.message.reply_text("📝 Nhập tên team của bạn:")
    return WAITING_TEAM_NAME


async def receive_team_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    team_name = update.message.text.strip()
    if len(team_name) < 2 or len(team_name) > 50:
        await update.message.reply_text("⚠️ Tên team phải từ 2-50 ký tự. Vui lòng nhập lại:")
        return WAITING_TEAM_NAME

    user = update.effective_user
    team = sheets.register_team(
        telegram_user_id=user.id,
        username=_username(update),
        team_name=team_name,
    )

    await update.message.reply_text(
        f"✅ Đã đăng ký team: {team['team_name']} ({team['team_id']})\n\n"
        "Bây giờ bạn có thể sử dụng các chức năng bên dưới:",
        reply_markup=_main_menu_keyboard(registered=True),
    )
    return ConversationHandler.END


async def cancel_dangki(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    registered = sheets.get_team_by_user(user.id) is not None
    await update.message.reply_text(
        "Đã huỷ đăng ký. Bấm /dangki để thử lại.",
        reply_markup=_main_menu_keyboard(registered),
    )
    return ConversationHandler.END


# ── /checkin (ConversationHandler – 2 bước) ─────────────────────────────

async def checkin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bấm button 'Check-in tuần' → bắt đầu flow 2 bước."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    team = sheets.get_team_by_user(user.id)
    if not team:
        await _safe_edit(
            query,
            "⚠️ Bạn chưa đăng ký team. Bấm \"📝 Đăng ký team\" trước nhé.",
            reply_markup=_main_menu_keyboard(registered=False),
        )
        return ConversationHandler.END

    context.user_data["checkin_team"] = team
    await _safe_edit(
        query,
        "📋 Check-in tuần — Bước 1/2\n\n"
        "📸 Gửi ảnh chụp màn hình NotebookLM mới nhất của bạn:",
    )
    return WAITING_CHECKIN_PHOTO


async def cmd_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Lệnh /checkin → nếu có ảnh+caption thì xử lý thẳng, không thì bắt đầu flow."""
    message = update.effective_message
    if not message:
        return ConversationHandler.END

    if not _is_dm(update):
        await message.reply_text("Vui lòng dùng /checkin trong tin nhắn riêng với bot!")
        return ConversationHandler.END

    user = update.effective_user
    team = sheets.get_team_by_user(user.id)
    if not team:
        await message.reply_text(
            "⚠️ Bạn chưa đăng ký team. Dùng /dangki trước nhé.",
            reply_markup=_main_menu_keyboard(registered=False),
        )
        return ConversationHandler.END

    context.user_data["checkin_team"] = team

    # Nếu gửi ảnh + caption đầy đủ → xử lý thẳng (shortcut)
    text = message.caption or message.text or ""
    submission = re.sub(r"^/checkin\s*", "", text, flags=re.IGNORECASE).strip()
    if bool(message.photo) and submission and _extract_week(submission):
        return await _process_checkin(update, context, submission)

    # Bắt đầu flow từng bước
    await message.reply_text(
        "📋 Check-in tuần — Bước 1/2\n\n"
        "📸 Gửi ảnh chụp màn hình NotebookLM mới nhất của bạn:",
    )
    return WAITING_CHECKIN_PHOTO


async def checkin_receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bước 1: Nhận và xác minh ảnh NotebookLM."""
    message = update.effective_message
    photo_id = message.photo[-1].file_id

    # Tải ảnh và xác minh bằng AI vision
    await message.reply_text("⏳ Đang xác minh ảnh NotebookLM...")
    tg_file = await context.bot.get_file(photo_id)
    photo_bytes = bytes(await tg_file.download_as_bytearray())
    photo_result = scoring.validate_notebooklm_photo(photo_bytes)

    if not photo_result.valid:
        await message.reply_text(
            f"❌ Ảnh không hợp lệ: {photo_result.reason}\n\n"
            "Vui lòng gửi lại ảnh chụp màn hình NotebookLM "
            "(notebooklm.google.com — giao diện Audio Overview, Notebook Guide hoặc Sources)."
        )
        return WAITING_CHECKIN_PHOTO

    context.user_data["checkin_photo_id"] = photo_id

    # Nếu ảnh kèm caption đầy đủ → xử lý thẳng
    caption = message.caption or ""
    if caption.strip() and _extract_week(caption):
        return await _process_checkin(update, context, caption)

    # Chuyển bước 2 — hướng dẫn viết nội dung
    await message.reply_text(
        "✅ Ảnh NotebookLM hợp lệ!\n\n"
        "📋 Check-in tuần — Bước 2/2\n\n"
        "Gửi nội dung check-in theo mẫu dưới đây. "
        "Điền đầy đủ và cụ thể để được tính điểm tối đa.\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📌 MẪU (copy & điền vào):\n"
        "━━━━━━━━━━━━━━━━\n"
        "#post #week_<số tuần>\n"
        "Checkin DD/MM/YYYY\n"
        "Tham dự: <số có mặt>/<tổng thành viên> người\n"
        "Vắng: <tên hoặc số người vắng, lý do nếu có>\n"
        "Giải quyết từ tuần trước: <đã xong>/<tổng tồn> vấn đề\n"
        "Vấn đề mới: <số lượng> — <mô tả ngắn từng vấn đề>\n"
        "Tổng tồn đọng: <số>\n"
        "Tóm tắt buổi họp: <nội dung chính đã thảo luận, quyết định quan trọng>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📌 VÍ DỤ:\n"
        "━━━━━━━━━━━━━━━━\n"
        "#post #week_3\n"
        "Checkin 17/03/2026\n"
        "Tham dự: 9/10 người\n"
        "Vắng: Anh Minh (bận công tác)\n"
        "Giải quyết từ tuần trước: 3/5 vấn đề\n"
        "Vấn đề mới: 2 — lỗi API thanh toán, chậm onboard user mới\n"
        "Tổng tồn đọng: 4\n"
        "Tóm tắt buổi họp: Review sprint 3, demo tính năng export báo cáo, "
        "thống nhất kế hoạch Q2 và phân công nhiệm vụ tuần tới.\n\n"
    )
    return WAITING_CHECKIN_CONTENT


async def checkin_photo_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bước 1: User gửi text thay vì ảnh."""
    await update.message.reply_text(
        "⚠️ Vui lòng gửi ảnh chụp NotebookLM (không phải text).\n"
        "Gửi /cancel để huỷ.",
    )
    return WAITING_CHECKIN_PHOTO


async def checkin_receive_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bước 2: Nhận nội dung hashtag + số liệu."""
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("⚠️ Vui lòng gửi nội dung check-in với hashtag #post #week_<số>:")
        return WAITING_CHECKIN_CONTENT
    return await _process_checkin(update, context, text)


async def _process_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE, submission: str) -> int:
    """Xử lý check-in (dùng chung cho cả flow 2 bước và shortcut)."""
    message = update.effective_message
    team = context.user_data.get("checkin_team")
    if not team:
        team = sheets.get_team_by_user(update.effective_user.id)
    if not team:
        await message.reply_text(
            "⚠️ Bạn chưa đăng ký team.",
            reply_markup=_main_menu_keyboard(registered=False),
        )
        return ConversationHandler.END

    week = _extract_week(submission)
    if week is None:
        await message.reply_text("❌ Thiếu hashtag #week_<số> (ví dụ: #week_1). Gửi lại:")
        return WAITING_CHECKIN_CONTENT

    if sheets.team_already_checked_in(team["team_id"], week):
        await message.reply_text(
            f"⚠️ Team {team['team_name']} đã check-in cho tuần {week} rồi.",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        _checkin_cleanup(context)
        return ConversationHandler.END

    await message.reply_text("⏳ Đang kiểm tra check-in của bạn...")
    result = scoring.score_checkin(submission)
    if not result.valid:
        await message.reply_text(
            f"❌ Check-in bị từ chối: {result.reason}\n\nVui lòng sửa và gửi lại.",
        )
        return WAITING_CHECKIN_CONTENT

    # Upload ảnh lên S3 (nếu đã cấu hình)
    photo_url: str | None = None
    photo_id = context.user_data.get("checkin_photo_id")
    if photo_id and config.USE_S3:
        try:
            tg_file = await context.bot.get_file(photo_id)
            photo_bytes = bytes(await tg_file.download_as_bytearray())
            photo_url = storage.upload_checkin_photo(photo_bytes, team["team_id"], week)
        except Exception as e:
            logger.error("Failed to upload photo to S3: %s", e)

    member_count = _extract_member_count(submission) or 0
    rank = sheets.count_checkins_for_week(week) + 1
    points = config.CHECKIN_POINTS

    try:
        sheets.save_checkin(
            team_id=team["team_id"],
            team_name=team["team_name"],
            week=week,
            summary_text=submission[:1000],
            has_screenshot=bool(photo_id),
            rank=rank,
            points=points,
            member_count=member_count,
            photo_url=photo_url,
        )
        sheets.compute_and_save_leaderboard()
        sheets.update_organizer_details()
    except Exception as e:
        logger.error("Failed to save checkin: %s", e)
        await message.reply_text("❌ Lỗi khi lưu check-in. Vui lòng thử lại sau.")
        _checkin_cleanup(context)
        return ConversationHandler.END

    await message.reply_text(
        f"✅ Check-in thành công!\n\n"
        f"📅 Tuần: {week}\n"
        f"🏅 Thứ hạng tuần này: #{rank}\n"
        f"💰 Điểm nhận: +{points}\n\n"
        f"{result.reason}",
        reply_markup=_main_menu_keyboard(registered=True),
    )

    if config.GROUP_CHAT_ID:
        try:
            forward_text = lb.build_checkin_forward(
                team_name=team["team_name"],
                week=week,
                rank=rank,
                points=points,
                username=_username(update),
            )
            await context.bot.send_message(chat_id=config.GROUP_CHAT_ID, text=forward_text)
        except Exception as e:
            logger.error("Failed to forward checkin to group: %s", e)

    _checkin_cleanup(context)
    return ConversationHandler.END


def _checkin_cleanup(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("checkin_team", None)
    context.user_data.pop("checkin_photo_id", None)


async def cancel_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    registered = sheets.get_team_by_user(user.id) is not None
    _checkin_cleanup(context)
    await update.message.reply_text(
        "Đã huỷ check-in.",
        reply_markup=_main_menu_keyboard(registered),
    )
    return ConversationHandler.END


# ── /share (ConversationHandler – 1 bước) ────────────────────────────────

async def share_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bấm button 'Chia sẻ bài AI' → hướng dẫn + chờ nội dung."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    team = sheets.get_team_by_user(user.id)
    if not team:
        await _safe_edit(
            query,
            "⚠️ Bạn chưa đăng ký team. Bấm \"📝 Đăng ký team\" trước nhé.",
            reply_markup=_main_menu_keyboard(registered=False),
        )
        return ConversationHandler.END

    context.user_data["share_team"] = team
    prev_best = sheets.get_best_share_score(team["team_id"])
    week_count = sheets.count_shares_this_week(team["team_id"])
    remaining = max(0, config.MAX_SHARES_PER_WEEK - week_count)

    urgency = ""
    if prev_best == 0:
        urgency = "🚀 Team chưa có bài nào — nộp ngay để không bị bỏ lại!\n\n"
    elif prev_best < 60:
        urgency = f"⚡ Bài tốt nhất của team: {prev_best}/100 — còn {remaining} slot tuần này. Thử một vấn đề AI khác để nâng điểm!\n\n"
    else:
        urgency = f"✨ Bài tốt nhất: {prev_best}/100. Còn {remaining} slot tuần này — chia sẻ thêm vấn đề AI khác!\n\n"

    await _safe_edit(
        query,
        "💡 Chia sẻ bài AI\n\n"
        + urgency +
        "Viết bài chia sẻ cách team ứng dụng AI vào công việc thực tế.\n"
        "Kèm hashtag #share #week_<số>\n\n"
        f"⚠️ Tối đa {config.MAX_SHARES_PER_WEEK} bài/tuần, mỗi bài phải là vấn đề AI khác nhau.\n"
        "Điểm cao nhất trong tuần được tính vào BXH.\n\n"
        "🤖 AI chấm theo 3 tiêu chí:\n"
        "• Tính mới (33đ) — cách dùng AI độc đáo, có twist riêng\n"
        "• Tính thực tế (33đ) — có số liệu trước/sau, đã áp dụng thật\n"
        "• Độ rõ workflow (34đ) — mô tả rõ input → tool → output\n\n"
        "📌 Ví dụ:\n"
        "#share #week_1\n"
        "Vấn đề: Viết test cho module thanh toán tốn 2 ngày.\n"
        "Giải pháp: Dùng ChatGPT + prompt \"Viết unit test cho hàm X, cover edge case Y\".\n"
        "Kết quả: Coverage 40% → 85%, phát hiện 3 bug, tiết kiệm 1.5 ngày.",
    )
    return WAITING_SHARE_CONTENT


async def cmd_share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Lệnh /share → nếu có nội dung thì xử lý thẳng, không thì chờ."""
    message = update.effective_message
    if not message:
        return ConversationHandler.END

    if not _is_dm(update):
        await message.reply_text("Vui lòng dùng /share trong tin nhắn riêng với bot!")
        return ConversationHandler.END

    user = update.effective_user
    team = sheets.get_team_by_user(user.id)
    if not team:
        await message.reply_text(
            "⚠️ Bạn chưa đăng ký team. Dùng /dangki trước nhé.",
            reply_markup=_main_menu_keyboard(registered=False),
        )
        return ConversationHandler.END

    context.user_data["share_team"] = team

    text = message.text or ""
    submission = re.sub(r"^/share\s*", "", text, flags=re.IGNORECASE).strip()

    if submission and len(submission) >= 30:
        return await _process_share(update, context, submission)

    # Chờ nội dung
    prev_best = sheets.get_best_share_score(team["team_id"])
    week_count = sheets.count_shares_this_week(team["team_id"])
    remaining = max(0, config.MAX_SHARES_PER_WEEK - week_count)

    if prev_best == 0:
        hint = f"🚀 Team chưa có bài nào! Nộp ngay để ghi điểm. Còn {remaining} slot tuần này.\n"
    elif prev_best < 60:
        hint = f"⚡ Bài tốt nhất: {prev_best}/100 — thử vấn đề AI khác để nâng điểm! Còn {remaining} slot.\n"
    else:
        hint = f"✨ Bài tốt nhất: {prev_best}/100. Còn {remaining} slot tuần này.\n"

    await message.reply_text(
        "💡 Gửi bài chia sẻ AI kèm hashtag #share #week_<số> (tối thiểu 30 ký tự):\n\n"
        + hint
        + f"⚠️ Mỗi bài phải là vấn đề AI khác nhau (tối đa {config.MAX_SHARES_PER_WEEK} bài/tuần).",
    )
    return WAITING_SHARE_CONTENT


async def share_receive_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Nhận nội dung bài chia sẻ."""
    text = (update.message.text or "").strip()
    if not text or len(text) < 30:
        await update.message.reply_text(
            "⚠️ Nội dung quá ngắn (tối thiểu 30 ký tự). Gửi lại:\n"
            "Gửi /cancel để huỷ.",
        )
        return WAITING_SHARE_CONTENT
    return await _process_share(update, context, text)


async def _process_share(update: Update, context: ContextTypes.DEFAULT_TYPE, submission: str) -> int:
    """Xử lý bài chia sẻ (dùng chung cho cả flow button và /share)."""
    message = update.effective_message
    team = context.user_data.get("share_team")
    if not team:
        team = sheets.get_team_by_user(update.effective_user.id)
    if not team:
        await message.reply_text(
            "⚠️ Bạn chưa đăng ký team.",
            reply_markup=_main_menu_keyboard(registered=False),
        )
        return ConversationHandler.END

    week = _extract_week(submission) or 0

    # Kiểm tra giới hạn và trùng chủ đề
    this_week_shares = sheets.get_shares_this_week(team["team_id"])
    week_count = len(this_week_shares)

    if week_count >= config.MAX_SHARES_PER_WEEK:
        await message.reply_text(
            f"⚠️ Tuần này team đã nộp {week_count} bài (tối đa {config.MAX_SHARES_PER_WEEK} chủ đề AI khác nhau/tuần).\n"
            "Hãy quay lại tuần sau nhé!",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        context.user_data.pop("share_team", None)
        return ConversationHandler.END

    if this_week_shares:
        await message.reply_text("🔍 Đang kiểm tra chủ đề...")
        prev_contents = [r.get("content", "") for r in this_week_shares]
        is_dup, dup_reason = scoring.is_duplicate_topic(submission, prev_contents)
        if is_dup:
            await message.reply_text(
                f"⚠️ Bài này có vẻ trùng chủ đề AI với bài đã nộp tuần này.\n"
                f"💬 {dup_reason}\n\n"
                f"Mỗi bài phải là một vấn đề / giải pháp AI khác nhau. "
                f"Còn {config.MAX_SHARES_PER_WEEK - week_count} slot trong tuần này.",
            )
            context.user_data.pop("share_team", None)
            return ConversationHandler.END

    prev_best = sheets.get_best_share_score(team["team_id"])

    await message.reply_text("🤖 Đang dùng AI để chấm bài của bạn...")
    try:
        result = scoring.score_sharing(submission)
        sheets.save_share(
            team_id=team["team_id"],
            team_name=team["team_name"],
            week=week,
            content=submission[:2000],
            score=result.score,
            feedback=result.feedback,
        )
        sheets.compute_and_save_leaderboard()
    except Exception as e:
        logger.error("Scoring/save failed: %s", e)
        await message.reply_text("❌ Chấm điểm hoặc lưu thất bại. Vui lòng thử lại sau.")
        context.user_data.pop("share_team", None)
        return ConversationHandler.END

    is_new_best = result.score > prev_best
    result_text = (
        f"🎯 Điểm chia sẻ: {result.score}/100\n\n"
        f"💡 Tính mới: {result.novelty}/33\n"
        f"🔧 Tính thực tế: {result.practicality}/33\n"
        f"📋 Độ rõ workflow: {result.workflow_clarity}/34\n\n"
        f"📝 Nhận xét: {result.feedback}"
    )
    if is_new_best:
        result_text += "\n\n🏆 Đây là điểm cao nhất của team bạn!"

    await message.reply_text(result_text, reply_markup=_main_menu_keyboard(registered=True))

    if config.GROUP_CHAT_ID:
        try:
            forward_text = lb.build_share_forward(
                team_name=team["team_name"],
                week=week,
                score=result.score,
                highlight=result.highlight,
                feedback=result.feedback,
                username=_username(update),
                is_new_best=is_new_best,
            )
            await context.bot.send_message(chat_id=config.GROUP_CHAT_ID, text=forward_text)
        except Exception as e:
            logger.error("Failed to forward share to group: %s", e)

    context.user_data.pop("share_team", None)
    return ConversationHandler.END


async def cancel_share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    registered = sheets.get_team_by_user(user.id) is not None
    context.user_data.pop("share_team", None)
    await update.message.reply_text(
        "Đã huỷ chia sẻ.",
        reply_markup=_main_menu_keyboard(registered),
    )
    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Huỷ mọi flow đang chạy (dangki / checkin / share)."""
    user = update.effective_user
    registered = sheets.get_team_by_user(user.id) is not None
    _checkin_cleanup(context)
    context.user_data.pop("share_team", None)
    await update.message.reply_text(
        "Đã huỷ.",
        reply_markup=_main_menu_keyboard(registered),
    )
    return ConversationHandler.END


# ── /leaderboard (group only, auto-delete) ──────────────────────────────

async def _delete_after(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: xoá message sau delay."""
    job = context.job
    try:
        await context.bot.delete_message(
            chat_id=job.data["chat_id"],
            message_id=job.data["message_id"],
        )
    except Exception:
        pass  # message có thể đã bị xoá


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xem BXH — chỉ hoạt động trong group, tự xoá sau 10 giây."""
    if _is_dm(update):
        await update.message.reply_text(
            "🏆 Bảng xếp hạng chỉ xem được trong group chat.\n"
            "Gõ /leaderboard trong group nhé!",
        )
        return

    try:
        standings = sheets.compute_and_save_leaderboard()
        text = lb.format_leaderboard(standings)
    except Exception as e:
        logger.error("Leaderboard error: %s", e)
        text = "❌ Không tải được leaderboard lúc này."

    sent = await update.message.reply_text(text)

    # Xoá cả lệnh user và reply của bot sau 10 giây
    context.job_queue.run_once(
        _delete_after, 10,
        data={"chat_id": sent.chat_id, "message_id": sent.message_id},
    )
    context.job_queue.run_once(
        _delete_after, 10,
        data={"chat_id": update.message.chat_id, "message_id": update.message.message_id},
    )


# ── Auto gửi BXH hàng tuần vào group ───────────────────────────────────

async def weekly_leaderboard_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job chạy hàng tuần: gửi BXH vào group."""
    if not config.GROUP_CHAT_ID:
        return
    try:
        standings = sheets.compute_and_save_leaderboard()
        text = "📊 Bảng xếp hạng tuần này:\n\n" + lb.format_leaderboard(standings)
        await context.bot.send_message(chat_id=config.GROUP_CHAT_ID, text=text)
    except Exception as e:
        logger.error("Weekly leaderboard job error: %s", e)


# ── Setup commands menu ──────────────────────────────────────────────────

async def post_init(application: Application) -> None:
    """Validate kết nối + set command menu khi bot khởi động."""
    bot = application.bot

    # Validate bot token
    me = await bot.get_me()
    logger.info("Bot initialized: @%s", me.username)

    # Validate Google Sheets nếu đang dùng
    if not config.USE_LOCAL_STORAGE:
        try:
            sheets._get_sheet(config.SHEET_TEAMS)
            logger.info("Google Sheets connection OK")
        except Exception as e:
            logger.error("Google Sheets connection FAILED: %s", e)
            raise

    # Commands cho DM
    await bot.set_my_commands(
        commands=[
            BotCommand("start", "Bắt đầu bot"),
            BotCommand("dangki", "Đăng ký tên team"),
            BotCommand("checkin", "Check-in tuần"),
            BotCommand("share", "Chia sẻ bài AI"),
            BotCommand("help", "Hướng dẫn sử dụng"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )

    # Commands cho Group
    await bot.set_my_commands(
        commands=[
            BotCommand("leaderboard", "Xem bảng xếp hạng"),
        ],
        scope=BotCommandScopeAllGroupChats(),
    )

    # Default commands (fallback)
    await bot.set_my_commands(
        commands=[
            BotCommand("start", "Bắt đầu bot"),
            BotCommand("leaderboard", "Xem bảng xếp hạng"),
            BotCommand("help", "Hướng dẫn sử dụng"),
        ],
    )

    logger.info("Đã set command menu cho DM và Group.")


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    sheets.ensure_schema()
    storage.check_connection()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # ConversationHandler duy nhất — gộp dangki + checkin + share
    # Cho phép chuyển flow tự do (bấm button khác → tự cancel flow cũ)
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(dangki_button_handler, pattern="^menu_dangki$"),
            CallbackQueryHandler(checkin_button_handler, pattern="^menu_checkin$"),
            CallbackQueryHandler(share_button_handler, pattern="^menu_share$"),
            CommandHandler("dangki", cmd_dangki),
            CommandHandler("checkin", cmd_checkin),
            CommandHandler("share", cmd_share),
            MessageHandler(
                filters.PHOTO & filters.CaptionRegex(r"(?i)^/checkin"),
                cmd_checkin,
            ),
        ],
        states={
            WAITING_TEAM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_team_name),
            ],
            WAITING_CHECKIN_PHOTO: [
                MessageHandler(filters.PHOTO, checkin_receive_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, checkin_photo_fallback),
            ],
            WAITING_CHECKIN_CONTENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, checkin_receive_content),
            ],
            WAITING_SHARE_CONTENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, share_receive_content),
            ],
        },
        fallbacks=[
            # Cho phép chuyển flow bằng button/command khi đang ở flow khác
            CallbackQueryHandler(dangki_button_handler, pattern="^menu_dangki$"),
            CallbackQueryHandler(checkin_button_handler, pattern="^menu_checkin$"),
            CallbackQueryHandler(share_button_handler, pattern="^menu_share$"),
            CommandHandler("dangki", cmd_dangki),
            CommandHandler("checkin", cmd_checkin),
            CommandHandler("share", cmd_share),
            CommandHandler("cancel", cancel_conversation),
        ],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(conv)
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Auto gửi BXH vào group mỗi thứ 2 lúc 9:00 sáng (ICT = UTC+7 → 2:00 UTC)
    if config.GROUP_CHAT_ID:
        app.job_queue.run_daily(
            weekly_leaderboard_job,
            time=time(hour=2, minute=0, tzinfo=timezone.utc),  # 9:00 ICT
            days=(0,),  # Thứ 2 (Monday=0)
        )
        logger.info("Đã lên lịch gửi BXH hàng tuần vào group.")

    logger.info("Bot đang khởi động...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
