"""
sheets.py - Tích hợp Google Sheets với fallback lưu local JSON để test.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
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


_gs_client = None
_gs_client_created_at: float = 0


def _get_client():
    global _gs_client, _gs_client_created_at
    import time as _time
    now = _time.monotonic()
    # Cache client for 50 minutes (token expires after 60)
    if _gs_client is None or (now - _gs_client_created_at) > 3000:
        creds = Credentials.from_service_account_file(
            config.GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=SCOPES
        )
        _gs_client = gspread.authorize(creds)
        _gs_client_created_at = now
    return _gs_client


def _get_sheet(tab_name: str):
    client = _get_client()
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    return spreadsheet.worksheet(tab_name)


_SHEET_MIN_ROWS = 10000
_SHEET_MIN_COLS = 50

# Headers mặc định cho từng sheet
_DEFAULT_HEADERS = {
    config.SHEET_TEAMS: ["team_id", "team_name", "telegram_user_id", "username",
                         "user_name", "meeting_freq", "member_count", "member_list",
                         "registered_at"],
    config.SHEET_CHECKINS: ["id", "team_id", "team_name", "week", "submitted_at",
                            "rank", "points", "summary_text", "has_screenshot",
                            "validated", "member_count", "photo_url"],
    config.SHEET_SHARES: ["id", "team_id", "team_name", "week", "submitted_at",
                          "content", "score", "category", "novelty", 
                          "practicality", "workflow_clarity", 
                          "scored_at", "feedback"],
    config.SHEET_LEADERBOARD: ["team_id", "team_name", "checkin_points",
                               "sharing_points", "total_points", "last_updated"],
}


def _get_all_records(ws, tab_name: str) -> list[dict]:
    """Wrapper for get_all_records that handles duplicate empty headers."""
    headers = _DEFAULT_HEADERS.get(tab_name)
    if headers:
        return ws.get_all_records(expected_headers=headers)
    return ws.get_all_records()


def _expand_sheet(ws) -> None:
    """Mở rộng sheet lên tối thiểu _SHEET_MIN_ROWS dòng và _SHEET_MIN_COLS cột."""
    needs_resize = ws.row_count < _SHEET_MIN_ROWS or ws.col_count < _SHEET_MIN_COLS
    if needs_resize:
        ws.resize(
            rows=max(ws.row_count, _SHEET_MIN_ROWS),
            cols=max(ws.col_count, _SHEET_MIN_COLS),
        )


def _sanitize_cell(value) -> str:
    """Chống formula injection cho Google Sheets — thêm ' ở đầu."""
    s = str(value)
    if s and s[0] in ("=", "@"):
        return "'" + s
    return s


def _append_row_by_headers(ws, record: dict) -> None:
    """Append row theo đúng thứ tự headers trong sheet, sanitize values."""
    headers = ws.row_values(1)
    row_data = [_sanitize_cell(record.get(h, "")) for h in headers]
    ws.append_row(row_data)


def ensure_schema() -> None:
    """Mở rộng grid tất cả các sheet, thêm cột mới nếu thiếu, init headers nếu trống."""
    if config.USE_LOCAL_STORAGE:
        return
    try:
        client = _get_client()
        spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
        for tab in [config.SHEET_TEAMS, config.SHEET_CHECKINS, config.SHEET_SHARES, config.SHEET_LEADERBOARD]:
            try:
                ws = spreadsheet.worksheet(tab)
                _expand_sheet(ws)
                logger.info("Sheet '%s': grid OK (%d rows × %d cols).", tab, ws.row_count, ws.col_count)

                # Init headers nếu row 1 trống
                headers = ws.row_values(1)
                if not headers and tab in _DEFAULT_HEADERS:
                    ws.append_row(_DEFAULT_HEADERS[tab])
                    logger.info("Đã init headers cho sheet '%s'.", tab)
                    headers = _DEFAULT_HEADERS[tab]

                # Thêm cột thiếu
                if tab in _DEFAULT_HEADERS:
                    for col_name in _DEFAULT_HEADERS[tab]:
                        if col_name not in headers:
                            next_col = len(headers) + 1
                            ws.update_cell(1, next_col, col_name)
                            headers.append(col_name)
                            logger.info("Đã thêm cột '%s' vào sheet '%s' (cột %d).", col_name, tab, next_col)
            except Exception as e:
                logger.warning("ensure_schema: không thể xử lý sheet '%s': %s", tab, e)
    except Exception as e:
        logger.warning("ensure_schema: lỗi: %s", e)


def register_team(telegram_user_id: int, username: str, team_name: str,
                   user_name: str = "", meeting_freq: str = "",
                   member_count: str = "", member_list: str = "") -> dict:
    if config.USE_LOCAL_STORAGE:
        data = _load_local()
        for row in data["Teams"]:
            if str(row["telegram_user_id"]) == str(telegram_user_id):
                return row
        team_id = f"team_{len(data['Teams']) + 1}"
        row = {
            "team_id": team_id, "team_name": team_name,
            "telegram_user_id": str(telegram_user_id), "username": username,
            "user_name": user_name, "meeting_freq": meeting_freq,
            "member_count": member_count, "member_list": member_list,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        data["Teams"].append(row)
        _save_local(data)
        return row

    ws = _get_sheet(config.SHEET_TEAMS)
    all_rows = _get_all_records(ws, config.SHEET_TEAMS)
    for row in all_rows:
        if str(row["telegram_user_id"]) == str(telegram_user_id):
            return row
    team_id = f"team_{len(all_rows) + 1}"
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "team_id": team_id, "team_name": team_name,
        "telegram_user_id": str(telegram_user_id), "username": username,
        "user_name": user_name, "meeting_freq": meeting_freq,
        "member_count": member_count, "member_list": member_list,
        "registered_at": now,
    }
    _append_row_by_headers(ws, record)
    return record


def get_team_by_user(telegram_user_id: int) -> Optional[dict]:
    if config.USE_LOCAL_STORAGE:
        return next((r for r in _load_local()["Teams"] if str(r["telegram_user_id"]) == str(telegram_user_id)), None)
    ws = _get_sheet(config.SHEET_TEAMS)
    for row in _get_all_records(ws, config.SHEET_TEAMS):
        if str(row["telegram_user_id"]) == str(telegram_user_id):
            return row
    return None


def get_all_teams() -> list[dict]:
    if config.USE_LOCAL_STORAGE:
        return _load_local()["Teams"]
    ws = _get_sheet(config.SHEET_TEAMS)
    return _get_all_records(ws, config.SHEET_TEAMS)


def count_checkins_for_week(week: int) -> int:
    rows = _load_local()["Checkins"] if config.USE_LOCAL_STORAGE else _get_all_records(_get_sheet(config.SHEET_CHECKINS), config.SHEET_CHECKINS)
    return sum(1 for row in rows if int(row["week"]) == week and str(row["validated"]).upper() == "TRUE")


def team_already_checked_in(team_id: str, week: int) -> bool:
    """Check-in trùng: cùng team + cùng challenge week number."""
    rows = _load_local()["Checkins"] if config.USE_LOCAL_STORAGE else _get_all_records(_get_sheet(config.SHEET_CHECKINS), config.SHEET_CHECKINS)
    for row in rows:
        if row["team_id"] != team_id:
            continue
        if str(row.get("validated", "")).upper() != "TRUE":
            continue
        try:
            if int(row["week"]) == week:
                return True
        except (ValueError, TypeError):
            continue
    return False


def save_checkin(team_id: str, team_name: str, week: int, summary_text: str, has_screenshot: bool, rank: int, points: int, member_count: int = 0, photo_url: str | None = None) -> dict:
    row = {
        "id": None, "team_id": team_id, "team_name": team_name, "week": week,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "rank": rank, "points": points, "summary_text": summary_text,
        "has_screenshot": "TRUE" if has_screenshot else "FALSE",
        "validated": "TRUE", "member_count": member_count,
        "photo_url": photo_url or "",
    }
    if config.USE_LOCAL_STORAGE:
        data = _load_local()
        row["id"] = f"ci_{len(data['Checkins']) + 1}"
        data["Checkins"].append(row)
        _save_local(data)
        return row
    ws = _get_sheet(config.SHEET_CHECKINS)
    row["id"] = f"ci_{len(_get_all_records(ws, config.SHEET_CHECKINS)) + 1}"
    _append_row_by_headers(ws, row)
    return row


def get_shares_this_week(team_id: str) -> list[dict]:
    """Lấy danh sách các bài share của team trong tuần hiện tại (theo ICT)."""
    ict = timezone(timedelta(hours=7))
    now = datetime.now(ict)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    rows = _load_local()["Shares"] if config.USE_LOCAL_STORAGE else _get_all_records(_get_sheet(config.SHEET_SHARES), config.SHEET_SHARES)
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


def get_shares_today(team_id: str) -> list[dict]:
    """Lấy danh sách bài share của team trong ngày hôm nay (theo ICT)."""
    ict = timezone(timedelta(hours=7))
    now = datetime.now(ict)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    rows = _load_local()["Shares"] if config.USE_LOCAL_STORAGE else _get_all_records(_get_sheet(config.SHEET_SHARES), config.SHEET_SHARES)
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
            if dt.astimezone(ict) >= today_start:
                result.append(row)
        except (ValueError, TypeError):
            continue
    return result


def get_best_share_score(team_id: str) -> int:
    rows = _load_local()["Shares"] if config.USE_LOCAL_STORAGE else _get_all_records(_get_sheet(config.SHEET_SHARES), config.SHEET_SHARES)
    scores = [int(r["score"]) for r in rows if r["team_id"] == team_id and str(r.get("score", "")).strip() != ""]
    return max(scores) if scores else 0


def get_global_best_share_score() -> int:
    """Lấy điểm share cao nhất toàn cuộc thi (tất cả teams)."""
    rows = _load_local()["Shares"] if config.USE_LOCAL_STORAGE else _get_all_records(_get_sheet(config.SHEET_SHARES), config.SHEET_SHARES)
    scores = [int(r["score"]) for r in rows if str(r.get("score", "")).strip() != ""]
    return max(scores) if scores else 0


def save_share(team_id: str, team_name: str, week: int, content: str, score: int, category: int, novelty: int, practicality: int, workflow_clarity: int, feedback: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": None, "team_id": team_id, "team_name": team_name, "week": week,
        "submitted_at": now, "content": content, 
        "score": score, "category": category, "novelty": novelty, 
        "practicality": practicality, "workflow_clarity": workflow_clarity,
        "scored_at": now, "feedback": feedback,
    }
    if config.USE_LOCAL_STORAGE:
        data = _load_local()
        row["id"] = f"sh_{len(data['Shares']) + 1}"
        data["Shares"].append(row)
        _save_local(data)
        return row
    ws = _get_sheet(config.SHEET_SHARES)
    row["id"] = f"sh_{len(_get_all_records(ws, config.SHEET_SHARES)) + 1}"
    _append_row_by_headers(ws, row)
    return row


def compute_and_save_leaderboard() -> list[dict]:
    try:
        teams = get_all_teams()
        if config.USE_LOCAL_STORAGE:
            data = _load_local()
            checkin_rows = data["Checkins"]
            share_rows = data["Shares"]
        else:
            checkin_rows = _get_all_records(_get_sheet(config.SHEET_CHECKINS), config.SHEET_CHECKINS)
            share_rows = _get_all_records(_get_sheet(config.SHEET_SHARES), config.SHEET_SHARES)

        now = datetime.now(timezone.utc).isoformat()
        standings = []
        for team in teams:
            tid = team["team_id"]
            ci_pts = min(sum(int(r.get("points", 0)) for r in checkin_rows if r["team_id"] == tid and str(r.get("validated", "")).upper() == "TRUE"), config.MAX_CHECKIN_POINTS)
            sh_pts = max((int(r["score"]) for r in share_rows if r["team_id"] == tid and str(r.get("score", "")).strip() != ""), default=0)
            standings.append({"team_id": tid, "team_name": team["team_name"], "checkin_points": ci_pts, "sharing_points": sh_pts, "total_points": ci_pts + sh_pts, "last_updated": now})

        standings.sort(key=lambda x: (x["total_points"], x["sharing_points"], x["checkin_points"]), reverse=True)
        if config.USE_LOCAL_STORAGE:
            data = _load_local()
            data["Leaderboard"] = standings
            _save_local(data)
        else:
            lb_ws = _get_sheet(config.SHEET_LEADERBOARD)
            headers = lb_ws.row_values(1)
            if not headers:
                headers = _DEFAULT_HEADERS[config.SHEET_LEADERBOARD]
            # Batch update: build all rows then write at once
            all_data = [headers]
            for s in standings:
                all_data.append([s.get(h, "") for h in headers])
            lb_ws.resize(rows=1)
            lb_ws.resize(rows=max(len(all_data), 2))
            lb_ws.update(range_name=f"A1:{chr(64 + len(headers))}{len(all_data)}", values=all_data)
        return standings
    except Exception as e:
        logger.error("compute_and_save_leaderboard failed: %s", e)
        return get_leaderboard()  # Trả về dữ liệu cũ nếu lỗi


def get_leaderboard() -> list[dict]:
    return _load_local()["Leaderboard"] if config.USE_LOCAL_STORAGE else _get_all_records(_get_sheet(config.SHEET_LEADERBOARD), config.SHEET_LEADERBOARD)


def update_organizer_details() -> None:
    """Cập nhật sheet tổng hợp Meeting_Organizer_Details từ Teams + Checkins."""
    if config.USE_LOCAL_STORAGE:
        return

    teams = get_all_teams()
    checkin_rows = _get_all_records(_get_sheet(config.SHEET_CHECKINS), config.SHEET_CHECKINS)
    share_rows = _get_all_records(_get_sheet(config.SHEET_SHARES), config.SHEET_SHARES)

    try:
        ws = _get_sheet("Meeting_Organizer_Details")
    except Exception:
        client = _get_client()
        spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
        ws = spreadsheet.add_worksheet(title="Meeting_Organizer_Details", rows=500, cols=7)

    header = ["#", "Leader", "Tên Team / Tên cuộc họp", "Số member", "Check-in", "Score Action", "Tổng điểm"]
    all_data = [header]

    for idx, team in enumerate(teams, 1):
        tid = team["team_id"]
        team_checkins = [r for r in checkin_rows if r["team_id"] == tid and str(r["validated"]).upper() == "TRUE"]
        checkin_count = len(team_checkins)
        latest_members = 0
        if team_checkins:
            latest = max(team_checkins, key=lambda r: r.get("submitted_at", ""))
            latest_members = int(latest.get("member_count", 0) or 0)
        ci_pts = min(sum(int(r["points"]) for r in team_checkins), config.MAX_CHECKIN_POINTS)
        sh_pts = max((int(r["score"]) for r in share_rows if r["team_id"] == tid and str(r.get("score", "")).strip() != ""), default=0)
        total = ci_pts + sh_pts
        checkin_text = f"{checkin_count} lần" if checkin_count else "Chưa"
        all_data.append([idx, team.get("username", ""), team["team_name"], latest_members, checkin_text, sh_pts, total])

    # Batch update thay vì append từng row
    ws.resize(rows=1)
    ws.resize(rows=max(len(all_data), 2))
    ws.update(range_name=f"A1:G{len(all_data)}", values=all_data)
