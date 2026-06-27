import argparse
import asyncio
import logging

from app.config import AUTOPONTO_API_TOKEN, AUTOPONTO_API_URL, NODE_UUID
from app.face_embeddings import preparar_cache_redis_com_embeddings_descriptografados
from app.mqtt import publicar_fetch_dispositivos
from app.redis_store import (
    marcar_eventos_presenca_sincronizados,
    obter_eventos_presenca_pendentes,
    podar_eventos_presenca_sincronizados,
    substituir_snapshot_redis,
)

logger = logging.getLogger(__name__)


def _cabecalhos_autenticacao() -> dict[str, str]:
    cabecalhos = {"X-Node-Id": NODE_UUID}
    if AUTOPONTO_API_TOKEN:
        cabecalhos["Authorization"] = f"NodeToken {AUTOPONTO_API_TOKEN}"
    return cabecalhos


def _validar_resposta_http(resposta, operacao: str) -> None:
    try:
        resposta.raise_for_status()
    except Exception:
        corpo = getattr(resposta, "text", "")
        if len(corpo) > 1000:
            corpo = f"{corpo[:1000]}..."
        logger.warning(
            "sync %s failed status=%s body=%s",
            operacao,
            getattr(resposta, "status_code", "unknown"),
            corpo,
        )
        raise


def _codigos_dispositivos_do_cache(cache_redis: dict) -> list[str]:
    dispositivos = cache_redis.get("dispositivos_por_codigo", {})
    if not isinstance(dispositivos, dict):
        return []

    codigos = []
    vistos = set()
    for chave, registro in dispositivos.items():
        codigo = str(chave).strip() if chave is not None else ""
        if not codigo and isinstance(registro, dict):
            codigo = str(registro.get("dispositivo_codigo", "")).strip()
        if not codigo or codigo in vistos:
            continue
        vistos.add(codigo)
        codigos.append(codigo)
    return codigos


def aplicar_payload_sincronizacao(payload: dict) -> list[str]:
    cache_redis = payload.get("cache_redis")
    snapshot_data = payload.get("snapshot_data")
    synced_at = payload.get("synced_at")

    if not isinstance(cache_redis, dict):
        raise ValueError("payload de sincronizacao sem cache_redis")
    if not snapshot_data:
        raise ValueError("payload de sincronizacao sem snapshot_data")
    if not synced_at:
        raise ValueError("payload de sincronizacao sem synced_at")

    dispositivo_codigos = _codigos_dispositivos_do_cache(cache_redis)
    cache_redis = preparar_cache_redis_com_embeddings_descriptografados(cache_redis)
    substituir_snapshot_redis(cache_redis, str(snapshot_data), str(synced_at))
    return dispositivo_codigos


def publicar_fetch_apos_sync(dispositivo_codigos: list[str]) -> None:
    try:
        enviados = publicar_fetch_dispositivos(dispositivo_codigos)
        if enviados:
            logger.info("fetch mqtt publicado para %d dispositivos", enviados)
    except Exception as exc:
        logger.warning(
            "fetch mqtt pos-sync falhou dispositivos=%d error=%s",
            len(dispositivo_codigos),
            exc,
        )


async def sincronizar_presencas_pendentes(ids: list[str] | None = None) -> bool:
    if not AUTOPONTO_API_URL:
        return False

    presencas = obter_eventos_presenca_pendentes(ids)
    if not presencas:
        podar_eventos_presenca_sincronizados()
        return True

    import httpx

    try:
        async with httpx.AsyncClient(timeout=20) as cliente:
            resposta = await cliente.post(
                f"{AUTOPONTO_API_URL}/edge/attendance/",
                headers=_cabecalhos_autenticacao(),
                json={
                    "node_id": NODE_UUID,
                    "eventos": [
                        {
                            "id": presenca["id"],
                            "aluno_id": presenca["aluno_id"],
                            "aula_id": presenca["aula_id"],
                            "dispositivo_id": presenca["dispositivo_id"],
                            "reconhecido_em": presenca["reconhecido_em"],
                            "score": presenca["score"],
                        }
                        for presenca in presencas
                    ],
                },
            )
            _validar_resposta_http(resposta, "attendance push")
            ids_sincronizados = resposta.json().get(
                "synced_ids",
                [presenca["id"] for presenca in presencas],
            )
            marcar_eventos_presenca_sincronizados(ids_sincronizados)
            return True
    except Exception as exc:
        logger.warning("attendance immediate sync failed error=%s", exc)
        return False


async def executar_sincronizacao(
    enviar_presencas: bool = True,
) -> None:
    if not AUTOPONTO_API_URL:
        return

    import httpx

    async with httpx.AsyncClient(timeout=20) as cliente:
        resposta_pull = await cliente.get(
            f"{AUTOPONTO_API_URL}/edge/pull/",
            headers=_cabecalhos_autenticacao(),
            params={"node_id": NODE_UUID},
        )
        _validar_resposta_http(resposta_pull, "pull")

        payload = resposta_pull.json()

        logger.info(
            "payload recebido na sincronizacao=%s",
            payload,
        )

        dispositivo_codigos = aplicar_payload_sincronizacao(payload)
        publicar_fetch_apos_sync(dispositivo_codigos)

        if enviar_presencas:
            await sincronizar_presencas_pendentes()


def main() -> None:
    parser = argparse.ArgumentParser(description="Executa uma sincronizacao AutoPonto.")
    parser.add_argument(
        "--sem-presencas",
        action="store_true",
        help="nao envia presencas pendentes neste ciclo",
    )
    argumentos = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    asyncio.run(
        executar_sincronizacao(
            enviar_presencas=not argumentos.sem_presencas,
        )
    )


if __name__ == "__main__":
    main()
