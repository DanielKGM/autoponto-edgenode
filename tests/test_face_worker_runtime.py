from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
FACE_WORKER = ROOT / "services" / "face-worker"


def clear_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


def load_face_worker_module(monkeypatch, module_name: str):
    clear_app_modules()
    monkeypatch.syspath_prepend(str(FACE_WORKER))
    return importlib.import_module(module_name)


def test_decode_jpeg_rotates_frame_180_degrees(monkeypatch):
    vision_engine = load_face_worker_module(monkeypatch, "app.vision_engine")
    source = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)

    monkeypatch.setattr(
        vision_engine.cv2,
        "imdecode",
        lambda np_buf, flags: source.copy(),
    )

    engine = vision_engine.VisionEngine.__new__(vision_engine.VisionEngine)
    decoded = engine.decode_jpeg(b"fake-jpeg")

    expected = vision_engine.cv2.rotate(source, vision_engine.cv2.ROTATE_180)
    assert np.array_equal(decoded, expected)


def test_face_worker_has_no_mqtt_or_debug_frame_runtime():
    app_dir = FACE_WORKER / "app"
    main_source = (app_dir / "main.py").read_text()

    assert not (app_dir / "mqtt_client.py").exists()
    assert not (app_dir / "debug_frames.py").exists()
    assert "publish_result" not in main_source
    assert "build_mqtt_client" not in main_source
    assert "DebugFrameSaver" not in main_source
