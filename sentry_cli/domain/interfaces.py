"""
Portas / Interfaces do domínio Sentry CLI (Arquitetura Hexagonal / Ports & Adapters).
Garante que casos de uso dependam apenas de abstrações.
"""

from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Tuple
from sentry_cli.domain.entities import SentryExecutionResult
from sentry_cli.domain.value_objects import (
    CommandExecutionResult,
    CommandStatement,
    ExecutionContext,
)


class ILLMProvider(ABC):
    """
    Porta de abstração para modelos de linguagem.
    Permite alternar entre Ollama local, Gemini, Claude, llama.cpp ou mocks
    sem qualquer alteração nos casos de uso.
    """

    @abstractmethod
    async def decide_action(
        self,
        user_intent: str,
        context: ExecutionContext,
        on_token: Optional[Callable[[int, str], None]] = None,
    ) -> Tuple[Optional[CommandStatement], str]:
        """
        Interpreta a intenção do operador e decide se é necessário executar um comando.
        Retorna (CommandStatement, explicacao/mensagem_direta).
        Se nenhum comando for necessário, retorna (None, resposta).
        """
        pass

    @abstractmethod
    async def synthesize_response(
        self,
        user_intent: str,
        command: CommandStatement,
        result: CommandExecutionResult,
        context: Optional[ExecutionContext] = None,
        on_token: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        """
        Sintetiza a saída da execução do comando em uma resposta executiva
        e amigável ao operador em português.
        """
        pass

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        on_token: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        """Processa um histórico de mensagens em modo conversacional puro."""
        pass


class ICommandExecutor(ABC):
    """
    Porta de abstração para execução de comandos de sistema operacional.
    Permite implementações reais assíncronas, executores restritos ou mocks de teste.
    """

    @abstractmethod
    async def execute(
        self, command: CommandStatement, context: ExecutionContext
    ) -> CommandExecutionResult:
        """Executa o comando no ambiente especificado com controle de timeout e saída."""
        pass


class IAuditLogger(ABC):
    """
    Porta de abstração para registro de auditoria.
    Permite registrar em arquivos do Obsidian, logs locais, banco ou consoles.
    """

    @abstractmethod
    async def log_execution(self, result: SentryExecutionResult) -> None:
        """Persiste o registro auditado de uma operação do Sentry."""
        pass
