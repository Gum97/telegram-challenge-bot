"""
scoring.py - Chấm điểm bằng AI (OpenAI), kèm fallback heuristic để test local.
"""

import json
import logging
import os
import re
from dataclasses import dataclass

import config

logger = logging.getLogger(__name__)
client = None
if not config.USE_FAKE_AI:
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)


# ── Prompt management (file-based, no DB) ────────────────────────────────

def _load_prompts() -> dict:
    """Load custom prompts from JSON file."""
    if os.path.exists(config.PROMPTS_FILE):
        try:
            with open(config.PROMPTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load prompts file: %s", e)
    return {}


def _save_prompts(data: dict) -> None:
    """Save custom prompts to JSON file."""
    with open(config.PROMPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_prompt(key: str, default: str | None = None) -> str | None:
    """Get a prompt by key; returns default if not customized."""
    prompts = _load_prompts()
    return prompts.get(key, default)


def has_custom_prompt(key: str) -> bool:
    """Check if a prompt has been customized."""
    return key in _load_prompts()


def set_prompt(key: str, value: str) -> None:
    """Set a custom prompt (admin only, enforced by caller)."""
    prompts = _load_prompts()
    prompts[key] = value[:config.MAX_PROMPT_LENGTH]
    _save_prompts(prompts)


def reset_prompt(key: str) -> None:
    """Reset a prompt to default (remove custom override)."""
    prompts = _load_prompts()
    prompts.pop(key, None)
    _save_prompts(prompts)


def list_prompt_keys() -> list[str]:
    """List all available prompt keys."""
    return ["checkin", "sharing"]


@dataclass
class CheckinResult:
    valid: bool
    reason: str


@dataclass
class SharingResult:
    score: int
    category: int
    novelty: int
    practicality: int
    workflow_clarity: int
    feedback: str
    highlight: str


def _has_numeric_summary(text: str) -> bool:
    """Kiểm tra xem text có chứa tóm tắt số liệu cuộc họp không (ít nhất 2 dấu hiệu)."""
    numeric_hits = 0
    if re.search(r"\b\d+\b", text):
        numeric_hits += 1
    if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", text):
        numeric_hits += 1
    keywords = ["tham dự", "vắng", "vấn đề", "raised", "raise", "next action", "action", "tồn đọng",
                 "người", "thiếu", "resolved", "missing", "participants", "attended"]
    if any(k.lower() in text.lower() for k in keywords):
        numeric_hits += 1
    return numeric_hits >= 2


def _checkin_fallback(text: str) -> CheckinResult:
    """Chấm check-in bằng heuristic khi không có AI thật."""
    has_summary = _has_numeric_summary(text)
    if not has_summary:
        return CheckinResult(valid=False, reason="Thiếu số liệu tóm tắt cuộc họp (ngày, tham dự, vắng, vấn đề, action...)")
    return CheckinResult(valid=True, reason="Số liệu tóm tắt cuộc họp hợp lệ.")


CHECKIN_SYSTEM_PROMPT = """Bạn xác thực nội dung check-in họp tuần của một team trong cuộc thi AI Meeting Challenge.

Nội dung check-in là kết quả từ prompt tóm tắt cuộc họp trên NotebookLM, gồm 1 dòng số liệu ngắn gọn.

Yêu cầu để hợp lệ (tất cả đều phải có):
1. Ngày diễn ra cuộc họp
2. Số người tham dự
3. Số người vắng
4. Số vấn đề được raise lên trong cuộc họp
5. Số lượng next action trong cuộc họp
6. Tổng số action còn tồn đọng cộng dồn

Nếu thiếu bất kỳ mục nào, trả về valid=false và nêu rõ thiếu gì.
Trả về JSON duy nhất, không markdown: {"valid": bool, "reason": "<nhận xét ngắn tiếng Việt>"}"""


def score_checkin(message_text: str) -> CheckinResult:
    if config.USE_FAKE_AI:
        return _checkin_fallback(message_text)
    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            max_completion_tokens=256,
            timeout=15,
            messages=[
                {"role": "system", "content": get_prompt("checkin", CHECKIN_SYSTEM_PROMPT)},
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


def validate_notebooklm_photo(photo_bytes: bytes) -> CheckinResult:
    """Dùng AI vision để xác minh ảnh là screenshot NotebookLM hợp lệ."""
    if config.USE_FAKE_AI:
        return CheckinResult(valid=True, reason="Ảnh đã được ghi nhận (chế độ test).")
    import base64
    try:
        b64 = base64.b64encode(photo_bytes).decode()
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            max_completion_tokens=256,
            timeout=20,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Bạn kiểm tra ảnh chụp màn hình. "
                        "Xác định xem đây có phải ảnh chụp từ NotebookLM (Google) không — "
                        "thường có giao diện Audio Overview, Notebook Guide, Sources panel, "
                        "hoặc chat interface của NotebookLM (notebook.google.com). "
                        'Trả về JSON duy nhất, không markdown: {"valid": bool, "reason": "<giải thích ngắn tiếng Việt>"}'
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"},
                        },
                        {"type": "text", "text": "Đây có phải ảnh chụp màn hình NotebookLM không?"},
                    ],
                },
            ],
        )
        if not response.choices:
            raise RuntimeError("AI returned empty response")
        raw = re.sub(r"^```json\s*|```$", "", response.choices[0].message.content.strip(), flags=re.MULTILINE).strip()
        data = json.loads(raw)
        return CheckinResult(valid=bool(data["valid"]), reason=data.get("reason", ""))
    except Exception as e:
        logger.error("validate_notebooklm_photo error: %s", e)
        # Nếu AI lỗi → không block user
        return CheckinResult(valid=True, reason="Không thể xác minh ảnh tự động, đã ghi nhận.")


SHARING_SYSTEM_PROMPT = """Bạn là giám khảo cuộc thi "AI Meeting Workflow Challenge".
Chấm bài dự thi viết dạng Markdown (tối thiểu 100 từ) về cách ứng dụng AI vào công việc thực tế.

BÀI DỰ THI thuộc 1 trong 3 nhóm, có TRỌNG SỐ từ cao tới thấp:
  Nhóm 1 (cao nhất): Đề xuất Quy trình họp Team hiệu quả với AI
  Nhóm 2 (trung bình): Chia sẻ quy trình cá nhân/team/phòng ban đã/đang/sắp dùng AI để tối ưu hiệu suất
  Nhóm 3 (thấp nhất): Chia sẻ, nhận xét, đánh giá về tin tức/sự kiện AI trên mạng

Hãy xác định bài thuộc nhóm nào và áp dụng trọng số tương ứng.

YÊU CẦU BÀI VIẾT:
- Có raise vấn đề rõ ràng
- Có lập luận logic
- Có ví dụ minh hoạ
Nếu thiếu 1 trong 3 yếu tố trên, trừ điểm tương ứng và ghi rõ trong feedback.

TIÊU CHÍ CHẤM ĐIỂM (tổng tối đa 80):

1. novelty (0-26): Tính mới / sáng tạo
   - 20-26: Cách dùng AI độc đáo, chưa phổ biến, có twist riêng
   - 12-19: Có ý tưởng hay nhưng khá phổ biến
   - 0-11: Quá generic, ai cũng biết, không có gì mới

2. practicality (0-27): Tính thực tế / áp dụng được
   - 20-27: Có kết quả đo lường cụ thể (số liệu trước/sau), đã áp dụng thực tế
   - 12-19: Có thể áp dụng nhưng thiếu số liệu hoặc chưa thử thực tế
   - 0-11: Lý thuyết suông, không rõ áp dụng thế nào

3. workflow_clarity (0-27): Độ rõ ràng workflow
   - 20-27: Mô tả rõ từng bước: input → tool/prompt → output, người khác có thể làm theo
   - 12-19: Có mô tả nhưng thiếu chi tiết, khó reproduce
   - 0-11: Mơ hồ, không rõ quy trình

TRỌNG SỐ NHÓM:
- Nhóm 1: Chấm đúng thang điểm (tối đa 80)
- Nhóm 2: Giảm nhẹ 5-10% so với bài cùng chất lượng ở Nhóm 1
- Nhóm 3: Giảm 15-25% so với bài cùng chất lượng ở Nhóm 1

OUTPUT: Trả về JSON duy nhất, không markdown:
{
  "category": <1|2|3>,
  "novelty": <int>,
  "practicality": <int>,
  "workflow_clarity": <int>,
  "score": <int tổng 3 tiêu chí, tối đa 80>,
  "feedback": "<nhận xét 2-3 câu bằng tiếng Việt, gợi ý cải thiện>",
  "highlight": "<1 câu tóm tắt điểm nổi bật nhất của bài, KHÔNG trích dẫn nội dung gốc>"
}"""


DUPLICATE_SYSTEM_PROMPT = """Bạn kiểm tra xem bài mới có trùng chủ đề AI với các bài đã nộp tuần này không.
Trùng chủ đề = cùng vấn đề / use-case AI (ví dụ: đều dùng AI viết test, đều dùng AI tóm tắt meeting...).
Khác chủ đề = vấn đề khác nhau dù cùng tool (ví dụ: AI viết test vs AI phân tích dữ liệu).
Trả về JSON duy nhất: {"is_duplicate": bool, "reason": "<giải thích ngắn gọn bằng tiếng Việt>"}"""


def is_duplicate_topic(new_content: str, previous_contents: list[str]) -> tuple[bool, str]:
    """Kiểm tra bài mới có trùng chủ đề AI với các bài đã nộp tuần này không.
    Trả về (is_duplicate, reason).
    """
    if not previous_contents:
        return False, ""

    if config.USE_FAKE_AI:
        # Heuristic: kiểm tra overlap keyword đơn giản
        new_words = set(re.findall(r"\w+", new_content.lower()))
        for prev in previous_contents:
            prev_words = set(re.findall(r"\w+", prev.lower()))
            overlap = len(new_words & prev_words) / max(len(new_words | prev_words), 1)
            if overlap > 0.6:
                return True, "Bài mới có nội dung rất giống bài đã nộp (chế độ test)."
        return False, ""

    prev_summary = "\n---\n".join(
        f"Bài {i+1}: {c[:400]}" for i, c in enumerate(previous_contents)
    )
    user_msg = f"Các bài đã nộp tuần này:\n{prev_summary}\n\n---\nBài mới:\n{new_content[:400]}"
    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            max_completion_tokens=128,
            timeout=15,
            messages=[
                {"role": "system", "content": DUPLICATE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        if not response.choices:
            return False, ""
        raw = re.sub(r"^```json\s*|```$", "", response.choices[0].message.content.strip(), flags=re.MULTILINE).strip()
        data = json.loads(raw)
        return bool(data["is_duplicate"]), data.get("reason", "")
    except Exception as e:
        logger.error("is_duplicate_topic error: %s", e)
        return False, ""  # Nếu lỗi → cho phép qua để không block user


def score_sharing(post_content: str) -> SharingResult:
    if config.USE_FAKE_AI:
        length = len(post_content)
        novelty = min(26, max(8, length // 50))
        practicality = min(27, 16 if any(k in post_content.lower() for k in ["workflow", "quy trình", "team", "ai", "meeting", "task"]) else 10)
        workflow = min(27, 18 if any(k in post_content.lower() for k in ["bước", "step", "1.", "2.", "3."]) else 12)
        score = min(80, novelty + practicality + workflow)
        return SharingResult(score=score, category=2, novelty=novelty, practicality=practicality, workflow_clarity=workflow, feedback="Test mode: cần AI thật để chấm chính xác hơn.", highlight="Bài dự thi đã được chấm ở chế độ test.")
    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            max_completion_tokens=512,
            timeout=30,
            messages=[
                {"role": "system", "content": get_prompt("sharing", SHARING_SYSTEM_PROMPT)},
                {"role": "user", "content": post_content},
            ],
        )
        if not response.choices:
            raise RuntimeError("AI returned empty response")
        raw = re.sub(r"^```json\s*|```$", "", response.choices[0].message.content.strip(), flags=re.MULTILINE).strip()
        data = json.loads(raw)
        return SharingResult(score=min(80, int(data["score"])), category=int(data.get("category", 2)), novelty=int(data["novelty"]), practicality=int(data["practicality"]), workflow_clarity=int(data["workflow_clarity"]), feedback=data["feedback"], highlight=data["highlight"])
    except Exception as e:
        logger.error("score_sharing error: %s", e)
        raise RuntimeError(f"AI scoring failed: {e}") from e
