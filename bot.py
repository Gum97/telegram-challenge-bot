"""
bot.py - Bot Telegram chính cho thử thách AI Meeting.

Luồng hoạt động:
- Người dùng nhắn riêng (DM) để nộp check-in và sharing
- Bot chấm điểm riêng tư, rồi forward kết quả lên group
- Leaderboard được tính từ dữ liệu Google Sheets (hoặc local JSON khi test)
"""

import asyncio
import logging
import re
from datetime import timezone, timedelta

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
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


def _is_dm(update: Update) -> bool:
    """Kiểm tra xem tin nhắn có phải từ DM không."""
    return update.effective_chat.type == ChatType.PRIVATE


def _username(update: Update) -> str:
    """Lấy username hoặc tên đầy đủ của người gửi."""
    user = update.effective_user
    return user.username or user.full_name or str(user.id)


def _extract_week(text: str) -> int | None:
    """Trích xuất số tuần từ hashtag #week_N."""
    m = re.search(r"#week_(\d+)", text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_team_tag(text: str) -> str | None:
    """Trích xuất tên team từ hashtag #team_<tên>."""
    m = re.search(r"#team_([a-z0-9_]+)", text, re.IGNORECASE)
    return m.group(1).lower() if m else None


async def _dm_only(update: Update, command: str) -> bool:
    """Yêu cầu người dùng chỉ dùng lệnh trong DM."""
    if _is_dm(update):
        return True
    await update.message.reply_text(
        f"Vui lòng dùng /{command} trong tin nhắn riêng với bot nhé! 🤫"
    )
    return False


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh /start - đăng ký team."""
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(
            "👋 Chào mừng đến với Bot Thử Thách AI Meeting!\n\n"
            "Đăng ký team của bạn:\n"
            "/start TênTeamCuaBan\n\n"
            "Các lệnh:\n"
            "- /checkin — Nộp check-in hàng tuần (chỉ trong DM)\n"
            "- /share — Chia sẻ bài viết AI (chỉ trong DM)\n"
            "- /leaderboard — Xem bảng xếp hạng"
        )
        return

    team_name = " ".join(args).strip()
    team = sheets.register_team(
        telegram_user_id=user.id,
        username=_username(update),
        team_name=team_name,
    )

    await update.message.reply_text(
        f"✅ Đã đăng ký team: {team['team_name']} ({team['team_id']})\n\n"
        f"Dùng /checkin và /share trong DM với bot để nộp bài nhé!"
    )


async def _handle_checkin_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý nộp check-in (từ command hoặc photo caption)."""
    if not await _dm_only(update, "checkin"):
        return

    user = update.effective_user
    team = sheets.get_team_by_user(user.id)
    if not team:
        await update.message.reply_text(
            "Bạn chưa đăng ký team. Dùng /start TênTeam trước nhé."
        )
        return

    message = update.message
    text = message.caption or message.text or ""
    submission = re.sub(r"^/checkin\s*", "", text, flags=re.IGNORECASE).strip()
    has_photo = bool(message.photo)

    if not submission:
        await update.message.reply_text(
            "📋 *Hướng dẫn check-in:*\n\n"
            "Gửi /checkin kèm ảnh chụp NotebookLM và caption gồm:\n"
            "#post #team_<ten_team> #week_<so>\n"
            "cùng tóm tắt bằng số liệu.\n\n"
            "*Ví dụ:*\n"
            "#post #team_backend #week_1\n"
            "Checkin 12/03/2026\n"
            "10 người họp\n"
            "Thiếu: 1 người\n"
            "3/5 vấn đề tuần trước đã được giải quyết\n"
            "2 vấn đề mới phát sinh\n"
            "Tổng vấn đề tồn: 4",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    if not has_photo:
        await update.message.reply_text(
            "❌ Check-in bắt buộc phải có ảnh chụp NotebookLM mới nhất."
        )
        return

    week = _extract_week(submission)
    if week is None:
        await update.message.reply_text("❌ Thiếu hashtag #week_<so> (ví dụ: #week_1).")
        return

    team_tag = _extract_team_tag(submission)
    if not team_tag:
        await update.message.reply_text("❌ Thiếu hashtag #team_<ten_team>.")
        return

    if sheets.team_already_checked_in(team["team_id"], week):
        await update.message.reply_text(
            f"⚠️ Team {team['team_name']} đã check-in cho tuần {week} rồi."
        )
        return

    await update.message.reply_text("⏳ Đang kiểm tra check-in của bạn...")
    result = scoring.score_checkin(submission)
    if not result.valid:
        await update.message.reply_text(
            f"❌ Check-in bị từ chối: {result.reason}\n\nVui lòng sửa và gửi lại."
        )
        return

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
    )
    standings = sheets.compute_and_save_leaderboard()

    await update.message.reply_text(
        f"✅ Check-in thành công!\n\n"
        f"Tuần: {week}\n"
        f"Thứ hạng tuần này: #{rank}\n"
        f"Điểm nhận: +{points}\n\n"
        f"{result.reason}"
    )

    # Forward lên group (nếu có config GROUP_CHAT_ID)
    if config.GROUP_CHAT_ID:
        forward_text = lb.build_checkin_forward(
            team_name=team["team_name"],
            week=week,
            rank=rank,
            points=points,
            username=_username(update),
        )
        await context.bot.send_message(
            chat_id=config.GROUP_CHAT_ID,
            text=forward_text
        )


async def cmd_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh /checkin (text command)."""
    await _handle_checkin_submission(update, context)


async def cmd_share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh /share - nộp bài chia sẻ AI."""
    if not await _dm_only(update, "share"):
        return

    user = update.effective_user
    team = sheets.get_team_by_user(user.id)
    if not team:
        await update.message.reply_text(
            "Bạn chưa đăng ký team. Dùng /start TênTeam trước nhé."
        )
        return

    text = update.message.text or ""
    submission = re.sub(r"^/share\s*", "", text, flags=re.IGNORECASE).strip()

    if not submission or len(submission) < 30:
        await update.message.reply_text(
            "📝 Gửi /share kèm nội dung bài chia sẻ đầy đủ (ít nhất 30 ký tự)."
        )
        return

    week = _extract_week(submission) or 0
    prev_best = sheets.get_best_share_score(team["team_id"])

    await update.message.reply_text("🤖 Đang dùng AI để chấm bài của bạn...")
    try:
        result = scoring.score_sharing(submission)
    except Exception as e:
        logger.error("Scoring failed: %s", e)
        await update.message.reply_text("❌ Chấm điểm AI thất bại. Vui lòng thử lại sau.")
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
    await update.message.reply_text(
        f"🎯 *Điểm chia sẻ: {result.score}/100*\n\n"
        f"💡 Tính mới: {result.novelty}/33\n"
        f"🔧 Tính thực tế: {result.practicality}/33\n"
        f"📋 Độ rõ workflow: {result.workflow_clarity}/34\n\n"
        f"Nhận xét: {result.feedback}"
        + ("\n\n🏆 Đây là điểm cao nhất của team bạn!" if is_new_best else ""),
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # Forward lên group (nếu có config GROUP_CHAT_ID)
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
        await context.bot.send_message(
            chat_id=config.GROUP_CHAT_ID,
            text=forward_text
        )


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh /leaderboard - hiển thị bảng xếp hạng."""
    try:
        standings = sheets.compute_and_save_leaderboard()
        await update.message.reply_text(lb.format_leaderboard(standings))
    except Exception as e:
        logger.error("Leaderboard error: %s", e)
        await update.message.reply_text("❌ Không tải được leaderboard lúc này.")


def main() -> None:
    """Khởi động bot."""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("checkin", cmd_checkin))
    # Bắt ảnh với caption bắt đầu bằng /checkin (CommandHandler không bắt caption)
    app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r"(?i)^/checkin"), cmd_checkin))
    app.add_handler(CommandHandler("share", cmd_share))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))

    logger.info("Weekly scheduler tạm tắt để test local.")
    logger.info("Bot đang khởi động...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
