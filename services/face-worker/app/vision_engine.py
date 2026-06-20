import logging
import os

import cv2
import numpy as np

logger = logging.getLogger(__name__)

DETECT_MODEL_PATH = os.getenv("DETECT_MODEL_PATH")
RECOG_MODEL_PATH = os.getenv("RECOG_MODEL_PATH")
LIMIAR_DETECCAO_FACIAL = float(os.getenv("FACE_SCORE_THRESHOLD", "0.85"))


class VisionEngine:
    def __init__(self):
        self.detector = cv2.FaceDetectorYN.create(
            DETECT_MODEL_PATH,
            "",
            (240, 240),
            LIMIAR_DETECCAO_FACIAL,
            0.3,
            5000,
        )
        self.recognizer = cv2.FaceRecognizerSF.create(
            RECOG_MODEL_PATH,
            "",
        )

    def decodificar_jpeg(self, frame_bytes: bytes) -> np.ndarray | None:
        try:
            buffer_numpy = np.frombuffer(frame_bytes, dtype=np.uint8)
            imagem = cv2.imdecode(buffer_numpy, cv2.IMREAD_COLOR)

            if imagem is None:
                logger.warning("jpeg decode returned None")
                return None

            return cv2.rotate(imagem, cv2.ROTATE_180)
        except Exception as exc:
            logger.exception("failed to decode jpeg: %s", exc)
            return None

    def detectar_melhor_rosto(self, imagem: np.ndarray):
        try:
            altura, largura = imagem.shape[:2]
            self.detector.setInputSize((largura, altura))
            _, rostos = self.detector.detect(imagem)

            if rostos is None or len(rostos) == 0:
                return None

            return max(rostos, key=lambda rosto: float(rosto[14]))
        except Exception as exc:
            logger.exception("failed during face detection: %s", exc)
            return None

    def extrair_embedding(self, imagem: np.ndarray, rosto) -> np.ndarray | None:
        try:
            alinhado = self.recognizer.alignCrop(imagem, rosto)
            return self.recognizer.feature(alinhado)
        except Exception as exc:
            logger.exception("failed during embedding extraction: %s", exc)
            return None

    def comparar(self, embedding_1: np.ndarray, embedding_2: np.ndarray) -> float:
        return float(
            self.recognizer.match(
                embedding_1,
                embedding_2,
                cv2.FaceRecognizerSF_FR_COSINE,
            )
        )
