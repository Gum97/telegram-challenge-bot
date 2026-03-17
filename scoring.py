"""
scoring.py - Chấm điểm bằng AI (OpenAI), kèm fallback heuristic để test local.
"""

import json
import logging
import re
from dataclasses import dataclass

import config

logger = logging.getLogger(__name__)
client = None
if not config.USE_FAKE_AI:
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)


@dataclass
class CheckinResult:
    valid: bool
    reason: str


@dataclass
class SharingResult:
    score: int
    novelty: int
    practicality: int
    workflow_clarity: int
    feedback: str
    highlight: str


def _has_numeric_summary(text: str) -> bool:
    """Kiểm tra xem text có chứa tóm tắt bằng số liệu không (ít nhất 2 dấu hiệu)."""
    numeric_hits = 0
    if re.search(r"\b\d+\b", text):
        numeric_hits += 1
    if re.search(r"\b\d+\s*/\s*\d+\b", text):
        numeric_hits += 1
    keywords = ["người", "thiếu", "vấn đề", "resolved", "missing", "participants", "attended", "open issues", "new issues", "tồn", "phát sinh"]
    if any(k.lower() in text.lower() for k in keywords):
        numeric_hits += 1
    return numeric_hits >= 2


def _checkin_fallback(text: str) -> CheckinResult:
    """Chấm check-in bằng heuristic khi không có AI thật."""
    has_post = bool(re.search(r"#post\b", text, re.IGNORECASE))
    has_week = bool(re.search(r"#week_(\d+)", text, re.IGNORECASE))
    has_summary = _has_numeric_summary(text)
    missing = []
    if not has_post: missing.append("#post")
    if not has_week: missing.append("#week_<số>")
    if not has_summary: missing.append("tóm tắt số liệu")
    return CheckinResult(valid=not missing, reason=("Hashtag và số liệu hợp lệ." if not missing else f"Thiếu hoặc không đầy đủ: {', '.join(missing)}"))


def score_checkin(message_text: str) -> CheckinResult:
    if config.USE_FAKE_AI:
        return _checkin_fallback(message_text)
    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            max_completion_tokens=256,
            timeout=15,
            messages=[
                {"role": "system", "content": 'Validate checkin and return JSON {"valid":bool,"reason":string}. Require #post #week_<x> and numeric summary. Screenshot is checked separately.'},
                {"role": "user", "content": message_text},
            ],
        )
        if not response.choices:
            raise RuntimeError("AI returned empty response")
        raw = re.sub(r"^```json\s*|```$", "", response.choices[0].message.content.strip(), flags=re.MULTILINE).strip()
        data = json.loads(raw)
        return CheckinResult(valid=bool(data["valid"]), reason=data.get("reason", ""))
    except Exception as e:
        logger.error("score_checkin error: %s", e)
        return _checkin_fallback(message_text)


SHARING_SYSTEM_PROMPT = """Bạn là giám khảo cuộc thi "AI Meeting Workflow Challenge".
Chấm bài chia sẻ về cách ứng dụng AI vào công việc thực tế.

TIÊU CHÍ CHẤM ĐIỂM (tổng 100):

1. novelty (0-33): Tính mới / sáng tạo
   - 25-33: Cách dùng AI độc đáo, chưa phổ biến, có twist riêng
   - 15-24: Có ý tưởng hay nhưng khá phổ biến (dùng ChatGPT viết email, tóm tắt...)
   - 0-14: Quá generic, ai cũng biết, không có gì mới

2. practicality (0-33): Tính thực tế / áp dụng được
   - 25-33: Có kết quả đo lường cụ thể (số liệu trước/sau), team đã áp dụng thực tế
   - 15-24: Có thể áp dụng nhưng thiếu số liệu hoặc chưa thử thực tế
   - 0-14: Lý thuyết suông, không rõ áp dụng thế nào

3. workflow_clarity (0-34): Độ rõ ràng workflow
   - 25-34: Mô tả rõ từng bước: input → tool/prompt → output, người khác có thể làm theo
   - 15-24: Có mô tả nhưng thiếu chi tiết, khó reproduce
   - 0-14: Mơ hồ, không rõ quy trình

OUTPUT: Trả về JSON duy nhất, không markdown:
{
  "novelty": <int>,
  "practicality": <int>,
  "workflow_clarity": <int>,
  "score": <int tổng 3 tiêu chí>,
  "feedback": "<nhận xét 2-3 câu bằng tiếng Việt, gợi ý cải thiện>",
  "highlight": "<1 câu tóm tắt điểm nổi bật nhất của bài, KHÔNG trích dẫn nội dung gốc>"
}"""


def score_sharing(post_content: str) -> SharingResult:
    if config.USE_FAKE_AI:
        length = len(post_content)
        novelty = min(33, max(10, length // 40))
        practicality = 20 if any(k in post_content.lower() for k in ["workflow", "quy trình", "team", "ai", "meeting", "task"]) else 12
        workflow = 22 if any(k in post_content.lower() for k in ["bước", "step", "1.", "2.", "3."]) else 15
        score = min(100, novelty + practicality + workflow)
        return SharingResult(score=score, novelty=novelty, practicality=practicality, workflow_clarity=workflow, feedback="Test mode: cần AI thật để chấm chính xác hơn.", highlight="Bài sharing đã được chấm ở chế độ test.")
    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            max_completion_tokens=512,
            timeout=30,
            messages=[
                {"role": "system", "content": SHARING_SYSTEM_PROMPT},
                {"role": "user", "content": post_content},
            ],
        )
        if not response.choices:
            raise RuntimeError("AI returned empty response")
        raw = re.sub(r"^```json\s*|```$", "", response.choices[0].message.content.strip(), flags=re.MULTILINE).strip()
        data = json.loads(raw)
        return SharingResult(score=int(data["score"]), novelty=int(data["novelty"]), practicality=int(data["practicality"]), workflow_clarity=int(data["workflow_clarity"]), feedback=data["feedback"], highlight=data["highlight"])
    except Exception as e:
        logger.error("score_sharing error: %s", e)
        raise RuntimeError(f"AI scoring failed: {e}") from e
