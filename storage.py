"""
storage.py - Upload ảnh lên S3 (hoặc S3-compatible: FPT Cloud, Cloudflare R2, MinIO, v.v.).
"""
import logging
from datetime import datetime, timezone

import config

logger = logging.getLogger(__name__)

_s3_client = None


def _get_client():
    global _s3_client
    if _s3_client is None:
        import boto3
        from botocore.config import Config
        kwargs = {
            "aws_access_key_id": config.AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": config.AWS_SECRET_ACCESS_KEY,
            "region_name": config.AWS_S3_REGION,
            # path-style để tương thích S3-compatible (FPT Cloud, MinIO, v.v.)
            "config": Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        }
        if config.AWS_S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = config.AWS_S3_ENDPOINT_URL
        _s3_client = boto3.client("s3", **kwargs)
    return _s3_client


def _public_url(key: str) -> str:
    """Tạo URL public để truy cập file đã upload."""
    if config.AWS_S3_PUBLIC_URL:
        return f"{config.AWS_S3_PUBLIC_URL.rstrip('/')}/{key}"
    if config.AWS_S3_ENDPOINT_URL:
        return f"{config.AWS_S3_ENDPOINT_URL.rstrip('/')}/{config.AWS_S3_BUCKET}/{key}"
    return f"https://{config.AWS_S3_BUCKET}.s3.{config.AWS_S3_REGION}.amazonaws.com/{key}"


def upload_checkin_photo(photo_bytes: bytes, team_id: str, week: int) -> str | None:
    """Upload ảnh check-in lên S3, trả về URL public hoặc None nếu S3 chưa cấu hình / lỗi.

    Key: checkins/{team_id}/week{week}_{timestamp}.jpg
    """
    if not config.USE_S3:
        return None
    try:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        key = f"checkins/{team_id}/week{week}_{ts}.jpg"
        _get_client().put_object(
            Bucket=config.AWS_S3_BUCKET,
            Key=key,
            Body=photo_bytes,
            ContentType="image/jpeg",
        )
        url = _public_url(key)
        logger.info("Uploaded checkin photo: %s", url)
        return url
    except Exception as e:
        logger.error("S3 upload failed: %s", e)
        return None
