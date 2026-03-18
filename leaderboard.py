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
        f"✅ Một team vừa check-in tuần {week}!\n"
        f"- Thứ tự tuần này: #{rank}\n"
        f"- Điểm nhận: +{points}\n\n"
        f"Leaderboard đã được cập nhật. Team bạn đã check-in chưa? 👀"
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
    badge = "\n🏆 Kỷ lục mới!" if is_new_best else ""
    week_text = f"tuần {week}" if week else ""
    return (
        f"💡 Một team vừa chia sẻ bài AI{' — ' + week_text if week_text else ''}!\n"
        f"🎯 Điểm: {score}/100\n"
        f"✨ {highlight}"
        f"{badge}\n\n"
        f"Team bạn đang ở đâu trên BXH? Thử chia sẻ bài AI ngay! 🔥"
    )


async def post_weekly_leaderboard(bot, week: Optional[int] = None) -> None:
    try:
        standings = sheets.compute_and_save_leaderboard()
        await bot.send_message(chat_id=config.GROUP_CHAT_ID, text=format_leaderboard(standings, week=week))
        logger.info("Weekly leaderboard posted to group")
    except Exception as e:
        logger.error("Failed to post weekly leaderboard: %s", e)
