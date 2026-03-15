"""
scoring.py - Chấm điểm bằng AI (Anthropic Claude), kèm fallback heuristic để test local.
"""

import json
import logging
import re
from dataclasses import dataclass

import config

logger = logging.getLogger(__name__)
client = None
if not config.USE_FAKE_AI:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


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
    has_team = bool(re.search(r"#team_[a-z0-9_]+", text, re.IGNORECASE))
    has_week = bool(re.search(r"#week_(\d+)", text, re.IGNORECASE))
    has_summary = _has_numeric_summary(text)
    missing = []
    if not has_post: missing.append("#post")
    if not has_team: missing.append("#team_<tên_team>")
    if not has_week: missing.append("#week_<số>")
    if not has_summary: missing.append("tóm tắt số liệu")
    return CheckinResult(valid=not missing, reason=("Hashtag và số liệu hợp lệ." if not missing else f"Thiếu hoặc không đầy đủ: {', '.join(missing)}"))


def score_checkin(message_text: str) -> CheckinResult:
    if config.USE_FAKE_AI:
        return _checkin_fallback(message_text)
    try:
        response = client.messages.create(model=config.ANTHROPIC_MODEL, max_tokens=256, system='Validate checkin and return JSON {"valid":bool,"reason":string}. Require #post #team_<name> #week_<x> and numeric summary. Screenshot is checked separately.', messages=[{"role":"user","content":message_text}])
        raw = re.sub(r"^```json\s*|```$", "", response.content[0].text.strip(), flags=re.MULTILINE).strip()
        data = json.loads(raw)
        return CheckinResult(valid=bool(data["valid"]), reason=data.get("reason", ""))
    except Exception as e:
        logger.error("score_checkin error: %s", e)
        return _checkin_fallback(message_text)


def score_sharing(post_content: str) -> SharingResult:
    if config.USE_FAKE_AI:
        length = len(post_content)
        novelty = min(33, max(10, length // 40))
        practicality = 20 if any(k in post_content.lower() for k in ["workflow", "quy trình", "team", "ai", "meeting", "task"]) else 12
        workflow = 22 if any(k in post_content.lower() for k in ["bước", "step", "1.", "2.", "3."]) else 15
        score = min(100, novelty + practicality + workflow)
        return SharingResult(score=score, novelty=novelty, practicality=practicality, workflow_clarity=workflow, feedback="Test mode scoring: bài có ý rõ và có thể áp dụng, nhưng cần AI thật để chấm chính xác hơn.", highlight="Bài sharing đã được chấm ở chế độ test local.")
    try:
        response = client.messages.create(model=config.ANTHROPIC_MODEL, max_tokens=512, system='Score sharing post and return JSON with novelty, practicality, workflow_clarity, score, feedback, highlight.', messages=[{"role":"user","content":post_content}])
        raw = re.sub(r"^```json\s*|```$", "", response.content[0].text.strip(), flags=re.MULTILINE).strip()
        data = json.loads(raw)
        return SharingResult(score=int(data["score"]), novelty=int(data["novelty"]), practicality=int(data["practicality"]), workflow_clarity=int(data["workflow_clarity"]), feedback=data["feedback"], highlight=data["highlight"])
    except Exception as e:
        logger.error("score_sharing error: %s", e)
        raise RuntimeError(f"AI scoring failed: {e}") from e
