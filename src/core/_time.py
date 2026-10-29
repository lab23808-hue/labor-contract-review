"""schemas 内部共用的时间工具。统一使用带时区的 UTC 时间，避免 SQLite 存取时出现时区混乱。"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_aware(value: datetime) -> datetime:
    """字段校验用：拒绝不带时区的时间。"""
    if value.tzinfo is None:
        raise ValueError("时间必须带时区（统一使用 UTC）")
    return value
