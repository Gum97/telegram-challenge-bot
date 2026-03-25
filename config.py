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
# Topic (thread) ID trong Forum group — None = gửi vào General
_topic_raw = _get("GROUP_TOPIC_ID", "")
GROUP_TOPIC_ID: int | None = int(_topic_raw) if _topic_raw else None

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

# --- Admin ---
_admin_raw = _get("ADMIN_IDS", "479445625,339028172")
ADMIN_IDS: set[int] = {int(x) for x in _admin_raw.split(",") if x.strip()}
PROMPTS_FILE: str = _get("PROMPTS_FILE", "prompts.json")
MAX_PROMPT_LENGTH: int = 4000

# --- Cấu hình thử thách ---
TOTAL_WEEKS: int = int(_get("TOTAL_WEEKS", "6"))
CHECKIN_POINTS: int = int(_get("CHECKIN_POINTS", "20"))
MAX_CHECKIN_POINTS: int = CHECKIN_POINTS * TOTAL_WEEKS  # Tổng điểm check-in tối đa
MAX_SHARES_PER_WEEK: int = int(_get("MAX_SHARES_PER_WEEK", "3"))  # Tối đa 3 lần share/tuần/team
# Ngày bắt đầu thử thách (YYYY-MM-DD, theo ICT). None = chưa cấu hình, bot dùng #week_N từ user.
CHALLENGE_START_DATE: str | None = _get("CHALLENGE_START_DATE")

# --- AWS S3 (lưu ảnh check-in) ---
AWS_ACCESS_KEY_ID: str | None = _get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY: str | None = _get("AWS_SECRET_ACCESS_KEY")
AWS_S3_BUCKET: str | None = _get("AWS_S3_BUCKET")
AWS_S3_REGION: str = _get("AWS_S3_REGION", "ap-southeast-1")
AWS_S3_ENDPOINT_URL: str | None = _get("AWS_S3_ENDPOINT_URL")  # API endpoint cho boto3 (không có bucket)
AWS_S3_PUBLIC_URL: str | None = _get("AWS_S3_PUBLIC_URL")       # Base URL public để tạo link (có thể khác endpoint)
USE_S3: bool = bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_S3_BUCKET)

# --- Tên tab trong Google Sheets ---
SHEET_TEAMS = "Teams"
SHEET_CHECKINS = "Checkins"
SHEET_SHARES = "Shares"
SHEET_LEADERBOARD = "Leaderboard"
