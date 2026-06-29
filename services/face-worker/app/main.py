import logging
import os
from datetime import datetime, timezone

from app.recognition_service import ServicoReconhecimento
from app.storage import ArmazenamentoRedis
from tcc_evidencias import registrar_tempo


def processar_frame(
    item: dict,
    armazenamento: ArmazenamentoRedis,
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
    espera_ms = _tempo_espera_processamento_ms(recebido_em)
    if espera_ms is not None:
        registrar_tempo(
            "frame_espera_processamento_ms",
            espera_ms,
            "face-worker",
            origem=dispositivo_codigo or dispositivo_id,
            detalhes={"aula_id": aula_id, "sala_id": sala_id},
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


def _tempo_espera_processamento_ms(recebido_em: str | None) -> float | None:
    if not recebido_em:
        return None
    try:
        recebido = datetime.fromisoformat(recebido_em.replace("Z", "+00:00"))
    except ValueError:
        return None
    if recebido.tzinfo is None:
        recebido = recebido.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - recebido).total_seconds() * 1000, 0.0)


def main():
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logger = logging.getLogger("face-worker")

    armazenamento = ArmazenamentoRedis()
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
