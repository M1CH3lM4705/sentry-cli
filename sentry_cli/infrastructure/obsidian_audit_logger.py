"""
Adaptador de Infraestrutura: ObsidianAuditLogger implementando IAuditLogger.
Persiste histórico auditável de comandos e diagnósticos no cofre Obsidian.
"""

import asyncio
from pathlib import Path
from typing import Optional

from sentry_cli.domain.entities import SentryExecutionResult
from sentry_cli.domain.interfaces import IAuditLogger


class ObsidianAuditLogger(IAuditLogger):
    """
    Gravador de auditoria operacional do Sentry CLI no Segundo Cérebro (Obsidian).
    Garante rastreabilidade histórica e governança sobre operações no SO.
    """

    INITIAL_HEADER = (
        "---\n"
        "type: audit-log\n"
        "domain: ops\n"
        "tags:\n"
        "  - sentry/audit\n"
        "  - optron/auditoria\n"
        "  - homelab/debian\n"
        "---\n\n"
        "# Log de Auditoria Operacional do Sentry CLI\n"
        "Registro de comandos, diagnósticos e inspeções executados no servidor Homelab.\n\n"
    )

    @classmethod
    def get_default_audit_path(cls) -> Path:
        """Determina o caminho do arquivo de auditoria conforme o SO e ambiente."""
        import os
        import sys

        env_path = os.getenv("SENTRY_AUDIT_PATH")
        if env_path:
            return Path(env_path)

        if sys.platform == "win32":
            return Path.home() / ".sentry" / "audit.md"

        linux_vault = Path(
            "/mnt/umbrel-pool/personal-agent/vault/Personal Agent/Operações/Auditoria/sentry-cli-audit.md"
        )
        if linux_vault.parent.exists():
            return linux_vault
        return Path.home() / ".sentry" / "audit.md"

    def __init__(self, audit_file_path: Optional[Path] = None) -> None:
        self.audit_path = audit_file_path or self.get_default_audit_path()

    async def log_execution(self, result: SentryExecutionResult) -> None:
        """Grava a entrada de auditoria de forma assíncrona e não bloqueante."""
        await asyncio.to_thread(self._sync_append, result.to_audit_entry())

    def _sync_append(self, entry_text: str) -> None:
        """Executa gravação com criação defensiva de diretórios."""
        try:
            parent = self.audit_path.parent
            parent.mkdir(parents=True, exist_ok=True)

            if not self.audit_path.exists():
                self.audit_path.write_text(self.INITIAL_HEADER, encoding="utf-8")

            with open(self.audit_path, "a", encoding="utf-8") as f:
                f.write(entry_text + "\n")
        except Exception:
            # Operação defensiva fail-safe: falha no log do Obsidian não deve derrubar o CLI
            pass
