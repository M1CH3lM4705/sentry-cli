"""
Caso de uso: Execução de um turno operacional do Sentry.
Coordena raciocínio do LLM, execução defensiva e auditoria em arquitetura limpa.
"""

from typing import Callable, Optional
from sentry_cli.domain.entities import SentryExecutionResult
from sentry_cli.domain.interfaces import IAuditLogger, ICommandExecutor, ILLMProvider
from sentry_cli.domain.value_objects import (
    CommandExecutionResult,
    CommandStatement,
    ExecutionContext,
)


class ExecuteSentryTurnUseCase:
    """
    Orquestra o ciclo: Intenção -> Decisão do LLM -> Execução Segura -> Síntese -> Auditoria.
    Segue Object Calisthenics: indentação única, sem 'else', guard clauses.
    """

    def __init__(
        self,
        llm_provider: ILLMProvider,
        executor: ICommandExecutor,
        audit_logger: IAuditLogger,
    ) -> None:
        self._llm = llm_provider
        self._executor = executor
        self._logger = audit_logger

    async def execute(
        self,
        user_query: str,
        context: Optional[ExecutionContext] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> SentryExecutionResult:
        """Executa um turno completo de diagnóstico ou comando com auditoria."""
        ctx = context or ExecutionContext()

        if on_status:
            on_status("Planejando ação...")

        def on_decide_token(count: int, chunk: str) -> None:
            if on_status:
                on_status(f"Planejando ação... [{count} tokens]")

        command, interpretation = await self._llm.decide_action(
            user_query, ctx, on_token=on_decide_token if on_status else None
        )

        if command is None:
            return await self._handle_conversational_turn(user_query, interpretation)

        if ctx.dry_run:
            return await self._handle_dry_run_turn(user_query, command, interpretation)

        return await self._handle_execution_turn(
            user_query, command, interpretation, ctx, on_status=on_status
        )

    async def _handle_conversational_turn(
        self, user_query: str, interpretation: str
    ) -> SentryExecutionResult:
        result = SentryExecutionResult(
            user_query=user_query,
            command=None,
            execution=None,
            llm_interpretation=interpretation,
            summary=interpretation,
            success=True,
        )
        await self._logger.log_execution(result)
        return result

    async def _handle_dry_run_turn(
        self,
        user_query: str,
        command: CommandStatement,
        interpretation: str,
    ) -> SentryExecutionResult:
        simulated_execution = CommandExecutionResult(
            exit_code=0,
            stdout=f"[DRY-RUN]: O comando `{command.sanitized_str()}` foi planejado mas não executado.",
            stderr="",
            duration_ms=0.0,
            timed_out=False,
        )
        result = SentryExecutionResult(
            user_query=user_query,
            command=command,
            execution=simulated_execution,
            llm_interpretation=interpretation,
            summary=f"Plano em simulação: comando `{command.sanitized_str()}` validado para execução.",
            success=True,
        )
        await self._logger.log_execution(result)
        return result

    async def _handle_execution_turn(
        self,
        user_query: str,
        command: CommandStatement,
        interpretation: str,
        context: ExecutionContext,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> SentryExecutionResult:
        if on_status:
            on_status(f"Executando: {command.sanitized_str()}")

        execution_result = await self._executor.execute(command, context)

        if on_status:
            on_status("Sintetizando diagnóstico...")

        def on_synth_token(count: int, chunk: str) -> None:
            if on_status:
                on_status(f"Sintetizando diagnóstico... [{count} tokens]")

        summary = await self._llm.synthesize_response(
            user_query,
            command,
            execution_result,
            context=context,
            on_token=on_synth_token if on_status else None,
        )

        result = SentryExecutionResult(
            user_query=user_query,
            command=command,
            execution=execution_result,
            llm_interpretation=interpretation,
            summary=summary,
            success=execution_result.is_success(),
        )
        await self._logger.log_execution(result)
        return result
