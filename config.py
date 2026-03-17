"""
config.py - Đọc và kiểm tra biến môi trường cho bot.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _get(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def _require(key: str) -> str:
    """Lấy biến môi trường bắt buộc; ném lỗi nếu thiếu."""
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Thiếu biến môi trường bắt buộc: {key}")
    return val


# --- Telegram ---
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
GROUP_CHAT_ID_RAW = _get("GROUP_CHAT_ID", "")
# None nếu chưa cấu hình → bot sẽ không forward lên group
GROUP_CHAT_ID: int | None = int(GROUP_CHAT_ID_RAW) if GROUP_CHAT_ID_RAW and GROUP_CHAT_ID_RAW != "-1001234567890" else None

# --- Google Sheets / local fallback ---
GOOGLE_SHEETS_CREDENTIALS_FILE: str = _get("GOOGLE_SHEETS_CREDENTIALS_FILE", "credentials.json")
SPREADSHEET_ID: str | None = _get("SPREADSHEET_ID")
# Dùng lưu local JSON khi chưa có credentials hoặc spreadsheet ID thật
USE_LOCAL_STORAGE: bool = (not SPREADSHEET_ID) or SPREADSHEET_ID == "your_spreadsheet_id_here" or not os.path.exists(GOOGLE_SHEETS_CREDENTIALS_FILE)
LOCAL_DB_FILE: str = _get("LOCAL_DB_FILE", "local_data.json")

# --- OpenAI / chấm điểm dự phòng ---
OPENAI_API_KEY: str | None = _get("OPENAI_API_KEY")
# Dùng heuristic fallback khi chưa có API key thật
USE_FAKE_AI: bool = (not OPENAI_API_KEY) or OPENAI_API_KEY == "sk-..."
OPENAI_MODEL: str = _get("OPENAI_MODEL", "gpt-4o")

# --- Cấu hình thử thách ---
TOTAL_WEEKS: int = int(_get("TOTAL_WEEKS", "10"))
CHECKIN_POINTS: int = int(_get("CHECKIN_POINTS", "10"))
MAX_CHECKIN_POINTS: int = CHECKIN_POINTS * TOTAL_WEEKS  # Tổng điểm check-in tối đa

# --- Tên tab trong Google Sheets ---
SHEET_TEAMS = "Teams"
SHEET_CHECKINS = "Checkins"
SHEET_SHARES = "Shares"
SHEET_LEADERBOARD = "Leaderboard"
