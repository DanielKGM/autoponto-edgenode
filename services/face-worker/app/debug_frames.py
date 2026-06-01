import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_filename_part(value: str | None) -> str:
    if not value:
        return "unknown"
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in value)


class DebugFrameSaver:
    def __init__(
        self,
        enabled: bool | None = None,
        frames_dir: str | Path | None = None,
        max_frames: int | None = None,
    ):
        self.enabled = _env_bool("DEBUG_SAVE_FRAMES") if enabled is None else enabled
        self.frames_dir = Path(frames_dir or os.getenv("DEBUG_FRAMES_DIR", "/debug/frames"))
        self.max_frames = max_frames or int(os.getenv("DEBUG_MAX_FRAMES", "10"))
        self._counter = 0

    def save(self, device_id: str, lesson_id: str | None, frame_bytes: bytes) -> Path | None:
        if not self.enabled:
            return None

        try:
            self.frames_dir.mkdir(parents=True, exist_ok=True)
            self._counter += 1
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            filename = (
                f"{timestamp}_"
                f"{_safe_filename_part(device_id)}_"
                f"{_safe_filename_part(lesson_id)}_"
                f"{self._counter % 10000:04d}.jpg"
            )
            path = self.frames_dir / filename
            path.write_bytes(frame_bytes)
            self._prune()
            return path
        except Exception as exc:
            logger.warning("failed to save debug frame: %s", exc)
            return None

    def _prune(self) -> None:
        if self.max_frames < 1:
            return

        files = sorted(
            self.frames_dir.glob("*.jpg"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        for old_file in files[self.max_frames :]:
            old_file.unlink(missing_ok=True)
