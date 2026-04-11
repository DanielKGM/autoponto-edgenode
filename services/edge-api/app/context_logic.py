from datetime import datetime
from zoneinfo import ZoneInfo
from app.models import DeviceContext, ScheduleEntry
import os

TZ = ZoneInfo(os.getenv("ZONE_INFO"))

def delta_to_ms(delta) -> int:
    return max(int(delta.total_seconds() * 1000), 0)

def compute_context(entries: list[ScheduleEntry]) -> DeviceContext:
    now = datetime.now(TZ)
    ordered = sorted(entries, key=lambda e: e.starts_at)

    current = None
    upcoming = None

    for entry in ordered:
        if entry.starts_at <= now < entry.ends_at:
            current = entry
            break
        if now < entry.starts_at:
            upcoming = entry
            break

    if current:
        return DeviceContext(
            lesson_name=current.lesson_name,
            ms_remaining=delta_to_ms(current.ends_at - now),
            ms_for_next=0,
        )

    if upcoming:
        return DeviceContext(
            lesson_name="",
            ms_remaining=0,
            ms_for_next=delta_to_ms(upcoming.starts_at - now),
        )

    return DeviceContext(
        lesson_name="",
        ms_remaining=0,
        ms_for_next=0,
    )