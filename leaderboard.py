"""
leaderboard.py - Format bảng xếp hạng và các thông báo forward lên group.
"""

import logging
from typing import Optional

import config
import sheets

logger = logging.getLogger(__name__)
MEDAL = {1: "🥇", 2: "🥈", 3: "🥉"}


def format_leaderboard(standings: list[dict], week: Optional[int] = None) -> str:
    if not standings:
        return "Chưa có team nào đăng ký."

    title = "🏆 AI Meeting Challenge — Bảng xếp hạng"
    if week:
        title += f" (Tuần {week})"

    lines = [title, ""]
    for i, team in enumerate(standings, start=1):
        medal = MEDAL.get(i, f"{i}.")
        lines.append(
            f"{medal} {team['team_name']} — {team['total_points']} điểm "
            f"(check-in {team['checkin_points']} + sharing {team['sharing_points']})"
        )

    lines.append("")
    lines.append("Check-in: tối đa 100 điểm / 10 tuần | Sharing: chỉ lấy bài cao nhất mỗi team")
    return "\n".join(lines)


def build_checkin_forward(team_name: str, week: int, rank: int, points: int, username: str) -> str:
    return (
        f"✅ Team {team_name} vừa check-in tuần {week}.\n"
        f"- Thứ tự tuần này: #{rank}\n"
        f"- Điểm nhận: +{points}\n"
        f"- Người gửi: @{username}\n\n"
        f"Leaderboard đã được cập nhật. Mời anh em quote và thảo luận 😄"
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
    badge = "🏆 Bài sharing tốt nhất mới của team!\n" if is_new_best else ""
    week_text = f"tuần {week}" if week else "không gắn tuần"
    return (
        f"💡 Team {team_name} vừa gửi bài sharing ({week_text}).\n"
        f"- Điểm AI: {score}/100\n"
        f"- Highlight: {highlight}\n"
        f"- Người gửi: @{username}\n"
        f"{badge}"
        f"\nLeaderboard đã được cập nhật. Mời anh em quote và bàn luận 🔥"
    )


async def post_weekly_leaderboard(bot, week: Optional[int] = None) -> None:
    try:
        standings = sheets.compute_and_save_leaderboard()
        await bot.send_message(chat_id=config.GROUP_CHAT_ID, text=format_leaderboard(standings, week=week))
        logger.info("Weekly leaderboard posted to group")
    except Exception as e:
        logger.error("Failed to post weekly leaderboard: %s", e)
