"""
Ponte de integração programática (Bridge) do subsistema Sentry CLI.
Permite ao OPTRON e seus handlers invocarem o motor operacional Sentry
com segurança, isolamento e auditoria em suas rotinas.
"""

import asyncio
import concurrent.futures
from typing import Any, Callable, Optional

from sentry_cli.application.execute_sentry_turn import ExecuteSentryTurnUseCase
from sentry_cli.application.inspect_homelab import InspectHomelabUseCase
from sentry_cli.application.interactive_session import InteractiveSessionUseCase
from sentry_cli.domain.entities import SentryExecutionResult
from sentry_cli.domain.interfaces import IAuditLogger, ICommandExecutor, ILLMProvider
from sentry_cli.domain.value_objects import ExecutionContext
from sentry_cli.infrastructure.async_bash_executor import AsyncBashExecutor
from sentry_cli.infrastructure.obsidian_audit_logger import ObsidianAuditLogger
from sentry_cli.infrastructure.ollama_provider import OllamaProvider


class SentryBridge:
    """
    Ponto de contato programático para o OPTRON consumir o subsistema SENTRY CLI.
    """

    def __init__(
        self,
        llm_provider: Optional[ILLMProvider] = None,
        executor: Optional[ICommandExecutor] = None,
        audit_logger: Optional[IAuditLogger] = None,
    ) -> None:
        self.llm = llm_provider or OllamaProvider()
        self.executor = executor or AsyncBashExecutor()
        self.logger = audit_logger or ObsidianAuditLogger()

        self.turn_use_case = ExecuteSentryTurnUseCase(
            self.llm, self.executor, self.logger
        )
        self.inspect_use_case = InspectHomelabUseCase(
            self.executor, self.logger, self.llm
        )

    async def execute_turn(
        self,
        query: str,
        dry_run: bool = False,
        timeout: float = 30.0,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> SentryExecutionResult:
        """Executa um turno operacional interpretado por IA de forma assíncrona."""
        context = ExecutionContext(dry_run=dry_run, timeout_seconds=timeout)
        return await self.turn_use_case.execute(query, context, on_status=on_status)

    async def inspect(
        self,
        component: str,
        dry_run: bool = False,
        timeout: float = 30.0,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> SentryExecutionResult:
        """Executa inspeção direcionada de componente de hardware/serviço."""
        context = ExecutionContext(dry_run=dry_run, timeout_seconds=timeout)
        return await self.inspect_use_case.execute(component, context, on_status=on_status)

    def create_interactive_session(
        self,
        dry_run: bool = False,
        timeout: float = 30.0,
        initial_context: Optional[ExecutionContext] = None,
    ) -> InteractiveSessionUseCase:
        """Cria e inicializa uma sessão interativa contínua do Sentry (REPL)."""
        ctx = initial_context or ExecutionContext(dry_run=dry_run, timeout_seconds=timeout)
        return InteractiveSessionUseCase(
            llm_provider=self.llm,
            executor=self.executor,
            audit_logger=self.logger,
            initial_context=ctx,
        )

    def execute_turn_sync(
        self,
        query: str,
        dry_run: bool = False,
        timeout: float = 30.0,
    ) -> SentryExecutionResult:
        """Executa um turno de forma síncrona com gerenciamento seguro de loop."""
        if self._is_loop_running():
            return self._run_in_executor(self.execute_turn, query, dry_run, timeout)
        return asyncio.run(self.execute_turn(query, dry_run, timeout))

    def inspect_sync(
        self,
        component: str,
        dry_run: bool = False,
        timeout: float = 30.0,
    ) -> SentryExecutionResult:
        """Executa inspeção síncrona com gerenciamento seguro de loop."""
        if self._is_loop_running():
            return self._run_in_executor(self.inspect, component, dry_run, timeout)
        return asyncio.run(self.inspect(component, dry_run, timeout))

    def _is_loop_running(self) -> bool:
        try:
            loop = asyncio.get_running_loop()
            return loop.is_running()
        except RuntimeError:
            return False

    def _run_in_executor(self, func: Any, *args: Any) -> Any:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, func(*args)).result()
