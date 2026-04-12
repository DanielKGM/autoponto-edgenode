import os
import cv2
import numpy as np

YUNET_MODEL_PATH = os.getenv("YUNET_MODEL_PATH", "/models/face_detection_yunet.onnx")
SFACE_MODEL_PATH = os.getenv("SFACE_MODEL_PATH", "/models/face_recognition_sface.onnx")
FACE_SCORE_THRESHOLD = float(os.getenv("FACE_SCORE_THRESHOLD", "0.85"))


class VisionPipeline:
    def __init__(self):
        self.detector = cv2.FaceDetectorYN.create(
            YUNET_MODEL_PATH,
            "",
            (240, 240),
            FACE_SCORE_THRESHOLD,
            0.3,
            5000,
        )
        self.recognizer = cv2.FaceRecognizerSF.create(
            SFACE_MODEL_PATH,
            "",
        )

    def decode_jpeg(self, frame_bytes: bytes) -> np.ndarray | None:
        try:
            np_buf = np.frombuffer(frame_bytes, dtype=np.uint8)
            return cv2.imdecode(np_buf, cv2.IMREAD_COLOR)
            
            if image is None:
                return None

            # optional fix
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)

        except Exception:
            return None

    def detect_best_face(self, image: np.ndarray):
        h, w = image.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(image)

        if faces is None or len(faces) == 0:
            return None

        faces = sorted(faces, key=lambda f: float(f[14]), reverse=True)
        return faces[0]

    def extract_embedding(self, image: np.ndarray, face) -> np.ndarray | None:
        try:
            aligned = self.recognizer.alignCrop(image, face)
            feat = self.recognizer.feature(aligned)
            return feat
        except Exception:
            return None

    def compare(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        return float(
            self.recognizer.match(
                feat1,
                feat2,
                cv2.FaceRecognizerSF_FR_COSINE,
            )
        )