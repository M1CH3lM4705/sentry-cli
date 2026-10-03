"""
Configurações centralizadas e desacopladas do Sentry CLI.
Lê variáveis de ambiente com fallbacks defensivos e seguros para Linux e Windows.
"""

import os
import sys
from pathlib import Path


def get_ollama_base_url() -> str:
    """Retorna o endpoint base da API do Ollama."""
    default_url = "http://localhost:11434" if sys.platform == "win32" else "http://127.0.0.1:11434"
    return os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_API_URL", default_url))


def get_sentry_local_model() -> str:
    """Retorna o modelo Ollama padrão utilizado para inferência operacional."""
    return os.getenv("SENTRY_LOCAL_MODEL", "gemma4:e2b")


def get_default_audit_path() -> Path:
    """Determina o caminho padrão para auditoria imutável."""
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
