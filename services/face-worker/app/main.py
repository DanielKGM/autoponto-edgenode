import logging
import os

from app.recognition_service import ServicoReconhecimento
from app.storage import RedisRepo


def configurar_logs():
    nome_nivel = os.getenv("LOG_LEVEL", "INFO").upper()
    nivel = getattr(logging, nome_nivel, logging.INFO)

    logging.basicConfig(
        level=nivel,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def processar_frame(
    item: dict,
    armazenamento: RedisRepo,
    reconhecimento: ServicoReconhecimento,
    logger,
) -> bool:
    dispositivo_id = item["dispositivoId"]
    dispositivo_codigo = item.get("dispositivoCodigo")
    sala_id = item.get("salaId")
    aula_id = item.get("aulaId")
    recebido_em = item.get("receivedAt")
    frame_bytes = item["frame"]

    if not aula_id:
        logger.info(
            "frame ignored dispositivo=%s reason=missing_aula aula=%s",
            dispositivo_id,
            aula_id,
        )
        return False

    logger.info(
        "frame received dispositivo=%s sala=%s aula=%s bytes=%d receivedAt=%s",
        dispositivo_id,
        sala_id,
        aula_id,
        len(frame_bytes),
        recebido_em,
    )

    resultado = reconhecimento.reconhecer(frame_bytes, aula_id)
    if not resultado["ok"]:
        logger.info(
            "recognition failed dispositivo=%s reason=%s score=%s %s",
            dispositivo_id,
            resultado["reason"],
            resultado.get("score"),
            resultado.get("embeddingId"),
        )
        return False

    armazenamento.enfileirar_evento_presenca(
        dispositivo_id=dispositivo_id,
        dispositivo_codigo=dispositivo_codigo,
        aula_id=aula_id,
        aluno_id=resultado["alunoId"],
        score=resultado["score"],
    )
    logger.info(
        "recognition success queued_attendance dispositivo=%s aluno=%s embedding_id=%s score=%.4f",
        dispositivo_id,
        resultado["alunoId"],
        resultado.get("embeddingId"),
        resultado["score"],
    )
    return True


def main():
    configurar_logs()
    logger = logging.getLogger("face-worker")

    armazenamento = RedisRepo()
    reconhecimento = ServicoReconhecimento(armazenamento)

    logger.info("waiting for frames...")

    while True:
        try:
            item = armazenamento.buscar_frame_bloqueante()
            if not item:
                continue

            processar_frame(item, armazenamento, reconhecimento, logger)

        except Exception as exc:
            logger.exception("worker loop error: %s", exc)


if __name__ == "__main__":
    main()
