"""
sheets.py - Tích hợp Google Sheets với fallback lưu local JSON để test.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)

if not config.USE_LOCAL_STORAGE:
    import gspread
    from google.oauth2.service_account import Credentials
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]


def _db_path() -> Path:
    return Path(__file__).with_name(config.LOCAL_DB_FILE)


def _load_local() -> dict:
    path = _db_path()
    if not path.exists():
        return {"Teams": [], "Checkins": [], "Shares": [], "Leaderboard": []}
    return json.loads(path.read_text())


def _save_local(data: dict) -> None:
    _db_path().write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _get_client():
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=SCOPES
    )
    return gspread.authorize(creds)


def _get_sheet(tab_name: str):
    client = _get_client()
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    return spreadsheet.worksheet(tab_name)


def register_team(telegram_user_id: int, username: str, team_name: str) -> dict:
    if config.USE_LOCAL_STORAGE:
        data = _load_local()
        for row in data["Teams"]:
            if str(row["telegram_user_id"]) == str(telegram_user_id):
                return row
        team_id = f"team_{len(data['Teams']) + 1}"
        row = {"team_id": team_id, "team_name": team_name, "telegram_user_id": str(telegram_user_id), "username": username, "registered_at": datetime.utcnow().isoformat()}
        data["Teams"].append(row)
        _save_local(data)
        return row

    ws = _get_sheet(config.SHEET_TEAMS)
    all_rows = ws.get_all_records()
    for row in all_rows:
        if str(row["telegram_user_id"]) == str(telegram_user_id):
            return row
    team_id = f"team_{len(all_rows) + 1}"
    now = datetime.utcnow().isoformat()
    ws.append_row([team_id, team_name, str(telegram_user_id), username, now])
    return {"team_id": team_id, "team_name": team_name, "telegram_user_id": telegram_user_id, "username": username, "registered_at": now}


def get_team_by_user(telegram_user_id: int) -> Optional[dict]:
    if config.USE_LOCAL_STORAGE:
        return next((r for r in _load_local()["Teams"] if str(r["telegram_user_id"]) == str(telegram_user_id)), None)
    ws = _get_sheet(config.SHEET_TEAMS)
    for row in ws.get_all_records():
        if str(row["telegram_user_id"]) == str(telegram_user_id):
            return row
    return None


def get_all_teams() -> list[dict]:
    if config.USE_LOCAL_STORAGE:
        return _load_local()["Teams"]
    return _get_sheet(config.SHEET_TEAMS).get_all_records()


def count_checkins_for_week(week: int) -> int:
    rows = _load_local()["Checkins"] if config.USE_LOCAL_STORAGE else _get_sheet(config.SHEET_CHECKINS).get_all_records()
    return sum(1 for row in rows if int(row["week"]) == week and str(row["validated"]).upper() == "TRUE")


def team_already_checked_in(team_id: str, week: int) -> bool:
    """Check-in trùng: cùng team + cùng tuần lịch (thứ 2-CN theo ICT)."""
    from datetime import timezone, timedelta
    ict = timezone(timedelta(hours=7))
    now = datetime.now(ict)
    # Thứ 2 đầu tuần, 00:00
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    rows = _load_local()["Checkins"] if config.USE_LOCAL_STORAGE else _get_sheet(config.SHEET_CHECKINS).get_all_records()
    for row in rows:
        if row["team_id"] != team_id:
            continue
        submitted = row.get("submitted_at", "")
        if not submitted:
            continue
        try:
            dt = datetime.fromisoformat(submitted)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_ict = dt.astimezone(ict)
            if dt_ict >= monday:
                return True
        except (ValueError, TypeError):
            continue
    return False


def save_checkin(team_id: str, team_name: str, week: int, summary_text: str, has_screenshot: bool, rank: int, points: int, member_count: int = 0) -> dict:
    row = {"id": None, "team_id": team_id, "team_name": team_name, "week": week, "submitted_at": datetime.utcnow().isoformat(), "rank": rank, "points": points, "summary_text": summary_text, "has_screenshot": "TRUE" if has_screenshot else "FALSE", "validated": "TRUE", "member_count": member_count}
    if config.USE_LOCAL_STORAGE:
        data = _load_local()
        row["id"] = f"ci_{len(data['Checkins']) + 1}"
        data["Checkins"].append(row)
        _save_local(data)
        return row
    ws = _get_sheet(config.SHEET_CHECKINS)
    row["id"] = f"ci_{len(ws.get_all_records()) + 1}"
    ws.append_row([row["id"], team_id, team_name, week, row["submitted_at"], rank, points, summary_text, row["has_screenshot"], row["validated"], member_count])
    return row


def get_shares_this_week(team_id: str) -> list[dict]:
    """Lấy danh sách các bài share của team trong tuần hiện tại (theo ICT)."""
    from datetime import timezone, timedelta
    ict = timezone(timedelta(hours=7))
    now = datetime.now(ict)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    rows = _load_local()["Shares"] if config.USE_LOCAL_STORAGE else _get_sheet(config.SHEET_SHARES).get_all_records()
    result = []
    for row in rows:
        if row["team_id"] != team_id:
            continue
        submitted = row.get("submitted_at", "")
        if not submitted:
            continue
        try:
            dt = datetime.fromisoformat(submitted)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt.astimezone(ict) >= monday:
                result.append(row)
        except (ValueError, TypeError):
            continue
    return result


def count_shares_this_week(team_id: str) -> int:
    return len(get_shares_this_week(team_id))


def get_best_share_score(team_id: str) -> int:
    rows = _load_local()["Shares"] if config.USE_LOCAL_STORAGE else _get_sheet(config.SHEET_SHARES).get_all_records()
    scores = [int(r["score"]) for r in rows if r["team_id"] == team_id and str(r.get("score", "")).strip() != ""]
    return max(scores) if scores else 0


def save_share(team_id: str, team_name: str, week: int, content: str, score: int, feedback: str) -> dict:
    row = {"id": None, "team_id": team_id, "team_name": team_name, "week": week, "submitted_at": datetime.utcnow().isoformat(), "content": content, "score": score, "scored_at": datetime.utcnow().isoformat(), "feedback": feedback}
    if config.USE_LOCAL_STORAGE:
        data = _load_local()
        row["id"] = f"sh_{len(data['Shares']) + 1}"
        data["Shares"].append(row)
        _save_local(data)
        return row
    ws = _get_sheet(config.SHEET_SHARES)
    row["id"] = f"sh_{len(ws.get_all_records()) + 1}"
    ws.append_row([row["id"], team_id, team_name, week, row["submitted_at"], content, score, row["scored_at"], feedback])
    return row


def compute_and_save_leaderboard() -> list[dict]:
    try:
        teams = get_all_teams()
        if config.USE_LOCAL_STORAGE:
            data = _load_local()
            checkin_rows = data["Checkins"]
            share_rows = data["Shares"]
        else:
            checkin_rows = _get_sheet(config.SHEET_CHECKINS).get_all_records()
            share_rows = _get_sheet(config.SHEET_SHARES).get_all_records()

        standings = []
        for team in teams:
            tid = team["team_id"]
            ci_pts = min(sum(int(r.get("points", 0)) for r in checkin_rows if r["team_id"] == tid and str(r.get("validated", "")).upper() == "TRUE"), config.MAX_CHECKIN_POINTS)
            sh_pts = max((int(r["score"]) for r in share_rows if r["team_id"] == tid and str(r.get("score", "")).strip() != ""), default=0)
            standings.append({"team_id": tid, "team_name": team["team_name"], "checkin_points": ci_pts, "sharing_points": sh_pts, "total_points": ci_pts + sh_pts, "last_updated": datetime.utcnow().isoformat()})

        standings.sort(key=lambda x: (x["total_points"], x["sharing_points"], x["checkin_points"]), reverse=True)
        if config.USE_LOCAL_STORAGE:
            data = _load_local()
            data["Leaderboard"] = standings
            _save_local(data)
        else:
            lb_ws = _get_sheet(config.SHEET_LEADERBOARD)
            lb_ws.resize(rows=1)
            for s in standings:
                lb_ws.append_row([s["team_id"], s["team_name"], s["checkin_points"], s["sharing_points"], s["total_points"], s["last_updated"]])
        return standings
    except Exception as e:
        logger.error("compute_and_save_leaderboard failed: %s", e)
        return get_leaderboard()  # Trả về dữ liệu cũ nếu lỗi


def get_leaderboard() -> list[dict]:
    return _load_local()["Leaderboard"] if config.USE_LOCAL_STORAGE else _get_sheet(config.SHEET_LEADERBOARD).get_all_records()


def update_organizer_details() -> None:
    """Cập nhật sheet tổng hợp Meeting_Organizer_Details từ Teams + Checkins."""
    if config.USE_LOCAL_STORAGE:
        return

    teams = get_all_teams()
    checkin_rows = _get_sheet(config.SHEET_CHECKINS).get_all_records()
    share_rows = _get_sheet(config.SHEET_SHARES).get_all_records()

    try:
        ws = _get_sheet("Meeting_Organizer_Details")
    except Exception:
        client = _get_client()
        spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
        ws = spreadsheet.add_worksheet(title="Meeting_Organizer_Details", rows=100, cols=7)
        ws.append_row(["#", "Leader", "Tên Team / Tên cuộc họp", "Số member", "Check-in", "Score Action", "Tổng điểm"])

    # Xoá data cũ, giữ header
    ws.resize(rows=1)

    for idx, team in enumerate(teams, 1):
        tid = team["team_id"]
        # Đếm check-in
        team_checkins = [r for r in checkin_rows if r["team_id"] == tid and str(r["validated"]).upper() == "TRUE"]
        checkin_count = len(team_checkins)
        # Lấy số member gần nhất
        latest_members = 0
        if team_checkins:
            latest = max(team_checkins, key=lambda r: r.get("submitted_at", ""))
            latest_members = int(latest.get("member_count", 0) or 0)
        # Tính điểm
        ci_pts = min(sum(int(r["points"]) for r in team_checkins), config.MAX_CHECKIN_POINTS)
        sh_pts = max((int(r["score"]) for r in share_rows if r["team_id"] == tid and str(r.get("score", "")).strip() != ""), default=0)
        total = ci_pts + sh_pts

        checkin_text = f"{checkin_count} lần" if checkin_count else "Chưa"
        ws.append_row([idx, team.get("username", ""), team["team_name"], latest_members, checkin_text, sh_pts, total])
