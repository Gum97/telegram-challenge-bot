"""
bot.py - Bot Telegram chính cho thử thách AI Meeting.

Luồng hoạt động:
- /start      → Chào mừng + hiện menu buttons
- /help       → Hướng dẫn chi tiết
- /dangki     → Đăng ký tên team (ConversationHandler)
- /checkin    → Nộp check-in hàng tuần (DM)
- /share      → Nộp bài dự thi (DM)
- /leaderboard → Xem bảng xếp hạng
"""

import asyncio
import logging
import re
from datetime import datetime, date, time, timezone, timedelta

from telegram import (
    BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeChat,
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

# ConversationHandler states — dangki (multi-step)
WAITING_USER_NAME = 0
WAITING_TEAM_NAME = 1
WAITING_MEETING_FREQ = 2
WAITING_MEMBER_COUNT = 3
WAITING_MEMBER_LIST = 4
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
    m = re.search(r"#?week[_\s]*(\d+)", text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _current_week() -> int | None:
    """Tính tuần hiện tại dựa trên CHALLENGE_START_DATE (ICT).
    Ưu tiên: .env → prompts.json (admin set) → None.
    Trả về None nếu chưa cấu hình hoặc chưa đến ngày bắt đầu.
    Trả về số tuần (1-based) kể từ ngày bắt đầu.
    """
    start_str = scoring.get_prompt("start_date") or config.CHALLENGE_START_DATE
    if not start_str:
        return None
    try:
        start = date.fromisoformat(start_str)
        today = datetime.now(ICT).date()
        delta = (today - start).days
        if delta < 0:
            return None  # Chưa bắt đầu
        return delta // 7 + 1
    except (ValueError, TypeError):
        return None


def _extract_member_count(text: str) -> int | None:
    """Trích số người tham dự từ text.
    Hỗ trợ nhiều format: 'X/Y người', 'X người', 'Tham dự: X', 'X tham dự', v.v.
    """
    # Pattern 1: X/Y người (trích X)
    m = re.search(r"(\d+)\s*/\s*\d+\s*(?:người|thành viên|members?)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Pattern 2: keyword trước, số sau — "Tham dự: 7", "Số người tham dự: 11"
    m = re.search(r"(?:tham dự|tham gia|participants?|attended|số người tham)[:\s]+(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Pattern 3: số trước, keyword sau — "11 người", "10 tham dự"
    m = re.search(r"(\d+)\s*(?:người|thành viên|members?|người họp|người tham|tham dự|tham gia)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))




def _main_menu_keyboard(registered: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if not registered:
        rows.append([InlineKeyboardButton("📝 Đăng ký team", callback_data="menu_dangki")])
    rows.extend([
        [InlineKeyboardButton("📋 Check-in tuần", callback_data="menu_checkin")],
        [InlineKeyboardButton("💡 Nộp bài dự thi", callback_data="menu_share")],
        [InlineKeyboardButton("🏆 Bảng xếp hạng", callback_data="menu_leaderboard")],
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
    guide_link = '<a href="https://docs.google.com/document/d/1yC_0CVwUNiTwhc5LDIpODxocB0CPjyopqrdhzd3YYv0/edit?tab=t.0">hướng dẫn NotebookLM</a>'
    if existing:
        text = (
            f"👋 Chào mừng trở lại, {user.first_name}!\n"
            f"🏷 Team của bạn: {existing['team_name']}\n\n"
            f"📖 Xem {guide_link} để biết cách tổng hợp cuộc họp.\n\n"
            "Chọn chức năng bên dưới:"
        )
    else:
        text = (
            f"👋 Chào mừng {user.first_name} đến với Bot Thử Thách AI Meeting!\n\n"
            f"📖 Xem {guide_link} để biết cách tổng hợp cuộc họp.\n\n"
            "Bạn chưa đăng ký team. Bấm \"📝 Đăng ký team\" để bắt đầu."
        )

    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=_main_menu_keyboard(registered))


# ── Chào mừng thành viên mới join group ──────────────────────────────────

async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gửi tin chào mừng khi có người mới join group (vào General, không vào topic)."""
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        mention = f"@{member.username}" if member.username else member.first_name
        bot_me = await context.bot.get_me()
        bot_link = f"@{bot_me.username}" if bot_me.username else "bot"
        await update.message.reply_text("🎉")
        guide_link = '<a href="https://docs.google.com/document/d/1yC_0CVwUNiTwhc5LDIpODxocB0CPjyopqrdhzd3YYv0/edit?tab=t.0">hướng dẫn NotebookLM</a>'
        await update.message.reply_text(
            f"🎊 Chào mừng <b>{mention}</b> đến với nhóm <b>Thử Thách AI Meeting</b>! 🚀\n\n"
            f"📖 Xem {guide_link} để biết cách tổng hợp cuộc họp.\n\n"
            f"👉 Nhắn riêng cho {bot_link} để bắt đầu nhé! 💬",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


# ── /help ────────────────────────────────────────────────────────────────

HELP_TEXT = (
    "📖 Hướng dẫn sử dụng bot:\n\n"
    "1️⃣ /dangki — Đăng ký team (tên, thành viên, lịch họp)\n"
    "2️⃣ /checkin — Check-in tuần (20đ/tuần, tối đa 6 tuần = 120đ)\n"
    "   Gửi ảnh NotebookLM + kết quả prompt tóm tắt cuộc họp\n"
    "3️⃣ /share — Nộp bài dự thi (tối đa 80đ, tính lần cao nhất)\n"
    "   3 nhóm: Quy trình họp AI > Quy trình AI > Tin tức AI\n"
    "4️⃣ /leaderboard — Xem bảng xếp hạng (trong group)\n\n"
    "⚠️ Lưu ý: /dangki, /checkin và /share chỉ dùng được trong DM với bot.\n"
    "🏆 Top 10 bài dự thi cao nhất được Hội đồng AI chấm trực tiếp."
)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    registered = sheets.get_team_by_user(user.id) is not None
    await update.message.reply_text(HELP_TEXT, reply_markup=_main_menu_keyboard(registered))


# ── Callback query handler (xử lý buttons) ──────────────────────────────

async def _safe_edit(query, text: str, reply_markup=None, parse_mode=None, disable_web_page_preview=False) -> None:
    """Gửi tin nhắn mới thay vì edit tin cũ — giữ lại lịch sử chat."""
    await query.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
    )


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
    elif data == "menu_leaderboard":
        try:
            standings = sheets.compute_and_save_leaderboard()
            text = lb.format_leaderboard(standings)
        except Exception as e:
            logger.error("Leaderboard error: %s", e)
            text = "❌ Không tải được leaderboard lúc này."
        await _safe_edit(query, text, reply_markup=kb, parse_mode="HTML")


# ── /dangki (ConversationHandler) ────────────────────────────────────────

async def dangki_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Xử lý khi bấm button 'Đăng ký team'."""
    query = update.callback_query
    await query.answer()

    if update.effective_chat.type != ChatType.PRIVATE:
        await _safe_edit(query, "Vui lòng nhắn riêng cho bot để đăng ký team nhé!")
        return ConversationHandler.END

    # Khoá đăng ký sau deadline (hết hạn sau 13/04/2026)
    registration_deadline = date(2026, 4, 13)
    today = datetime.now(ICT).date()
    if today > registration_deadline:
        await _safe_edit(
            query,
            "⛔ Đã hết hạn đăng ký team!\n\n"
            "Thời gian đăng ký đã kết thúc vào ngày 13/04/2026.\n"
            "Nếu cần hỗ trợ, vui lòng liên hệ admin.",
            reply_markup=_main_menu_keyboard(registered=False),
        )
        return ConversationHandler.END

    user = update.effective_user
    existing = sheets.get_team_by_user(user.id)
    if existing:
        await _safe_edit(
            query,
            f"✅ Bạn đã đăng ký team: {existing['team_name']}\n"
            "Nếu muốn thay đổi thông tin, liên hệ admin.",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        return ConversationHandler.END

    await _safe_edit(query, "📝 <b>Bước 1/5</b> — Nhập tên của bạn:", parse_mode="HTML")
    return WAITING_USER_NAME


async def cmd_dangki(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _dm_only(update, "dangki"):
        return ConversationHandler.END

    # Khoá đăng ký sau deadline (hết hạn sau 13/04/2026)
    registration_deadline = date(2026, 4, 13)
    today = datetime.now(ICT).date()
    if today > registration_deadline:
        await update.message.reply_text(
            "⛔ Đã hết hạn đăng ký team!\n\n"
            "Thời gian đăng ký đã kết thúc vào ngày 13/04/2026.\n"
            "Nếu cần hỗ trợ, vui lòng liên hệ admin.",
            reply_markup=_main_menu_keyboard(registered=False),
        )
        return ConversationHandler.END

    user = update.effective_user
    existing = sheets.get_team_by_user(user.id)
    if existing:
        await update.message.reply_text(
            f"✅ Bạn đã đăng ký team: {existing['team_name']}\n"
            "Nếu muốn thay đổi thông tin, liên hệ admin.",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        return ConversationHandler.END

    await update.message.reply_text("📝 <b>Bước 1/5</b> — Nhập tên của bạn:", parse_mode="HTML")
    return WAITING_USER_NAME


async def receive_user_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 50:
        await update.message.reply_text("⚠️ Tên phải từ 2-50 ký tự. Vui lòng nhập lại:")
        return WAITING_USER_NAME
    context.user_data["reg_user_name"] = name
    await update.message.reply_text("📝 <b>Bước 2/5</b> — Nhập tên team của bạn:", parse_mode="HTML")
    return WAITING_TEAM_NAME


async def receive_team_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    team_name = update.message.text.strip()
    if len(team_name) < 2 or len(team_name) > 50:
        await update.message.reply_text("⚠️ Tên team phải từ 2-50 ký tự. Vui lòng nhập lại:")
        return WAITING_TEAM_NAME
    context.user_data["reg_team_name"] = team_name
    await update.message.reply_text("📝 <b>Bước 3/5</b> — Team họp định kỳ bao lâu một lần?\n(VD: 1 tuần/lần, 2 tuần/lần…)", parse_mode="HTML")
    return WAITING_MEETING_FREQ


async def receive_meeting_freq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    freq = update.message.text.strip()
    if len(freq) < 1 or len(freq) > 100:
        await update.message.reply_text("⚠️ Câu trả lời phải từ 1–100 ký tự. Vui lòng nhập lại:")
        return WAITING_MEETING_FREQ
    context.user_data["reg_meeting_freq"] = freq
    await update.message.reply_text("📝 <b>Bước 4/5</b> — Team có bao nhiêu thành viên?", parse_mode="HTML")
    return WAITING_MEMBER_COUNT


async def receive_member_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    if not txt.isdigit() or int(txt) < 1 or int(txt) > 999:
        await update.message.reply_text("⚠️ Vui lòng nhập một số hợp lệ (1-999):")
        return WAITING_MEMBER_COUNT
    context.user_data["reg_member_count"] = txt
    await update.message.reply_text("📝 <b>Bước 5/5</b> — Liệt kê tên các thành viên chính trong team:\n(Mỗi người một dòng hoặc cách nhau bằng dấu phẩy)", parse_mode="HTML")
    return WAITING_MEMBER_LIST


async def receive_member_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    members = update.message.text.strip()
    if len(members) < 2 or len(members) > 500:
        await update.message.reply_text("⚠️ Danh sách phải từ 2-500 ký tự. Vui lòng nhập lại:")
        return WAITING_MEMBER_LIST

    user = update.effective_user
    team = sheets.register_team(
        telegram_user_id=user.id,
        username=_username(update),
        user_name=context.user_data.get("reg_user_name", ""),
        team_name=context.user_data.get("reg_team_name", ""),
        meeting_freq=context.user_data.get("reg_meeting_freq", ""),
        member_count=context.user_data.get("reg_member_count", ""),
        member_list=members,
    )

    # Cleanup temp data
    for key in ("reg_user_name", "reg_team_name", "reg_meeting_freq", "reg_member_count"):
        context.user_data.pop(key, None)

    await update.message.reply_text(
        f"✅ Đã đăng ký team: <b>{team['team_name']}</b> ({team['team_id']})\n\n"
        "Bây giờ bạn có thể sử dụng các chức năng bên dưới:",
        parse_mode="HTML",
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

    if update.effective_chat.type != ChatType.PRIVATE:
        await _safe_edit(query, "Vui lòng nhắn riêng cho bot để check-in nhé!")
        return ConversationHandler.END

    user = update.effective_user
    team = sheets.get_team_by_user(user.id)
    if not team:
        await _safe_edit(
            query,
            "⚠️ Bạn chưa đăng ký team. Bấm \"📝 Đăng ký team\" trước nhé.",
            reply_markup=_main_menu_keyboard(registered=False),
        )
        return ConversationHandler.END

    # Khoá check-in sau deadline (hết hạn sau 17/05/2026)
    checkin_deadline = date(2026, 5, 17)
    today = datetime.now(ICT).date()
    if today > checkin_deadline:
        await _safe_edit(
            query,
            "⛔ Đã hết hạn check-in!\n\n"
            "Thời gian check-in đã kết thúc vào ngày 17/05/2026.\n"
            "Nếu cần hỗ trợ, vui lòng liên hệ admin.",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        return ConversationHandler.END

    context.user_data["checkin_team"] = team

    # Check challenge kết thúc + trùng ngay từ đầu
    week = _current_week()
    if week is not None and week > config.TOTAL_WEEKS:
        await _safe_edit(
            query,
            f"⚠️ Thử thách đã kết thúc (tuần {config.TOTAL_WEEKS}/{config.TOTAL_WEEKS}).",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        _checkin_cleanup(context)
        return ConversationHandler.END
    if week is not None and sheets.team_already_checked_in(team["team_id"], week):
        await _safe_edit(
            query,
            f"⚠️ Team {team['team_name']} đã check-in tuần {week} rồi.\n"
            "Hẹn gặp lại tuần sau nhé!",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        _checkin_cleanup(context)
        return ConversationHandler.END

    await _safe_edit(
        query,
        "📋 Check-in tuần — Bước 1/2\n\n"
        '📖 Trước khi check-in, hãy xem <a href="https://docs.google.com/document/d/1yC_0CVwUNiTwhc5LDIpODxocB0CPjyopqrdhzd3YYv0/edit?tab=t.0">hướng dẫn NotebookLM</a> để biết cách tổng hợp cuộc họp.\n\n'
        "📸 Gửi ảnh chụp màn hình NotebookLM mới nhất của bạn:\n"
        "Gửi /cancel để huỷ.",
        parse_mode="HTML",
        disable_web_page_preview=True,
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

    # Khoá check-in sau deadline (hết hạn sau 17/05/2026)
    checkin_deadline = date(2026, 5, 17)
    today = datetime.now(ICT).date()
    if today > checkin_deadline:
        await message.reply_text(
            "⛔ Đã hết hạn check-in!\n\n"
            "Thời gian check-in đã kết thúc vào ngày 17/05/2026.\n"
            "Nếu cần hỗ trợ, vui lòng liên hệ admin.",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        return ConversationHandler.END

    context.user_data["checkin_team"] = team

    # Check challenge kết thúc + trùng ngay từ đầu
    week = _current_week()
    if week is not None and week > config.TOTAL_WEEKS:
        await message.reply_text(
            f"⚠️ Thử thách đã kết thúc (tuần {config.TOTAL_WEEKS}/{config.TOTAL_WEEKS}).",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        _checkin_cleanup(context)
        return ConversationHandler.END
    if week is not None and sheets.team_already_checked_in(team["team_id"], week):
        await message.reply_text(
            f"⚠️ Team {team['team_name']} đã check-in tuần {week} rồi.\n"
            "Hẹn gặp lại tuần sau nhé!",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        _checkin_cleanup(context)
        return ConversationHandler.END

    # Nếu gửi ảnh + caption đầy đủ → validate ảnh + xử lý thẳng (shortcut)
    text = message.caption or message.text or ""
    submission = re.sub(r"^/checkin\s*", "", text, flags=re.IGNORECASE).strip()
    if bool(message.photo) and submission and (week is not None or _extract_week(submission)):
        photo_id = message.photo[-1].file_id
        await message.reply_text("⏳ Đang xác minh ảnh NotebookLM...")
        tg_file = await context.bot.get_file(photo_id)
        photo_bytes = bytes(await tg_file.download_as_bytearray())
        photo_result = await asyncio.to_thread(scoring.validate_notebooklm_photo, photo_bytes)
        if not photo_result.valid:
            await message.reply_text(
                f"❌ Ảnh không hợp lệ: {photo_result.reason}\n\n"
                "Vui lòng gửi lại ảnh chụp màn hình NotebookLM."
            )
            return WAITING_CHECKIN_PHOTO
        context.user_data["checkin_photo_id"] = photo_id
        context.user_data["checkin_photo_bytes"] = photo_bytes
        return await _process_checkin(update, context, submission)

    # Bắt đầu flow từng bước
    await message.reply_text(
        "📋 Check-in tuần — Bước 1/2\n\n"
        '📖 Trước khi check-in, hãy xem <a href="https://docs.google.com/document/d/1yC_0CVwUNiTwhc5LDIpODxocB0CPjyopqrdhzd3YYv0/edit?tab=t.0">hướng dẫn NotebookLM</a> để biết cách tổng hợp cuộc họp.\n\n'
        "📸 Gửi ảnh chụp màn hình NotebookLM mới nhất của bạn:\n"
        "Gửi /cancel để huỷ.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return WAITING_CHECKIN_PHOTO


async def checkin_receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bước 1: Nhận và xác minh ảnh NotebookLM."""
    message = update.effective_message
    if not message.photo:
        await message.reply_text("⚠️ Không nhận được ảnh. Vui lòng gửi lại.")
        return WAITING_CHECKIN_PHOTO
    photo_id = message.photo[-1].file_id

    # Tải ảnh và xác minh bằng AI vision
    await message.reply_text("⏳ Đang xác minh ảnh NotebookLM...")
    tg_file = await context.bot.get_file(photo_id)
    photo_bytes = bytes(await tg_file.download_as_bytearray())
    photo_result = await asyncio.to_thread(scoring.validate_notebooklm_photo, photo_bytes)

    if not photo_result.valid:
        await message.reply_text(
            f"❌ Ảnh không hợp lệ: {photo_result.reason}\n\n"
            "Vui lòng gửi lại ảnh chụp màn hình NotebookLM "
            "(notebooklm.google.com — giao diện Audio Overview, Notebook Guide hoặc Sources)."
        )
        return WAITING_CHECKIN_PHOTO

    context.user_data["checkin_photo_id"] = photo_id
    context.user_data["checkin_photo_bytes"] = photo_bytes

    # Nếu ảnh kèm caption đầy đủ → xử lý thẳng
    caption = message.caption or ""
    if caption.strip() and (_current_week() is not None or _extract_week(caption)):
        return await _process_checkin(update, context, caption)

    # Chuyển bước 2 — hướng dẫn gửi kết quả prompt AI
    await message.reply_text(
        "✅ Ảnh NotebookLM hợp lệ!\n\n"
        "<b>📋 Check-in tuần — Bước 2/2</b>\n\n"
        "Copy prompt bên dưới, dán vào NotebookLM, "
        "rồi gửi kết quả lại đây nhé.\n\n"
        "🔖 <b>Prompt</b> (copy vào NotebookLM):\n\n"
        "<i>Hãy tóm tắt thông tin cuộc họp như sau. "
        "Tất cả chỉ cần con số, biểu diễn ngắn gọn trong 1 dòng "
        "không cần liệt kê cụ thể: Ngày diễn ra cuộc họp cuối, "
        "Số người tham dự, số người vắng, "
        "Số vấn đề được raise lên trong cuộc họp này, "
        "Số lượng next action trong cuộc họp này, "
        "Tổng số action còn tồn đọng cộng dồn cả các cuộc họp</i>\n\n"
        "💬 <b>Ví dụ kết quả:</b>\n\n"
        "<code>Ngày: 18/03/2026, Tham dự: 11, Vắng: 1, "
        "Vấn đề raised: 4, Next action: 3, "
        "Tồn đọng: 3</code>\n\n"
        "Gửi /cancel để huỷ.",
        parse_mode="HTML",
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
    """Bước 2: Nhận kết quả prompt tóm tắt cuộc họp."""
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("⚠️ Vui lòng gửi kết quả tóm tắt cuộc họp từ NotebookLM:")
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

    # Ưu tiên tính tuần từ start_date; fallback về #week_N nếu có
    week = _current_week()
    if week is None:
        # Fallback: dùng #week_N từ user (nếu có)
        week = _extract_week(submission)
        if week is None:
            await message.reply_text(
                "❌ Chưa thiết lập ngày bắt đầu thử thách và không tìm thấy #week_<số>.\n"
                "Liên hệ admin để /setstart hoặc thêm #week_<số> vào nội dung.",
            )
            return WAITING_CHECKIN_CONTENT
    if week < 1:
        await message.reply_text("⚠️ Tuần không hợp lệ.")
        return WAITING_CHECKIN_CONTENT
    if week > config.TOTAL_WEEKS:
        await message.reply_text(
            f"⚠️ Thử thách đã kết thúc (tuần {config.TOTAL_WEEKS}/{config.TOTAL_WEEKS}).",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        _checkin_cleanup(context)
        return ConversationHandler.END
    else:
        # Kiểm tra nếu user ghi sai tuần → cảnh báo nhẹ nhưng vẫn dùng tuần đúng
        user_week = _extract_week(submission)
        if user_week and user_week != week:
            logger.warning(
                "User %s ghi #week_%d nhưng tuần thực tế là %d — dùng tuần %d.",
                update.effective_user.id, user_week, week, week,
            )

    if sheets.team_already_checked_in(team["team_id"], week):
        await message.reply_text(
            f"⚠️ Team {team['team_name']} đã check-in cho tuần {week} rồi.",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        _checkin_cleanup(context)
        return ConversationHandler.END

    await message.reply_text("⏳ Đang kiểm tra check-in của bạn...")
    result = await asyncio.to_thread(scoring.score_checkin, submission)
    if not result.valid:
        await message.reply_text(
            f"❌ Check-in chưa hợp lệ: {result.reason}\n\nVui lòng sửa và gửi lại.",
        )
        return WAITING_CHECKIN_CONTENT

    # Upload ảnh lên S3 (nếu đã cấu hình) — dùng bytes đã cache
    photo_url: str | None = None
    photo_id = context.user_data.get("checkin_photo_id")
    if photo_id and config.USE_S3:
        try:
            photo_bytes = context.user_data.get("checkin_photo_bytes")
            if not photo_bytes:
                tg_file = await context.bot.get_file(photo_id)
                photo_bytes = bytes(await tg_file.download_as_bytearray())
            photo_url = await asyncio.to_thread(
                storage.upload_checkin_photo, photo_bytes, team["team_id"], week
            )
        except Exception as e:
            logger.error("Failed to upload photo to S3: %s", e)

    member_count = _extract_member_count(submission) or 0
    rank = sheets.count_checkins_for_week(week) + 1
    points = config.CHECKIN_POINTS

    try:
        await asyncio.to_thread(
            sheets.save_checkin,
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
        await asyncio.to_thread(sheets.compute_and_save_leaderboard)
        await asyncio.to_thread(sheets.update_organizer_details)
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
            await context.bot.send_message(chat_id=config.GROUP_CHAT_ID, text=forward_text, message_thread_id=config.GROUP_TOPIC_ID, parse_mode="HTML")
        except Exception as e:
            logger.error("Failed to forward checkin to group: %s", e)

    _checkin_cleanup(context)
    return ConversationHandler.END


def _checkin_cleanup(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("checkin_team", None)
    context.user_data.pop("checkin_photo_id", None)
    context.user_data.pop("checkin_photo_bytes", None)


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
    """Bấm button 'Nộp bài dự thi' → hướng dẫn + chờ nội dung."""
    query = update.callback_query
    await query.answer()

    if update.effective_chat.type != ChatType.PRIVATE:
        await _safe_edit(query, "Vui lòng nhắn riêng cho bot để nộp bài nhé!")
        return ConversationHandler.END

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

    urgency = ""
    if prev_best == 0:
        urgency = "🚀 Team chưa có bài nào — nộp ngay để không bị bỏ lại!\n\n"
    elif prev_best < 50:
        urgency = f"⚡ Bài tốt nhất của team: {prev_best}/80 — nộp thêm để nâng điểm!\n\n"
    else:
        urgency = f"✨ Bài tốt nhất: {prev_best}/80 — nộp thêm nếu muốn cải thiện!\n\n"

    await _safe_edit(
        query,
        "💡 Bài dự thi (tối đa 80 điểm)\n\n"
        + urgency +
        "Nộp nhiều lần được, chỉ tính 1 lần điểm cao nhất.\n"
        "Bài dự thi là private, khi kết thúc cuộc thi mới public.\n"
        "Top 10 bài điểm cao nhất sẽ được Hội đồng AI chấm trực tiếp và trao giải.\n\n"
        "📝 Yêu cầu:\n"
        "• Viết dạng Markdown, 100–1000 từ\n"
        "• Có raise vấn đề, có lập luận, có ví dụ\n\n"
        "📋 3 nhóm bài (trọng số cao → thấp):\n"
        "1️⃣ Đề xuất Quy trình họp Team hiệu quả với AI\n"
        "2️⃣ Chia sẻ quy trình cá nhân/team/phòng ban dùng AI tối ưu hiệu suất\n"
        "3️⃣ Chia sẻ, nhận xét, đánh giá về tin tức/sự kiện AI\n\n"
        "🤖 AI chấm theo 3 tiêu chí:\n"
        "• Tính mới (26đ) — cách dùng AI độc đáo, có twist riêng\n"
        "• Tính thực tế (27đ) — có số liệu trước/sau, đã áp dụng thật\n"
        "• Độ rõ workflow (27đ) — mô tả rõ input → tool → output\n\n"
        "Gửi /cancel để huỷ.",
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

    word_count = len(submission.split()) if submission else 0
    if submission and word_count >= 100:
        return await _process_share(update, context, submission)

    # Chờ nội dung
    prev_best = sheets.get_best_share_score(team["team_id"])

    if prev_best == 0:
        hint = "🚀 Team chưa có bài nào — nộp ngay để không bị bỏ lại!\n\n"
    elif prev_best < 50:
        hint = f"⚡ Bài tốt nhất của team: {prev_best}/80 — nộp thêm để nâng điểm!\n\n"
    else:
        hint = f"✨ Bài tốt nhất: {prev_best}/80 — nộp thêm nếu muốn cải thiện!\n\n"

    await message.reply_text(
        "💡 Bài dự thi (tối đa 80 điểm)\n\n"
        + hint +
        "Nộp nhiều lần được, chỉ tính 1 lần điểm cao nhất.\n"
        "Bài dự thi là private, khi kết thúc cuộc thi mới public.\n"
        "Top 10 bài điểm cao nhất sẽ được Hội đồng AI chấm trực tiếp và trao giải.\n\n"
        "📝 Yêu cầu:\n"
        "• Viết dạng Markdown, 100–1000 từ\n"
        "• Có raise vấn đề, có lập luận, có ví dụ\n\n"
        "📋 3 nhóm bài (trọng số cao → thấp):\n"
        "1️⃣ Đề xuất Quy trình họp Team hiệu quả với AI\n"
        "2️⃣ Chia sẻ quy trình cá nhân/team/phòng ban dùng AI tối ưu hiệu suất\n"
        "3️⃣ Chia sẻ, nhận xét, đánh giá về tin tức/sự kiện AI\n\n"
        "🤖 AI chấm theo 3 tiêu chí:\n"
        "• Tính mới (26đ) — cách dùng AI độc đáo, có twist riêng\n"
        "• Tính thực tế (27đ) — có số liệu trước/sau, đã áp dụng thật\n"
        "• Độ rõ workflow (27đ) — mô tả rõ input → tool → output\n\n"
        "Gửi /cancel để huỷ.",
    )
    return WAITING_SHARE_CONTENT


async def share_receive_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Nhận nội dung bài dự thi."""
    text = (update.message.text or "").strip()
    word_count = len(text.split()) if text else 0
    if word_count < 100:
        await update.message.reply_text(
            f"⚠️ Bài quá ngắn ({word_count} từ, 100–1000 từ). Gửi lại:\n"
            "Gửi /cancel để huỷ.",
        )
        return WAITING_SHARE_CONTENT
    if word_count > 1000:
        await update.message.reply_text(
            f"⚠️ Bài quá dài ({word_count} từ, tối đa 1000 từ). Gửi lại:\n"
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

    cw = _current_week()
    week = cw or _extract_week(submission) or 0

    # Kiểm tra challenge đã kết thúc
    if cw is not None and cw > config.TOTAL_WEEKS:
        await message.reply_text(
            f"⚠️ Thử thách đã kết thúc (tuần {config.TOTAL_WEEKS}/{config.TOTAL_WEEKS}).",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        context.user_data.pop("share_team", None)
        return ConversationHandler.END

    word_count = len(submission.split())
    if word_count < 100:
        await message.reply_text(
            f"⚠️ Bài quá ngắn ({word_count} từ, 100–1000 từ). Gửi lại:",
        )
        return WAITING_SHARE_CONTENT
    if word_count > 1000:
        await message.reply_text(
            f"⚠️ Bài quá dài ({word_count} từ, tối đa 1000 từ). Gửi lại:",
        )
        return WAITING_SHARE_CONTENT

    # Kiểm tra giới hạn 1 bài/ngày
    today_shares = await asyncio.to_thread(sheets.get_shares_today, team["team_id"])
    if len(today_shares) >= config.MAX_SHARES_PER_DAY:
        await message.reply_text(
            "⚠️ Mỗi ngày chỉ được nộp 1 bài dự thi.\n"
            "Hãy chỉnh sửa kỹ rồi gửi lại vào ngày mai nhé!",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        context.user_data.pop("share_team", None)
        return ConversationHandler.END
    # Kiểm tra giới hạn số bài/tuần + lấy bài cũ để check trùng
    prev_shares = await asyncio.to_thread(sheets.get_shares_this_week, team["team_id"])
    if len(prev_shares) >= config.MAX_SHARES_PER_WEEK:
        await message.reply_text(
            f"⚠️ Team đã nộp {len(prev_shares)}/{config.MAX_SHARES_PER_WEEK} bài tuần này. "
            "Vui lòng đợi tuần sau nhé!",
            reply_markup=_main_menu_keyboard(registered=True),
        )
        context.user_data.pop("share_team", None)
        return ConversationHandler.END
    # if prev_shares:
    #     prev_contents = [s.get("content", "") for s in prev_shares if s.get("content")]
    #     is_dup, dup_reason = await asyncio.to_thread(scoring.is_duplicate_topic, submission, prev_contents)
    #     if is_dup:
    #         await message.reply_text(
    #             f"⚠️ Bài có vẻ trùng chủ đề với bài đã nộp tuần này:\n{dup_reason}\n\n"
    #             "Vui lòng viết về chủ đề AI khác.",
    #         )
    #         return WAITING_SHARE_CONTENT

    prev_best = await asyncio.to_thread(sheets.get_best_share_score, team["team_id"])
    global_best = await asyncio.to_thread(sheets.get_global_best_share_score)

    await message.reply_text("🤖 Đang dùng AI để chấm bài của bạn...")
    try:
        result = await asyncio.to_thread(scoring.score_sharing, submission)
        await asyncio.to_thread(
            sheets.save_share,
            team_id=team["team_id"],
            team_name=team["team_name"],
            week=week,
            content=submission[:30000],
            score=result.score,
            category=result.category,
            novelty=result.novelty,
            practicality=result.practicality,
            workflow_clarity=result.workflow_clarity,
            feedback=result.feedback,
        )
        await asyncio.to_thread(sheets.compute_and_save_leaderboard)
    except Exception as e:
        logger.error("Scoring/save failed: %s", e)
        await message.reply_text("❌ Chấm điểm hoặc lưu gặp lỗi. Vui lòng thử lại sau.")
        context.user_data.pop("share_team", None)
        return ConversationHandler.END

    category_names = {1: "Quy trình họp Team với AI", 2: "Quy trình dùng AI tối ưu hiệu suất", 3: "Nhận xét tin tức/sự kiện AI"}
    is_global_record = result.score > global_best
    is_team_best = result.score > prev_best
    result_text = (
        f"🎯 Điểm bài dự thi: {result.score}/80\n\n"
        f"📂 Nhóm: {result.category} — {category_names.get(result.category, 'Khác')}\n"
        f"💡 Tính mới: {result.novelty}/26\n"
        f"🔧 Tính thực tế: {result.practicality}/27\n"
        f"📋 Độ rõ workflow: {result.workflow_clarity}/27\n\n"
        f"📝 Nhận xét: {result.feedback}"
    )
    if is_global_record:
        result_text += "\n\n🏆 Kỷ lục mới toàn cuộc thi! 🎉"
    elif is_team_best:
        result_text += "\n\n⭐ Đây là điểm cao nhất của team bạn!"
    else:
        result_text += f"\n\n📊 Điểm cao nhất hiện tại của team: {prev_best}/80 (chỉ tính lần cao nhất)"

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
                is_new_best=is_global_record,
            )
            await context.bot.send_message(chat_id=config.GROUP_CHAT_ID, text=forward_text, message_thread_id=config.GROUP_TOPIC_ID, parse_mode="HTML")
        except Exception as e:
            logger.error("Failed to forward share to group: %s", e)

    context.user_data.pop("share_team", None)
    return ConversationHandler.END


async def cancel_share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    registered = sheets.get_team_by_user(user.id) is not None
    context.user_data.pop("share_team", None)
    await update.message.reply_text(
        "Đã huỷ nộp bài.",
        reply_markup=_main_menu_keyboard(registered),
    )
    return ConversationHandler.END


def _cleanup_all_flows(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dọn dẹp user_data của tất cả flows."""
    _checkin_cleanup(context)
    context.user_data.pop("share_team", None)
    for key in ("reg_user_name", "reg_team_name", "reg_meeting_freq", "reg_member_count"):
        context.user_data.pop(key, None)


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Huỷ mọi flow đang chạy (dangki / checkin / share)."""
    user = update.effective_user
    registered = sheets.get_team_by_user(user.id) is not None
    _cleanup_all_flows(context)
    await update.message.reply_text(
        "Đã huỷ.",
        reply_markup=_main_menu_keyboard(registered),
    )
    return ConversationHandler.END


# ── Admin: quản lý prompt chấm điểm ─────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def cmd_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/prompt [checkin|sharing] — Xem prompt hiện tại (admin only)."""
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("⛔ Chỉ admin mới dùng được lệnh này.")
        return

    args = context.args
    keys = scoring.list_prompt_keys()

    if not args:
        await update.message.reply_text(
            f"📋 Các prompt có thể xem/sửa: {', '.join(keys)}\n\n"
            "Dùng: /prompt <tên>\n"
            "Ví dụ: /prompt sharing",
        )
        return

    key = args[0].lower()
    if key not in keys:
        await update.message.reply_text(f"⚠️ Prompt không tồn tại. Chọn: {', '.join(keys)}")
        return

    defaults = {
        "checkin": scoring.CHECKIN_SYSTEM_PROMPT,
        "sharing": scoring.SHARING_SYSTEM_PROMPT,
    }
    current = scoring.get_prompt(key, defaults[key])
    is_custom = scoring.has_custom_prompt(key)

    status = "✏️ Custom" if is_custom else "📦 Mặc định"
    # Telegram giới hạn 4096 ký tự, cắt nếu cần
    display = current[:3800]
    if len(current) > 3800:
        display += "\n\n... (đã cắt bớt)"

    await update.message.reply_text(
        f"📌 Prompt [{key}] — {status}\n"
        f"📏 {len(current)} ký tự\n\n"
        f"{display}",
    )


async def cmd_setprompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setprompt <key> <nội dung> — Cập nhật prompt (admin only, max 4000 ký tự)."""
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("⛔ Chỉ admin mới dùng được lệnh này.")
        return

    text = (update.message.text or "").strip()
    # Parse: /setprompt <key> <content...>
    parts = text.split(None, 2)  # ['/setprompt', key, content]
    keys = scoring.list_prompt_keys()

    if len(parts) < 3:
        await update.message.reply_text(
            f"Cách dùng: /setprompt <{'/'.join(keys)}> <nội dung prompt>\n\n"
            f"Tối đa {config.MAX_PROMPT_LENGTH} ký tự.\n"
            "Dùng /resetprompt <tên> để về mặc định.",
        )
        return

    key = parts[1].lower()
    content = parts[2]

    if key not in keys:
        await update.message.reply_text(f"⚠️ Prompt không tồn tại. Chọn: {', '.join(keys)}")
        return

    if len(content) > config.MAX_PROMPT_LENGTH:
        await update.message.reply_text(
            f"⚠️ Prompt quá dài ({len(content)} ký tự, tối đa {config.MAX_PROMPT_LENGTH}).",
        )
        return

    scoring.set_prompt(key, content)
    await update.message.reply_text(
        f"✅ Đã cập nhật prompt [{key}] ({len(content)} ký tự).\n"
        "Dùng /prompt " + key + " để xem lại.",
    )


async def cmd_resetprompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/resetprompt <key> — Reset prompt về mặc định (admin only)."""
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("⛔ Chỉ admin mới dùng được lệnh này.")
        return

    args = context.args
    keys = scoring.list_prompt_keys()

    if not args:
        await update.message.reply_text(f"Cách dùng: /resetprompt <{'/'.join(keys)}>")
        return

    key = args[0].lower()
    if key not in keys:
        await update.message.reply_text(f"⚠️ Prompt không tồn tại. Chọn: {', '.join(keys)}")
        return

    scoring.reset_prompt(key)
    await update.message.reply_text(f"✅ Đã reset prompt [{key}] về mặc định.")


async def cmd_setstart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setstart YYYY-MM-DD — Set ngày bắt đầu thử thách (admin only)."""
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("⛔ Chỉ admin mới dùng được lệnh này.")
        return

    args = context.args
    if not args:
        current = config.CHALLENGE_START_DATE or scoring.get_prompt("start_date")
        week = _current_week()
        if current:
            status = f"📅 Ngày bắt đầu hiện tại: {current}"
            if week:
                status += f" (đang tuần {week}/{config.TOTAL_WEEKS})"
        else:
            status = "⚠️ Chưa set ngày bắt đầu."
        await update.message.reply_text(
            f"{status}\n\nCách dùng: /setstart YYYY-MM-DD\nVí dụ: /setstart 2026-03-23",
        )
        return

    date_str = args[0].strip()
    try:
        date.fromisoformat(date_str)
    except ValueError:
        await update.message.reply_text("⚠️ Sai format. Dùng YYYY-MM-DD, ví dụ: 2026-03-23")
        return

    scoring.set_prompt("start_date", date_str)
    week = _current_week()
    await update.message.reply_text(
        f"✅ Đã set ngày bắt đầu: {date_str}\n"
        f"📅 Tuần hiện tại: {week if week else 'chưa bắt đầu'}/{config.TOTAL_WEEKS}",
    )


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
    """Xem BXH — hoạt động cả DM và group. Trong group tự xoá sau 1 phút."""
    try:
        standings = sheets.compute_and_save_leaderboard()
        text = lb.format_leaderboard(standings)
    except Exception as e:
        logger.error("Leaderboard error: %s", e)
        text = "❌ Không tải được leaderboard lúc này."

    if _is_dm(update):
        user = update.effective_user
        registered = sheets.get_team_by_user(user.id) is not None
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=_main_menu_keyboard(registered))
        return

    sent = await update.message.reply_text(text, parse_mode="HTML")

    # Xoá cả lệnh user và reply của bot sau 1 phút
    context.job_queue.run_once(
        _delete_after, 60,
        data={"chat_id": sent.chat_id, "message_id": sent.message_id},
    )
    context.job_queue.run_once(
        _delete_after, 60,
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
        await context.bot.send_message(chat_id=config.GROUP_CHAT_ID, text=text, message_thread_id=config.GROUP_TOPIC_ID, parse_mode="HTML")
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
            BotCommand("share", "Nộp bài dự thi"),
            BotCommand("leaderboard", "Xem bảng xếp hạng"),
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

    # Commands cho Admin (hiện thêm lệnh quản trị)
    admin_commands = [
        BotCommand("start", "Bắt đầu bot"),
        BotCommand("dangki", "Đăng ký tên team"),
        BotCommand("checkin", "Check-in tuần"),
        BotCommand("share", "Nộp bài dự thi"),
        BotCommand("leaderboard", "Xem bảng xếp hạng"),
        BotCommand("help", "Hướng dẫn sử dụng"),
        BotCommand("prompt", "Xem prompt chấm điểm"),
        BotCommand("setprompt", "Sửa prompt chấm điểm"),
        BotCommand("resetprompt", "Reset prompt về mặc định"),
        BotCommand("setstart", "Set ngày bắt đầu thử thách"),
    ]
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.set_my_commands(
                commands=admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception as e:
            logger.warning("Failed to set admin commands for %s: %s", admin_id, e)

    logger.info("Đã set command menu cho DM, Group và Admin.")


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
            WAITING_USER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_user_name),
            ],
            WAITING_TEAM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_team_name),
            ],
            WAITING_MEETING_FREQ: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_meeting_freq),
            ],
            WAITING_MEMBER_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_member_count),
            ],
            WAITING_MEMBER_LIST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_member_list),
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

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("prompt", cmd_prompt))
    app.add_handler(CommandHandler("setprompt", cmd_setprompt))
    app.add_handler(CommandHandler("resetprompt", cmd_resetprompt))
    app.add_handler(CommandHandler("setstart", cmd_setstart))
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
