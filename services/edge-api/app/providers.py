from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from models import ScheduleEntry
import os

TZ = ZoneInfo(os.getenv("ZONE_INFO"))

DEVICE_LOCALE_MAP = {
    "9084CED6CDC0": "salateste",
}


def get_locale_id_for_device(device_id: str) -> str | None:
    return DEVICE_LOCALE_MAP.get(device_id)


def get_schedule_for_locale(locale_id: str) -> list[ScheduleEntry]:
    now = datetime.now(TZ)

    if locale_id == "salateste":
        start1 = now
        end1 = start1 + timedelta(minutes=2)

        start2 = end1 + timedelta(seconds=20)
        end2 = start2 + timedelta(minutes=4)

        return [
            ScheduleEntry(
                schedule_id="sched-1",
                locale_id=locale_id,
                lesson_name="Estrutura de Dados",
                starts_at=start1,
                ends_at=end1,
            ),
            ScheduleEntry(
                schedule_id="sched-2",
                locale_id=locale_id,
                lesson_name="Banco de Dados",
                starts_at=start2,
                ends_at=end2,
            ),
        ]

    return []
