from datetime import datetime, timedelta, timezone

from immo_ne_collector.models import PropertyStatus


def compute_visibility_status(last_seen_at: datetime, inactive_after_days: int) -> str:
    now = datetime.now(timezone.utc)
    if last_seen_at < now - timedelta(days=inactive_after_days):
        return PropertyStatus.INACTIVE
    return PropertyStatus.ACTIVE


def detect_changed_fields(old: dict, new: dict, fields: tuple[str, ...]) -> list[str]:
    changed = []
    for field in fields:
        if old.get(field) != new.get(field):
            changed.append(field)
    return changed
