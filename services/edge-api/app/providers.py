from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.models import ScheduleEntry
import os

TZ = ZoneInfo(os.getenv("ZONE_INFO"))


# temp mock DEVICEID:LOCALEID
DEVICE_LOCALE_MAP = {
    "ABC123": "salateste",
}

def get_locale_id_for_device(device_id: str) -> str | None:
    # TODO: get device/locale map from main API/cache
    return DEVICE_LOCALE_MAP.get(device_id)


def get_schedule_for_locale(locale_id: str) -> list[ScheduleEntry]:
    now = datetime.now(TZ)
    today = now.date()

    # temp mock
    # TODO: get schedule/locale map from main API/cache
    if locale_id == "salateste":
        return [
            ScheduleEntry(
                schedule_id="sched-1",
                locale_id=locale_id,
                lesson_name="Estrutura de Dados",
                starts_at = datetime.now(tz=TZ),
                ends_at = starts_at + timedelta(minutes=2)
            ),
            ScheduleEntry(
                schedule_id="sched-2",
                locale_id=locale_id,
                lesson_name="Banco de Dados",
                starts_at = datetime.now(tz=TZ) + timedelta(minutes=2, seconds=20),
                ends_at = starts_at + timedelta(minutes=4)
            ),
        ]

    return []