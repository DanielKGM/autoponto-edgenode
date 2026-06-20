from dataclasses import dataclass


@dataclass(frozen=True)
class ContextoDispositivo:
    aula_nome: str
    ms_remaining: int
    ms_for_next: int
    aula_id: str | None = None
    sala_id: str | None = None

    def para_payload(self) -> dict:
        return {
            "lesson_name": self.aula_nome,
            "msRemaining": self.ms_remaining,
            "msForNext": self.ms_for_next,
        }
