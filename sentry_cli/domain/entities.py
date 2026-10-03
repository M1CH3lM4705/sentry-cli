"""
Entidades do domínio Sentry CLI.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sentry_cli.domain.value_objects import CommandExecutionResult, CommandStatement


@dataclass
class SentryExecutionResult:
    """
    Entidade raiz de agregação que representa o ciclo completo de um turno operacional do Sentry.
    """
    user_query: str
    command: Optional[CommandStatement]
    execution: Optional[CommandExecutionResult]
    llm_interpretation: str
    summary: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool = True

    def to_audit_entry(self) -> str:
        """Gera entrada estruturada em Markdown para auditoria no cofre Obsidian."""
        iso_time = self.timestamp.isoformat()
        status_label = "SUCESSO" if self.success else "FALHA"
        cmd_str = self.command.sanitized_str() if self.command else "Nenhum (Diagnóstico conversacional)"
        
        duration = f"{self.execution.duration_ms:.1f}ms" if self.execution else "N/A"
        exit_code = str(self.execution.exit_code) if self.execution else "N/A"
        output_snippet = self.execution.combined_output() if self.execution else "N/A"
        
        # Limita o snippet para não explodir o log de auditoria
        if len(output_snippet) > 500:
            output_snippet = output_snippet[:500] + "... [truncado para auditoria]"

        return (
            f"### [{status_label}] {iso_time}\n"
            f"- **Intenção do Operador:** {self.user_query}\n"
            f"- **Comando Executado:** `{cmd_str}`\n"
            f"- **Código de Saída:** {exit_code} (Duração: {duration})\n"
            f"- **Interpretação Sentry:** {self.llm_interpretation}\n"
            f"- **Síntese Operacional:** {self.summary}\n"
            f"- **Amostra de Saída:**\n"
            f"```text\n{output_snippet}\n```\n"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Converte a entidade em dicionário serializável."""
        return {
            "user_query": self.user_query,
            "command": self.command.sanitized_str() if self.command else None,
            "exit_code": self.execution.exit_code if self.execution else None,
            "duration_ms": self.execution.duration_ms if self.execution else None,
            "timed_out": self.execution.timed_out if self.execution else False,
            "output": self.execution.combined_output() if self.execution else None,
            "interpretation": self.llm_interpretation,
            "summary": self.summary,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
        }
