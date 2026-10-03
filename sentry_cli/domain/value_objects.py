"""
Value Objects do domínio Sentry CLI.
Implementam encapsulamento estrito de primitivos, imutabilidade e validação de invariantes.
"""

from dataclasses import dataclass, field, replace
import re
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


class SecurityViolationError(ValueError):
    """Exceção levantada quando uma declaração de comando viola políticas de segurança defensiva."""
    pass


@dataclass(frozen=True)
class CommandStatement:
    """
    Value Object que encapsula um comando de shell a ser executado no Homelab.
    Garante sanitização preliminar contra comandos catastróficos.
    """
    raw_command: str

    # Padrões bloqueados por segurança defensiva
    _DISALLOWED_PATTERNS = (
        r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+(/|/\*|\$HOME|\~)",
        r":\(\)\s*\{\s*:\|:&\s*\};:",  # Fork bomb
        r"mkfs(\.[a-zA-Z0-9]+)?\s+/dev/sd[a-z]",
        r"dd\s+if=.*\s+of=/dev/sd[a-z]",
        r">\s*/dev/sd[a-z]",
        r">\s*/dev/nvme[0-9]",
    )

    def __post_init__(self) -> None:
        if not self.raw_command or not self.raw_command.strip():
            raise ValueError("O comando de shell não pode ser vazio.")
        
        normalized = self.raw_command.strip()
        for pattern in self._DISALLOWED_PATTERNS:
            if re.search(pattern, normalized, re.IGNORECASE):
                raise SecurityViolationError(
                    f"Comando rejeitado por violar políticas de segurança defensiva: '{normalized}'"
                )

    def sanitized_str(self) -> str:
        """Retorna o comando limpo de espaços laterais supérfluos."""
        return self.raw_command.strip()

    def __str__(self) -> str:
        return self.sanitized_str()


@dataclass(frozen=True)
class ExecutionContext:
    """
    Value Object que define o contexto de execução de um comando ou sessão interativa.
    Implementa gestão estrita de janela deslizante (sliding window) para evitar
    degradação de latência na CPU legada (AMD FX-6300).
    """
    user: str = "homelab"
    working_directory: str = "/mnt/umbrel-pool/personal-agent"
    timeout_seconds: float = 30.0
    max_output_length: int = 4000
    dry_run: bool = False
    environment: Optional[Mapping[str, str]] = None
    history: Tuple[Dict[str, str], ...] = ()
    max_history_turns: int = 6
    system_prompt: Optional[str] = None

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("O timeout de execução deve ser estritamente positivo.")
        if self.max_output_length <= 0:
            raise ValueError("O limite de saída (max_output_length) deve ser estritamente positivo.")
        if self.max_history_turns <= 0:
            raise ValueError("O limite de turnos de histórico (max_history_turns) deve ser estritamente positivo.")

    @staticmethod
    def truncate_lines(text: str, max_lines: int = 15) -> str:
        """
        Trunca cirurgicamente a saída de texto do comando em no máximo `max_lines` linhas.
        Inclui indicador visual explícito se a saída exceder o limite.
        """
        if not text:
            return ""
        lines = text.strip().splitlines()
        if len(lines) <= max_lines:
            return text.strip()
        truncated = "\n".join(lines[:max_lines])
        marker = f"[... saída truncada: exibindo primeiras {max_lines} linhas ...]"
        return f"{truncated}\n{marker}"

    def get_sliding_history(self) -> List[Dict[str, str]]:
        """
        Retorna as mensagens retidas no buffer aplicando a janela deslizante de
        no máximo `max_history_turns` turnos (mensagens), preservando a integridade do contexto.
        """
        if not self.history:
            return []
        return [dict(msg) for msg in self.history[-self.max_history_turns:]]

    def with_turn(self, role: str, content: str) -> "ExecutionContext":
        """
        Retorna uma nova instância imutável de ExecutionContext contendo o novo turno,
        já aplicando a janela deslizante de turnos para conter uso de tokens e latência.
        """
        new_history = list(self.history)
        new_history.append({"role": role, "content": content})
        if len(new_history) > self.max_history_turns:
            new_history = new_history[-self.max_history_turns:]
        return replace(self, history=tuple(new_history))

    def clear_history(self) -> "ExecutionContext":
        """Retorna uma nova instância com o buffer de histórico da sessão esvaziado."""
        return replace(self, history=())


@dataclass(frozen=True)
class CommandExecutionResult:
    """
    Value Object que representa o resultado imutável da execução de um comando no SO.
    """
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False

    def is_success(self) -> bool:
        """Verifica se o comando concluiu com sucesso e sem estourar timeout."""
        return self.exit_code == 0 and not self.timed_out

    def combined_output(self) -> str:
        """Combina stdout e stderr preservando clareza de contexto."""
        out = self.stdout.strip()
        err = self.stderr.strip()
        if not out and not err:
            return "(Sem saída de texto gerada pelo comando)"
        if out and err:
            return f"{out}\n[STDERR]: {err}"
        if out:
            return out
        return f"[STDERR]: {err}"
