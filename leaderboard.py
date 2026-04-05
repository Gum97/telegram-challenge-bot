"""
leaderboard.py - Format bảng xếp hạng và các thông báo forward lên group.
"""

import html
import logging
from typing import Optional

import config
import sheets

logger = logging.getLogger(__name__)
MEDAL = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}


def format_leaderboard(standings: list[dict], week: Optional[int] = None) -> str:
    if not standings:
        return "Chưa có team nào đăng ký."

    title = "\U0001f3c6 AI Meeting Challenge — Bảng xếp hạng"
    if week:
        title += f" (Tuần {week})"

    lines = [title, ""]
    for i, team in enumerate(standings, start=1):
        medal = MEDAL.get(i, f"{i}.")
        name = html.escape(str(team['team_name']))
        lines.append(
            f"{medal} {name} — {team['total_points']} điểm "
            f"(check-in {team['checkin_points']} + sharing {team['sharing_points']})"
        )

    lines.append("")
    lines.append("Check-in: 20đ/tuần × 6 tuần = 120đ | Bài dự thi: tối đa 80đ (lấy điểm cao nhất)")
    return "\n".join(lines)


def build_checkin_forward(team_name: str, week: int, rank: int, points: int, username: str) -> str:
    return (
        f"\u2705 Team {html.escape(team_name)} vừa check-in tuần {week}!\n"
        f"- Thứ tự tuần này: #{rank}\n"
        f"- Điểm nhận: +{points}\n\n"
        f"Bảng xếp hạng đã được cập nhật. Team bạn đã check-in chưa? \U0001f440"
    )


def build_share_forward(
    team_name: str,
    week: int,
    score: int,
    highlight: str,
    feedback: str,
    username: str,
    is_new_best: bool,
) -> str:
    badge = "\n\U0001f3c6 Kỷ lục mới toàn cuộc thi! 🎉" if is_new_best else ""
    week_text = f"tuần {week}" if week else ""
    return (
        f"\U0001f4a1 Team {html.escape(team_name)} vừa nộp bài dự thi{' — ' + week_text if week_text else ''}!\n"
        f"\U0001f3af Điểm: {score}/80\n"
        f"\u2728 {html.escape(highlight)}"
        f"{badge}\n\n"
        f"Các team khác đang ở đâu trên BXH? Hãy nộp bài dự thi của bạn, hoặc sửa bài cũ để điểm cao hơn nhé! \U0001f525"
    )


async def post_weekly_leaderboard(bot, week: Optional[int] = None) -> None:
    try:
        standings = sheets.compute_and_save_leaderboard()
        await bot.send_message(chat_id=config.GROUP_CHAT_ID, text=format_leaderboard(standings, week=week), message_thread_id=config.GROUP_TOPIC_ID, parse_mode="HTML")
        logger.info("Weekly leaderboard posted to group")
    except Exception as e:
        logger.error("Failed to post weekly leaderboard: %s", e)
