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

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
    """Trích số member từ text, ví dụ '10 người họp' → 10."""
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
    if data == "menu_dangki":
        # Xử lý trong dangki_button_handler (ConversationHandler)
        return
    elif data == "menu_checkin":
        # Xử lý trong checkin_button_handler (ConversationHandler)
        return
    elif data == "menu_share":
        await _safe_edit(
            query,
            "💡 Hướng dẫn Chia sẻ bài AI:\n\n"
            "Bước 1: Viết bài chia sẻ về cách bạn ứng dụng AI\n"
            "   (tối thiểu 30 ký tự)\n"
            "Bước 2: Gửi cho bot (trong DM) với lệnh /share\n\n"
            "📌 Ví dụ:\n"
            "/share #week_1\n"
            "Tuần này team mình dùng ChatGPT để tạo unit test "
            "tự động cho module thanh toán. Kết quả: coverage "
            "tăng từ 40% lên 85%, phát hiện 3 bug tiềm ẩn.\n\n"
            "🤖 Bot sẽ dùng AI chấm điểm bài của bạn theo 3 tiêu chí:\n"
            "• Tính mới (33đ)\n"
            "• Tính thực tế (33đ)\n"
            "• Độ rõ workflow (34đ)",
            reply_markup=kb,
        )
    elif data == "menu_help":
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
    if len(team_name) < 2:
        await update.message.reply_text("⚠️ Tên team quá ngắn. Vui lòng nhập lại:")
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
    """Bước 1: Nhận ảnh NotebookLM."""
    message = update.effective_message

    # Nếu ảnh kèm caption đầy đủ → xử lý thẳng
    caption = message.caption or ""
    if caption.strip() and _extract_week(caption):
        return await _process_checkin(update, context, caption)

    # Lưu ảnh, chuyển bước 2
    context.user_data["checkin_photo_id"] = message.photo[-1].file_id
    await message.reply_text(
        "✅ Đã nhận ảnh!\n\n"
        "📋 Check-in tuần — Bước 2/2\n\n"
        "Gửi nội dung check-in với hashtag:\n\n"
        "📌 Ví dụ:\n"
        "#post #week_1\n"
        "Checkin 17/03/2026\n"
        "10 người họp\n"
        "Thiếu: 1 người\n"
        "3/5 vấn đề tuần trước đã giải quyết\n"
        "2 vấn đề mới phát sinh\n"
        "Tổng vấn đề tồn: 4",
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

    member_count = _extract_member_count(submission) or 0
    rank = sheets.count_checkins_for_week(week) + 1
    points = config.CHECKIN_POINTS

    sheets.save_checkin(
        team_id=team["team_id"],
        team_name=team["team_name"],
        week=week,
        summary_text=submission[:1000],
        has_screenshot=True,
        rank=rank,
        points=points,
        member_count=member_count,
    )
    sheets.compute_and_save_leaderboard()
    sheets.update_organizer_details()

    await message.reply_text(
        f"✅ Check-in thành công!\n\n"
        f"📅 Tuần: {week}\n"
        f"🏅 Thứ hạng tuần này: #{rank}\n"
        f"💰 Điểm nhận: +{points}\n\n"
        f"{result.reason}",
        reply_markup=_main_menu_keyboard(registered=True),
    )

    if config.GROUP_CHAT_ID:
        forward_text = lb.build_checkin_forward(
            team_name=team["team_name"],
            week=week,
            rank=rank,
            points=points,
            username=_username(update),
        )
        await context.bot.send_message(chat_id=config.GROUP_CHAT_ID, text=forward_text)

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


# ── /share ───────────────────────────────────────────────────────────────

async def cmd_share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    if not _is_dm(update):
        await message.reply_text("Vui lòng dùng /share trong tin nhắn riêng với bot!")
        return

    user = update.effective_user
    team = sheets.get_team_by_user(user.id)
    if not team:
        await message.reply_text(
            "⚠️ Bạn chưa đăng ký team. Dùng /dangki trước nhé.",
            reply_markup=_main_menu_keyboard(registered=False),
        )
        return

    text = message.text or ""
    submission = re.sub(r"^/share\s*", "", text, flags=re.IGNORECASE).strip()

    if not submission or len(submission) < 30:
        await message.reply_text(
            "💡 Gửi /share kèm nội dung bài chia sẻ đầy đủ (ít nhất 30 ký tự)."
        )
        return

    week = _extract_week(submission) or 0
    prev_best = sheets.get_best_share_score(team["team_id"])

    await message.reply_text("🤖 Đang dùng AI để chấm bài của bạn...")
    try:
        result = scoring.score_sharing(submission)
    except Exception as e:
        logger.error("Scoring failed: %s", e)
        await message.reply_text("❌ Chấm điểm AI thất bại. Vui lòng thử lại sau.")
        return

    sheets.save_share(
        team_id=team["team_id"],
        team_name=team["team_name"],
        week=week,
        content=submission[:2000],
        score=result.score,
        feedback=result.feedback,
    )
    sheets.compute_and_save_leaderboard()

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


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # ConversationHandler cho đăng ký team (cả lệnh /dangki và button)
    dangki_conv = ConversationHandler(
        entry_points=[
            CommandHandler("dangki", cmd_dangki),
            CallbackQueryHandler(dangki_button_handler, pattern="^menu_dangki$"),
        ],
        states={
            WAITING_TEAM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_team_name),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_dangki)],
        per_message=False,
    )

    # ConversationHandler cho check-in (button và /checkin)
    checkin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(checkin_button_handler, pattern="^menu_checkin$"),
            CommandHandler("checkin", cmd_checkin),
            MessageHandler(
                filters.PHOTO & filters.CaptionRegex(r"(?i)^/checkin"),
                cmd_checkin,
            ),
        ],
        states={
            WAITING_CHECKIN_PHOTO: [
                MessageHandler(filters.PHOTO, checkin_receive_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, checkin_photo_fallback),
            ],
            WAITING_CHECKIN_CONTENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, checkin_receive_content),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_checkin)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(dangki_conv)
    app.add_handler(checkin_conv)
    app.add_handler(CommandHandler("share", cmd_share))
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
