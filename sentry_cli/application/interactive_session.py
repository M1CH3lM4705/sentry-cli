"""
Caso de uso: Sessão Interativa Contínua (REPL com memória contextual) do Sentry.
Orquestra o ciclo contínuo com janela deslizante para contenção de tokens na CPU AMD FX-6300.
"""

import sys
from dataclasses import dataclass
from typing import Callable, List, Optional
from sentry_cli.domain.entities import SentryExecutionResult
from sentry_cli.domain.interfaces import IAuditLogger, ICommandExecutor, ILLMProvider
from sentry_cli.domain.value_objects import (
    CommandExecutionResult,
    CommandStatement,
    ExecutionContext,
)


@dataclass(frozen=True)
class SessionTurnResult:
    """
    Representa o resultado de um turno no REPL interativo.
    Encapsula o despacho de comandos administrativos locais ou execuções do Sentry.
    """
    user_input: str
    should_exit: bool = False
    should_clear_terminal: bool = False
    is_internal_command: bool = False
    internal_message: Optional[str] = None
    execution_result: Optional[SentryExecutionResult] = None


class InteractiveSessionUseCase:
    """
    Orquestra sessões interativas contínuas do Sentry CLI.
    Aplica janela deslizante de no máximo 6 turnos (3 pares) e truncamento cirúrgico de 15 linhas
    para garantir baixa latência na CPU legada do homelab.
    """

    DEFAULT_SYSTEM_PROMPT_LINUX = (
        "Você é o SENTRY (CORE-0), operador tático do homelab Debian com permissão total para inspecionar e gerenciar o sistema via comandos bash.\n"
        "Seja direto, técnico, objetivo e preserve o contexto dos turnos anteriores.\n\n"
        "DIRETRIZES DE DECISÃO:\n"
        "1. Se a mensagem solicitar inspeção, verificação ou ação prática no homelab (Docker, containers, discos, storage, memória, CPU, processos, systemd, logs, rede, portas):\n"
        "   Gere o comando bash puro de inspeção/ação (ex: docker ps, free -h, df -h, systemctl status).\n"
        "   Mesmo sob linguagem natural indireta ('como estão os containers?', 'tem algum serviço parado?'), gere o comando!\n"
        "   Responda ESTRITAMENTE no formato:\n"
        "   COMANDO: <comando bash puro>\n"
        "   INTERPRETAÇÃO: <uma frase explicando o que o comando faz>\n\n"
        "2. Se for uma pergunta sobre suas capacidades, permissões ou quais comandos você tem acesso (ex: 'quais comandos você tem acesso?', 'o que você pode fazer?'), ou saudação/conversa geral, responda diretamente em português em no máximo 2 frases objetivas:\n"
        "   RESPOSTA: <sua resposta concisa em português>\n\n"
        "3. NUNCA diga que não tem acesso aos containers, arquivos ou ao sistema operacional. Você tem acesso total executando comandos bash.\n\n"
        "Não inclua blocos markdown extras ou explicações adicionais fora do formato."
    )

    DEFAULT_SYSTEM_PROMPT_WINDOWS = (
        "Você é o SENTRY (CORE-0), operador tático no ambiente Windows com permissão total para inspecionar o sistema via PowerShell/CMD.\n"
        "Seja direto, técnico, objetivo e preserve o contexto dos turnos anteriores.\n\n"
        "DIRETRIZES DE DECISÃO:\n"
        "1. Se a mensagem solicitar inspeção, verificação ou ação prática local (Docker, containers, discos, storage, memória, CPU, processos, serviços, rede, portas):\n"
        "   Gere o comando PowerShell/CMD puro de inspeção/ação (ex: docker ps, Get-Process, Get-Service).\n"
        "   Mesmo sob linguagem natural indireta ('como estão os containers?', 'tem algum serviço parado?'), gere o comando!\n"
        "   Responda ESTRITAMENTE no formato:\n"
        "   COMANDO: <comando powershell puro>\n"
        "   INTERPRETAÇÃO: <uma frase explicando o que o comando faz>\n\n"
        "2. Se for uma pergunta sobre suas capacidades, permissões ou quais comandos você tem acesso (ex: 'quais comandos você tem acesso?', 'o que você pode fazer?'), ou saudação/conversa geral, responda diretamente em português em no máximo 2 frases objetivas:\n"
        "   RESPOSTA: <sua resposta concisa em português>\n\n"
        "3. NUNCA diga que não tem acesso aos containers, arquivos ou ao sistema operacional. Você tem acesso total executando comandos PowerShell/CMD.\n\n"
        "Não inclua blocos markdown extras ou explicações adicionais fora do formato."
    )

    DEFAULT_SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT_WINDOWS if sys.platform == "win32" else DEFAULT_SYSTEM_PROMPT_LINUX

    def __init__(
        self,
        llm_provider: ILLMProvider,
        executor: ICommandExecutor,
        audit_logger: IAuditLogger,
        initial_context: Optional[ExecutionContext] = None,
    ) -> None:
        self._llm = llm_provider
        self._executor = executor
        self._logger = audit_logger
        base_ctx = initial_context or ExecutionContext()
        from dataclasses import replace
        sys_prompt = base_ctx.system_prompt or self.DEFAULT_SYSTEM_PROMPT
        self._context = replace(base_ctx, system_prompt=sys_prompt)

    @property
    def context(self) -> ExecutionContext:
        """Retorna o contexto atual da sessão."""
        return self._context

    async def process_input(
        self,
        user_input: str,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> SessionTurnResult:
        """
        Processa uma linha de entrada na sessão interativa.
        Discrimina comandos internos do shell local e turnos operacionais de IA.
        """
        clean_input = user_input.strip()

        if not clean_input:
            return SessionTurnResult(user_input=clean_input)

        if self._is_exit_command(clean_input):
            return self._handle_exit(clean_input)

        if clean_input.lower() == "/clear":
            return self._handle_clear(clean_input)

        if clean_input.lower() == "/history":
            return self._handle_history(clean_input)

        return await self._execute_session_turn(clean_input, on_status=on_status)

    def is_internal_command(self, user_input: str) -> bool:
        """
        Identifica se a entrada do operador é um comando interno/administrativo
        local (ex: /clear, /history, exit) que não requer inferência por IA.
        """
        clean = user_input.strip().lower()
        if not clean:
            return True
        return (
            self._is_exit_command(clean)
            or clean == "/clear"
            or clean == "/history"
        )

    def _is_exit_command(self, cmd: str) -> bool:
        """Identifica comandos de encerramento da sessão."""
        normalized = cmd.lower()
        return normalized in ("/exit", "/quit", "exit", "quit", "sair", "q")

    def _handle_exit(self, cmd: str) -> SessionTurnResult:
        """Trata o encerramento gracioso da sessão."""
        return SessionTurnResult(
            user_input=cmd,
            should_exit=True,
            is_internal_command=True,
            internal_message="Sessão Sentry encerrada. Homelab sob guarda.",
        )

    def _handle_clear(self, cmd: str) -> SessionTurnResult:
        """Limpa o buffer de histórico da sessão e solicita limpeza do terminal."""
        self._context = self._context.clear_history()
        return SessionTurnResult(
            user_input=cmd,
            should_clear_terminal=True,
            is_internal_command=True,
            internal_message="Histórico da sessão limpo com sucesso.",
        )

    def _handle_history(self, cmd: str) -> SessionTurnResult:
        """Exibe os turnos retidos na janela deslizante do buffer de contexto."""
        history = self._context.get_sliding_history()
        if not history:
            return SessionTurnResult(
                user_input=cmd,
                is_internal_command=True,
                internal_message="Buffer de histórico vazio (nenhum turno retido).",
            )

        lines: List[str] = [f"Turnos no buffer ({len(history)} mensagens retidas):"]
        for idx, turn in enumerate(history, start=1):
            role_label = "OPERADOR" if turn["role"] == "user" else "SENTRY"
            snippet = turn["content"]
            lines.append(f"• [{idx}] {role_label}: {snippet}")

        return SessionTurnResult(
            user_input=cmd,
            is_internal_command=True,
            internal_message="\n".join(lines),
        )

    async def _execute_session_turn(
        self,
        user_query: str,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> SessionTurnResult:
        """Executa um turno completo de IA e comando com preservação contextual."""
        if on_status:
            on_status("Planejando ação...")

        def on_decide_token(count: int, chunk: str) -> None:
            if on_status:
                on_status(f"Planejando ação... [{count} tokens]")

        command, interpretation = await self._llm.decide_action(
            user_query, self._context, on_token=on_decide_token if on_status else None
        )

        if command is None:
            return await self._handle_conversational_turn(user_query, interpretation)

        if self._context.dry_run:
            return await self._handle_dry_run_turn(user_query, command, interpretation)

        return await self._handle_execution_turn(
            user_query, command, interpretation, on_status=on_status
        )

    async def _handle_conversational_turn(
        self, user_query: str, interpretation: str
    ) -> SessionTurnResult:
        """Trata turno puramente conversacional alimentando o histórico podado."""
        result = SentryExecutionResult(
            user_query=user_query,
            command=None,
            execution=None,
            llm_interpretation=interpretation,
            summary=interpretation,
            success=True,
        )
        self._context = self._context.with_turn("user", user_query)
        self._context = self._context.with_turn("assistant", interpretation)
        await self._logger.log_execution(result)
        return SessionTurnResult(user_input=user_query, execution_result=result)

    async def _handle_dry_run_turn(
        self,
        user_query: str,
        command: CommandStatement,
        interpretation: str,
    ) -> SessionTurnResult:
        """Trata turno de simulação em dry-run."""
        simulated_execution = CommandExecutionResult(
            exit_code=0,
            stdout=f"[DRY-RUN]: O comando `{command.sanitized_str()}` foi planejado mas não executado.",
            stderr="",
            duration_ms=0.0,
            timed_out=False,
        )
        summary = f"Plano em simulação: comando `{command.sanitized_str()}` validado para execução."
        result = SentryExecutionResult(
            user_query=user_query,
            command=command,
            execution=simulated_execution,
            llm_interpretation=interpretation,
            summary=summary,
            success=True,
        )
        self._context = self._context.with_turn("user", user_query)
        self._context = self._context.with_turn("assistant", summary)
        await self._logger.log_execution(result)
        return SessionTurnResult(user_input=user_query, execution_result=result)

    async def _handle_execution_turn(
        self,
        user_query: str,
        command: CommandStatement,
        interpretation: str,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> SessionTurnResult:
        """Executa comando no Debian, aplica truncamento cirúrgico de 15 linhas e sintetiza."""
        if on_status:
            on_status(f"Executando: {command.sanitized_str()}")

        execution_result = await self._executor.execute(command, self._context)

        # Truncamento cirúrgico em no máximo 15 linhas mais significativas
        truncated_output = ExecutionContext.truncate_lines(
            execution_result.combined_output(), max_lines=15
        )

        if on_status:
            on_status("Sintetizando diagnóstico...")

        def on_synth_token(count: int, chunk: str) -> None:
            if on_status:
                on_status(f"Sintetizando diagnóstico... [{count} tokens]")

        summary = await self._llm.synthesize_response(
            user_query,
            command,
            execution_result,
            context=self._context,
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

        # Injeta no histórico o turno do usuário e do assistente com a saída truncada
        assistant_turn_content = (
            f"Comando executado: `{command.sanitized_str()}`\n"
            f"Saída:\n{truncated_output}\n"
            f"Síntese: {summary}"
        )
        self._context = self._context.with_turn("user", user_query)
        self._context = self._context.with_turn("assistant", assistant_turn_content)

        await self._logger.log_execution(result)
        return SessionTurnResult(user_input=user_query, execution_result=result)
