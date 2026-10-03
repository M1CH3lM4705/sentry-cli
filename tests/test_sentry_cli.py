"""
Testes unitários abrangentes para o subsistema Sentry CLI.
Cobre Domínio, Casos de Uso com Mocks e Adaptadores de Infraestrutura.
"""

import asyncio
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sentry_cli.domain.value_objects import (
    CommandExecutionResult,
    CommandStatement,
    ExecutionContext,
    SecurityViolationError,
)
from sentry_cli.domain.entities import SentryExecutionResult
from sentry_cli.domain.interfaces import IAuditLogger, ICommandExecutor, ILLMProvider
from sentry_cli.application.execute_sentry_turn import ExecuteSentryTurnUseCase
from sentry_cli.application.inspect_homelab import InspectHomelabUseCase
from sentry_cli.application.interactive_session import (
    InteractiveSessionUseCase,
    SessionTurnResult,
)
from sentry_cli.infrastructure.async_bash_executor import AsyncBashExecutor
from sentry_cli.infrastructure.ollama_provider import OllamaProvider
from sentry_cli.infrastructure.obsidian_audit_logger import ObsidianAuditLogger
from sentry_cli.interfaces.bridge import SentryBridge
from sentry_cli.interfaces.cli import print_banner, run_repl
from sentry_cli.interfaces.loader import SentryLoader


class TestSentryValueObjects(unittest.TestCase):
    """Testes para os Value Objects do domínio."""

    def test_command_statement_valid(self):
        stmt = CommandStatement("docker ps -a")
        self.assertEqual(stmt.sanitized_str(), "docker ps -a")
        self.assertEqual(str(stmt), "docker ps -a")

    def test_command_statement_empty_raises(self):
        with self.assertRaises(ValueError):
            CommandStatement("   ")

    def test_command_statement_security_violation_rm_rf(self):
        with self.assertRaises(SecurityViolationError):
            CommandStatement("rm -rf /")

    def test_command_statement_security_violation_fork_bomb(self):
        with self.assertRaises(SecurityViolationError):
            CommandStatement(":(){ :|:& };:")

    def test_command_statement_security_violation_mkfs(self):
        with self.assertRaises(SecurityViolationError):
            CommandStatement("mkfs.ext4 /dev/sda")

    def test_command_statement_security_violation_dd(self):
        with self.assertRaises(SecurityViolationError):
            CommandStatement("dd if=/dev/zero of=/dev/sda")

    def test_execution_context_valid_defaults(self):
        ctx = ExecutionContext()
        self.assertEqual(ctx.user, "homelab")
        self.assertEqual(ctx.timeout_seconds, 30.0)
        self.assertEqual(ctx.max_output_length, 4000)
        self.assertFalse(ctx.dry_run)

    def test_execution_context_invalid_timeout(self):
        with self.assertRaises(ValueError):
            ExecutionContext(timeout_seconds=0)

    def test_execution_context_invalid_max_output(self):
        with self.assertRaises(ValueError):
            ExecutionContext(max_output_length=-5)

    def test_command_execution_result_success(self):
        res = CommandExecutionResult(
            exit_code=0, stdout="OK", stderr="", duration_ms=12.5, timed_out=False
        )
        self.assertTrue(res.is_success())
        self.assertEqual(res.combined_output(), "OK")

    def test_command_execution_result_failure_with_stderr(self):
        res = CommandExecutionResult(
            exit_code=1, stdout="", stderr="Error", duration_ms=15.0, timed_out=False
        )
        self.assertFalse(res.is_success())
        self.assertEqual(res.combined_output(), "[STDERR]: Error")

    def test_command_execution_result_combined_both(self):
        res = CommandExecutionResult(
            exit_code=0, stdout="info", stderr="warning", duration_ms=10.0
        )
        self.assertEqual(res.combined_output(), "info\n[STDERR]: warning")

    def test_command_execution_result_empty(self):
        res = CommandExecutionResult(
            exit_code=0, stdout="", stderr="", duration_ms=5.0
        )
        self.assertEqual(res.combined_output(), "(Sem saída de texto gerada pelo comando)")


class TestSentryEntities(unittest.TestCase):
    """Testes para as Entidades do domínio."""

    def test_sentry_execution_result_to_audit_entry_and_dict(self):
        cmd = CommandStatement("docker ps")
        exec_res = CommandExecutionResult(
            exit_code=0, stdout="container-1 Up", stderr="", duration_ms=45.2
        )
        result = SentryExecutionResult(
            user_query="Status docker",
            command=cmd,
            execution=exec_res,
            llm_interpretation="Lista os containers ativos.",
            summary="1 container rodando em harmonia.",
            success=True,
        )

        audit_md = result.to_audit_entry()
        self.assertIn("[SUCESSO]", audit_md)
        self.assertIn("docker ps", audit_md)
        self.assertIn("1 container rodando em harmonia.", audit_md)

        res_dict = result.to_dict()
        self.assertEqual(res_dict["user_query"], "Status docker")
        self.assertEqual(res_dict["command"], "docker ps")
        self.assertEqual(res_dict["exit_code"], 0)
        self.assertTrue(res_dict["success"])


class TestExecuteSentryTurnUseCase(unittest.IsolatedAsyncioTestCase):
    """Testes para o caso de uso ExecuteSentryTurnUseCase com Mocks."""

    async def test_conversational_turn_without_command(self):
        llm_mock = MagicMock(spec=ILLMProvider)
        llm_mock.decide_action = AsyncMock(return_value=(None, "Olá Michel, SENTRY operando."))
        executor_mock = MagicMock(spec=ICommandExecutor)
        logger_mock = MagicMock(spec=IAuditLogger)
        logger_mock.log_execution = AsyncMock()

        use_case = ExecuteSentryTurnUseCase(llm_mock, executor_mock, logger_mock)
        res = await use_case.execute("E aí Sentry?")

        self.assertIsNone(res.command)
        self.assertIsNone(res.execution)
        self.assertEqual(res.summary, "Olá Michel, SENTRY operando.")
        self.assertTrue(res.success)
        executor_mock.execute.assert_not_called()
        logger_mock.log_execution.assert_called_once()

    async def test_execution_turn_with_command(self):
        cmd = CommandStatement("docker ps")
        llm_mock = MagicMock(spec=ILLMProvider)
        llm_mock.decide_action = AsyncMock(return_value=(cmd, "Listando containers."))
        llm_mock.synthesize_response = AsyncMock(return_value="Containers verificados.")

        exec_res = CommandExecutionResult(
            exit_code=0, stdout="nextcloud Up", stderr="", duration_ms=25.0
        )
        executor_mock = MagicMock(spec=ICommandExecutor)
        executor_mock.execute = AsyncMock(return_value=exec_res)

        logger_mock = MagicMock(spec=IAuditLogger)
        logger_mock.log_execution = AsyncMock()

        use_case = ExecuteSentryTurnUseCase(llm_mock, executor_mock, logger_mock)
        res = await use_case.execute("Verifique os containers")

        self.assertEqual(res.command.sanitized_str(), "docker ps")
        self.assertEqual(res.summary, "Containers verificados.")
        self.assertTrue(res.success)
        executor_mock.execute.assert_called_once()
        logger_mock.log_execution.assert_called_once()

    async def test_dry_run_turn(self):
        cmd = CommandStatement("systemctl restart personal-agent.service")
        llm_mock = MagicMock(spec=ILLMProvider)
        llm_mock.decide_action = AsyncMock(return_value=(cmd, "Reiniciar serviço."))

        executor_mock = MagicMock(spec=ICommandExecutor)
        logger_mock = MagicMock(spec=IAuditLogger)
        logger_mock.log_execution = AsyncMock()

        use_case = ExecuteSentryTurnUseCase(llm_mock, executor_mock, logger_mock)
        ctx = ExecutionContext(dry_run=True)
        res = await use_case.execute("Reiniciar agente", ctx)

        self.assertIn("DRY-RUN", res.execution.stdout)
        executor_mock.execute.assert_not_called()
        logger_mock.log_execution.assert_called_once()


class TestInspectHomelabUseCase(unittest.IsolatedAsyncioTestCase):
    """Testes para o caso de uso InspectHomelabUseCase."""

    async def test_inspect_valid_docker_component(self):
        executor_mock = MagicMock(spec=ICommandExecutor)
        exec_res = CommandExecutionResult(
            exit_code=0, stdout="vaultwarden Up", stderr="", duration_ms=20.0
        )
        executor_mock.execute = AsyncMock(return_value=exec_res)
        logger_mock = MagicMock(spec=IAuditLogger)
        logger_mock.log_execution = AsyncMock()

        use_case = InspectHomelabUseCase(executor_mock, logger_mock)
        res = await use_case.execute("docker")

        self.assertTrue(res.success)
        self.assertIn("docker ps", res.command.sanitized_str())
        self.assertEqual(res.summary, "vaultwarden Up")
        executor_mock.execute.assert_called_once()
        logger_mock.log_execution.assert_called_once()

    async def test_inspect_unknown_component(self):
        executor_mock = MagicMock(spec=ICommandExecutor)
        logger_mock = MagicMock(spec=IAuditLogger)
        logger_mock.log_execution = AsyncMock()

        use_case = InspectHomelabUseCase(executor_mock, logger_mock)
        res = await use_case.execute("componente_fantasma")

        self.assertFalse(res.success)
        self.assertIn("Componente desconhecido", res.summary)
        executor_mock.execute.assert_not_called()
        logger_mock.log_execution.assert_called_once()

    async def test_inspect_dry_run(self):
        executor_mock = MagicMock(spec=ICommandExecutor)
        logger_mock = MagicMock(spec=IAuditLogger)
        logger_mock.log_execution = AsyncMock()

        use_case = InspectHomelabUseCase(executor_mock, logger_mock)
        ctx = ExecutionContext(dry_run=True)
        res = await use_case.execute("storage", ctx)

        self.assertTrue(res.success)
        self.assertIn("DRY-RUN", res.execution.stdout)
        executor_mock.execute.assert_not_called()


class TestAsyncBashExecutor(unittest.IsolatedAsyncioTestCase):
    """Testes para o executor assíncrono bash."""

    async def test_execute_echo_success(self):
        executor = AsyncBashExecutor()
        cmd = CommandStatement("echo 'SENTRY_CLI_TEST'")
        ctx = ExecutionContext(timeout_seconds=5.0)

        result = await executor.execute(cmd, ctx)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout, "SENTRY_CLI_TEST")
        self.assertFalse(result.timed_out)
        self.assertTrue(result.duration_ms > 0)

    async def test_execute_timeout_handling(self):
        executor = AsyncBashExecutor()
        cmd = CommandStatement("sleep 2")
        ctx = ExecutionContext(timeout_seconds=0.2)

        result = await executor.execute(cmd, ctx)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.exit_code, -1)
        self.assertIn("timeout", result.stderr.lower())

    async def test_execute_semantic_truncation(self):
        executor = AsyncBashExecutor()
        # Gera texto com 600 caracteres
        cmd = CommandStatement("python3 -c 'print(\"A\" * 600)'")
        ctx = ExecutionContext(max_output_length=200, timeout_seconds=5.0)

        result = await executor.execute(cmd, ctx)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Truncado pelo Sentry Executor", result.stdout)


class TestOllamaProviderParsing(unittest.TestCase):
    """Testes para a lógica de parsing e formatação do OllamaProvider."""

    def test_parse_decision_output_standard_format(self):
        provider = OllamaProvider()
        raw = "COMANDO: docker ps\nINTERPRETAÇÃO: Verifica containers em execução."
        cmd, interp = provider._parse_decision_output(raw)
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.sanitized_str(), "docker ps")
        self.assertEqual(interp, "Verifica containers em execução.")

    def test_parse_decision_output_code_block(self):
        provider = OllamaProvider()
        raw = "Aqui está o comando:\n```bash\ndf -h\n```"
        cmd, interp = provider._parse_decision_output(raw)
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.sanitized_str(), "df -h")

    def test_parse_decision_output_conversational(self):
        provider = OllamaProvider()
        raw = "RESPOSTA: Fala Michel! O homelab tá suave na nave."
        cmd, reply = provider._parse_decision_output(raw)
        self.assertIsNone(cmd)
        self.assertEqual(reply, "Fala Michel! O homelab tá suave na nave.")


class TestObsidianAuditLogger(unittest.IsolatedAsyncioTestCase):
    """Testes para o gravador de auditoria no Obsidian."""

    async def test_audit_logging_writes_file_and_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "subfolder" / "audit.md"
            logger = ObsidianAuditLogger(audit_file_path=audit_file)

            cmd = CommandStatement("uptime")
            exec_res = CommandExecutionResult(
                exit_code=0, stdout="load average: 0.15", stderr="", duration_ms=10.0
            )
            result = SentryExecutionResult(
                user_query="Como tá a carga?",
                command=cmd,
                execution=exec_res,
                llm_interpretation="Verifica uptime.",
                summary="Carga baixa.",
                success=True,
            )

            await logger.log_execution(result)

            self.assertTrue(audit_file.exists())
            content = audit_file.read_text(encoding="utf-8")
            self.assertIn("Log de Auditoria Operacional do Sentry CLI", content)
            self.assertIn("Como tá a carga?", content)
            self.assertIn("load average: 0.15", content)


class TestExecutionContextSlidingWindowAndTruncation(unittest.TestCase):
    """Testes para gestão de janela deslizante e truncamento cirúrgico de linhas."""

    def test_truncate_lines_under_limit(self):
        text = "linha 1\nlinha 2\nlinha 3"
        result = ExecutionContext.truncate_lines(text, max_lines=15)
        self.assertEqual(result, text)
        self.assertNotIn("truncada", result)

    def test_truncate_lines_exact_limit(self):
        lines = [f"line {i}" for i in range(1, 16)]
        text = "\n".join(lines)
        result = ExecutionContext.truncate_lines(text, max_lines=15)
        self.assertEqual(result, text)
        self.assertNotIn("truncada", result)

    def test_truncate_lines_exceeding_limit(self):
        lines = [f"line {i}" for i in range(1, 25)]
        text = "\n".join(lines)
        result = ExecutionContext.truncate_lines(text, max_lines=15)
        
        result_lines = result.splitlines()
        # 15 linhas de saída + 1 linha de marcador
        self.assertEqual(len(result_lines), 16)
        self.assertEqual(result_lines[0], "line 1")
        self.assertEqual(result_lines[14], "line 15")
        self.assertIn("[... saída truncada: exibindo primeiras 15 linhas ...]", result_lines[15])

    def test_truncate_lines_empty(self):
        self.assertEqual(ExecutionContext.truncate_lines(""), "")
        self.assertEqual(ExecutionContext.truncate_lines("   "), "")

    def test_sliding_window_sliding_behavior(self):
        ctx = ExecutionContext(max_history_turns=6)
        self.assertEqual(len(ctx.get_sliding_history()), 0)

        # Adiciona 8 mensagens (4 turnos de usuário/assistente)
        for i in range(1, 9):
            role = "user" if i % 2 != 0 else "assistant"
            ctx = ctx.with_turn(role, f"mensagem {i}")

        history = ctx.get_sliding_history()
        # Deve reter estritamente no máximo 6 turnos
        self.assertEqual(len(history), 6)
        # As primeiras mensagens (1 e 2) devem ter deslizado para fora
        self.assertEqual(history[0]["content"], "mensagem 3")
        self.assertEqual(history[-1]["content"], "mensagem 8")

    def test_clear_history(self):
        ctx = ExecutionContext()
        ctx = ctx.with_turn("user", "ola").with_turn("assistant", "fala ai")
        self.assertEqual(len(ctx.get_sliding_history()), 2)

        cleared = ctx.clear_history()
        self.assertEqual(len(cleared.get_sliding_history()), 0)


class TestInteractiveSessionUseCase(unittest.IsolatedAsyncioTestCase):
    """Testes completos para o caso de uso InteractiveSessionUseCase."""

    def setUp(self):
        self.llm_mock = MagicMock(spec=ILLMProvider)
        self.executor_mock = MagicMock(spec=ICommandExecutor)
        self.logger_mock = MagicMock(spec=IAuditLogger)
        self.logger_mock.log_execution = AsyncMock()

    async def test_internal_exit_commands(self):
        use_case = InteractiveSessionUseCase(
            self.llm_mock, self.executor_mock, self.logger_mock
        )

        for cmd in ("/exit", "/quit", "sair", "exit", "quit", "q"):
            res = await use_case.process_input(cmd)
            self.assertTrue(res.should_exit)
            self.assertTrue(res.is_internal_command)
            self.assertIn("encerrada", res.internal_message.lower())

        self.llm_mock.decide_action.assert_not_called()

    async def test_internal_clear_command(self):
        use_case = InteractiveSessionUseCase(
            self.llm_mock, self.executor_mock, self.logger_mock
        )
        # Injeta turnos prévios
        use_case._context = use_case._context.with_turn("user", "teste 1")
        self.assertEqual(len(use_case.context.get_sliding_history()), 1)

        res = await use_case.process_input("/clear")
        self.assertTrue(res.should_clear_terminal)
        self.assertTrue(res.is_internal_command)
        self.assertEqual(len(use_case.context.get_sliding_history()), 0)
        self.llm_mock.decide_action.assert_not_called()

    async def test_internal_history_command(self):
        use_case = InteractiveSessionUseCase(
            self.llm_mock, self.executor_mock, self.logger_mock
        )
        
        # Histórico inicialmente vazio
        empty_res = await use_case.process_input("/history")
        self.assertTrue(empty_res.is_internal_command)
        self.assertIn("vazio", empty_res.internal_message.lower())

        # Popula turnos
        use_case._context = use_case._context.with_turn("user", "Status homelab")
        use_case._context = use_case._context.with_turn("assistant", "Tudo normal.")

        populated_res = await use_case.process_input("/history")
        self.assertIn("Status homelab", populated_res.internal_message)
        self.assertIn("Tudo normal.", populated_res.internal_message)

    async def test_conversational_turn_retains_context(self):
        self.llm_mock.decide_action = AsyncMock(
            return_value=(None, "SENTRY operacional em prontidão.")
        )
        use_case = InteractiveSessionUseCase(
            self.llm_mock, self.executor_mock, self.logger_mock
        )

        res = await use_case.process_input("Olá Sentry")
        self.assertFalse(res.should_exit)
        self.assertFalse(res.is_internal_command)
        self.assertEqual(res.execution_result.summary, "SENTRY operacional em prontidão.")
        
        # Valida que o contexto registrou o par user/assistant
        history = use_case.context.get_sliding_history()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0], {"role": "user", "content": "Olá Sentry"})
        self.assertEqual(history[1], {"role": "assistant", "content": "SENTRY operacional em prontidão."})
        self.logger_mock.log_execution.assert_called_once()

    async def test_command_turn_surgical_truncation_and_context_update(self):
        cmd = CommandStatement("journalctl -n 50")
        self.llm_mock.decide_action = AsyncMock(
            return_value=(cmd, "Consultando logs do sistema.")
        )
        self.llm_mock.synthesize_response = AsyncMock(
            return_value="Nenhum erro crítico encontrado nos logs."
        )

        # Gera 30 linhas de saída de comando
        long_output = "\n".join([f"Sep 29 log entry line {i}" for i in range(1, 31)])
        exec_result = CommandExecutionResult(
            exit_code=0, stdout=long_output, stderr="", duration_ms=40.0
        )
        self.executor_mock.execute = AsyncMock(return_value=exec_result)

        use_case = InteractiveSessionUseCase(
            self.llm_mock, self.executor_mock, self.logger_mock
        )

        res = await use_case.process_input("verificar logs recentes")
        self.assertTrue(res.execution_result.success)
        self.assertEqual(res.execution_result.summary, "Nenhum erro crítico encontrado nos logs.")

        # Valida que o assistente gravou no histórico a saída truncada em 15 linhas
        history = use_case.context.get_sliding_history()
        self.assertEqual(len(history), 2)
        assistant_turn = history[1]["content"]
        self.assertIn("journalctl -n 50", assistant_turn)
        self.assertIn("[... saída truncada: exibindo primeiras 15 linhas ...]", assistant_turn)
        self.assertIn("Nenhum erro crítico encontrado nos logs.", assistant_turn)

    async def test_contextual_continuity_two_consecutive_turns(self):
        """Valida que o segundo turno recebe o contexto do primeiro turno com continuidade."""
        # Turno 1: consulta memória
        cmd_mem = CommandStatement("free -h")
        self.llm_mock.decide_action = AsyncMock()
        self.llm_mock.synthesize_response = AsyncMock()

        self.llm_mock.decide_action.side_effect = [
            (cmd_mem, "Checar memória"),
            (None, "A swap tem 4GB configurados e está com 0B de uso, conforme os dados de memória anteriores.")
        ]
        self.llm_mock.synthesize_response.return_value = "Memória total: 16GB, livre: 10GB."

        mem_output = "              total        used        free      shared  buff/cache   available\nMem:           15Gi       3.2Gi        10Gi       256Mi       2.1Gi        11Gi\nSwap:         4.0Gi          0B       4.0Gi"
        self.executor_mock.execute = AsyncMock(
            return_value=CommandExecutionResult(0, mem_output, "", 15.0)
        )

        use_case = InteractiveSessionUseCase(
            self.llm_mock, self.executor_mock, self.logger_mock
        )

        # Executa Turno 1
        res1 = await use_case.process_input("como está a memória?")
        self.assertEqual(res1.execution_result.summary, "Memória total: 16GB, livre: 10GB.")

        # Executa Turno 2 (referenciando o anterior)
        res2 = await use_case.process_input("e a swap referenciando a resposta anterior?")
        self.assertIn("A swap tem 4GB configurados", res2.execution_result.summary)

        # Verifica chamadas do LLM: o segundo decide_action deve ter recebido o contexto com o turno 1
        call_args_list = self.llm_mock.decide_action.call_args_list
        self.assertEqual(len(call_args_list), 2)
        
        ctx_turn2 = call_args_list[1][0][1]  # segundo argumento posicional (context)
        history_turn2 = ctx_turn2.get_sliding_history()
        self.assertEqual(len(history_turn2), 2)
        self.assertEqual(history_turn2[0]["content"], "como está a memória?")
        self.assertIn("free -h", history_turn2[1]["content"])

    async def test_dry_run_turn_in_session(self):
        cmd = CommandStatement("reboot")
        self.llm_mock.decide_action = AsyncMock(return_value=(cmd, "Reiniciar host"))
        
        ctx = ExecutionContext(dry_run=True)
        use_case = InteractiveSessionUseCase(
            self.llm_mock, self.executor_mock, self.logger_mock, initial_context=ctx
        )

        res = await use_case.process_input("reiniciar servidor")
        self.assertTrue(res.execution_result.success)
        self.assertIn("DRY-RUN", res.execution_result.execution.stdout)
        self.executor_mock.execute.assert_not_called()


class TestOllamaProviderContextInjection(unittest.IsolatedAsyncioTestCase):
    """Testes para injeção de contexto deslizante no OllamaProvider."""

    async def test_decide_action_injects_sliding_history(self):
        provider = OllamaProvider()
        provider.chat = AsyncMock(return_value="RESPOSTA: Entendido perfeitamente.")

        ctx = ExecutionContext().with_turn("user", "Pergunta 1").with_turn("assistant", "Resposta 1")

        cmd, reply = await provider.decide_action("Pergunta 2", ctx)
        self.assertIsNone(cmd)
        self.assertEqual(reply, "Entendido perfeitamente.")

        provider.chat.assert_called_once()
        sent_messages = provider.chat.call_args[0][0]
        # Esperado: system, user (P1), assistant (R1), user (P2)
        self.assertEqual(len(sent_messages), 4)
        self.assertEqual(sent_messages[0]["role"], "system")
        self.assertEqual(sent_messages[1]["content"], "Pergunta 1")
        self.assertEqual(sent_messages[2]["content"], "Resposta 1")
        self.assertIn("Pergunta 2", sent_messages[3]["content"])

    async def test_synthesize_response_injects_sliding_history(self):
        provider = OllamaProvider()
        provider.chat = AsyncMock(return_value="Síntese com contexto concluída.")

        ctx = ExecutionContext().with_turn("user", "Turno anterior").with_turn("assistant", "OK")
        cmd = CommandStatement("uptime")
        exec_res = CommandExecutionResult(0, "load 0.05", "", 10.0)

        synthesis = await provider.synthesize_response(
            "Carga?", cmd, exec_res, context=ctx
        )
        self.assertEqual(synthesis, "Síntese com contexto concluída.")

        sent_messages = provider.chat.call_args[0][0]
        self.assertEqual(sent_messages[0]["role"], "system")
        self.assertEqual(sent_messages[1]["content"], "Turno anterior")
        self.assertEqual(sent_messages[2]["content"], "OK")
        self.assertIn("uptime", sent_messages[3]["content"])


class TestSentryBridgeInteractiveSession(unittest.TestCase):
    """Testes para criação da sessão interativa via bridge."""

    def test_create_interactive_session(self):
        bridge = SentryBridge()
        session = bridge.create_interactive_session(dry_run=True, timeout=15.0)
        self.assertIsInstance(session, InteractiveSessionUseCase)
        self.assertTrue(session.context.dry_run)
        self.assertEqual(session.context.timeout_seconds, 15.0)


class TestInteractiveSessionInternalCommands(unittest.TestCase):
    """Testes para validação e discriminação de comandos internos."""

    def setUp(self):
        llm_mock = MagicMock(spec=ILLMProvider)
        executor_mock = MagicMock(spec=ICommandExecutor)
        logger_mock = MagicMock(spec=IAuditLogger)
        self.session = InteractiveSessionUseCase(llm_mock, executor_mock, logger_mock)

    def test_is_internal_command_truthy(self):
        internal_cmds = ["/clear", "/history", "exit", "quit", "sair", "q", "/exit", "/quit", "", "   "]
        for cmd in internal_cmds:
            self.assertTrue(self.session.is_internal_command(cmd), f"Falha para comando interno: '{cmd}'")

    def test_is_internal_command_falsy(self):
        user_prompts = [
            "docker ps",
            "status do homelab",
            "verificar uso de memória",
            "quem é você?",
            "systemctl status",
        ]
        for prompt in user_prompts:
            self.assertFalse(self.session.is_internal_command(prompt), f"Deveria ser falso para prompt: '{prompt}'")


class TestSentryLoader(unittest.IsolatedAsyncioTestCase):
    """Testes para o componente visual SentryLoader."""

    async def test_loader_initial_state_and_properties(self):
        loader = SentryLoader(message="Testando...")
        self.assertFalse(loader.is_running)
        self.assertEqual(loader.message, "Testando...")
        loader.set_message("Novo status")
        self.assertEqual(loader.message, "Novo status")

    async def test_loader_disabled_when_not_tty(self):
        stream = io.StringIO()
        loader = SentryLoader(stream=stream, enabled=False)
        await loader.start()
        self.assertFalse(loader.is_running)
        await loader.stop()
        self.assertEqual(stream.getvalue(), "")

    async def test_loader_start_and_stop_lifecycle_with_stream(self):
        stream = io.StringIO()
        loader = SentryLoader(message="Executando teste", interval=0.01, stream=stream, enabled=True)
        await loader.start()
        self.assertTrue(loader.is_running)
        await asyncio.sleep(0.03)
        await loader.stop()
        self.assertFalse(loader.is_running)

        output = stream.getvalue()
        self.assertIn("Executando teste", output)
        self.assertIn(loader.CLEAR_LINE, output)
        self.assertIn(loader.SHOW_CURSOR, output)

    async def test_loader_context_manager(self):
        stream = io.StringIO()
        loader = SentryLoader(message="Context manager test", interval=0.01, stream=stream, enabled=True)
        async with loader:
            self.assertTrue(loader.is_running)
            await asyncio.sleep(0.02)
        self.assertFalse(loader.is_running)
        self.assertIn("Context manager test", stream.getvalue())

    async def test_loader_idempotent_start_and_stop(self):
        stream = io.StringIO()
        loader = SentryLoader(stream=stream, enabled=True)
        await loader.start()
        await loader.start()  # Segundo start não deve quebrar nem duplicar task
        self.assertTrue(loader.is_running)
        await loader.stop()
        await loader.stop()  # Segundo stop não deve quebrar
        self.assertFalse(loader.is_running)


class TestReplWithLoader(unittest.IsolatedAsyncioTestCase):
    """Testes para o REPL interativo com integração do loader."""

    @patch("builtins.input")
    @patch("sentry_cli.interfaces.cli.SentryLoader")
    async def test_repl_triggers_loader_for_prompts_and_skips_for_internal_cmds(
        self, mock_loader_cls, mock_input
    ):
        mock_loader_instance = MagicMock()
        mock_loader_instance.__aenter__ = AsyncMock(return_value=mock_loader_instance)
        mock_loader_instance.__aexit__ = AsyncMock(return_value=None)
        mock_loader_cls.return_value = mock_loader_instance

        # Sequência de entradas no REPL: prompt normal -> comando interno /history -> exit
        mock_input.side_effect = [
            "docker ps",
            "/history",
            "sair",
        ]

        bridge_mock = MagicMock(spec=SentryBridge)
        session_mock = MagicMock()
        session_mock.is_internal_command.side_effect = lambda cmd: cmd in ("/history", "sair")

        exec_turn_res = SessionTurnResult(
            user_input="docker ps",
            execution_result=MagicMock(success=True, user_query="docker ps", command=None, execution=None, summary="OK")
        )
        history_turn_res = SessionTurnResult(
            user_input="/history",
            is_internal_command=True,
            internal_message="Historico..."
        )
        exit_turn_res = SessionTurnResult(
            user_input="sair",
            should_exit=True,
            is_internal_command=True,
            internal_message="Sessão Sentry encerrada."
        )

        session_mock.process_input = AsyncMock(side_effect=[
            exec_turn_res,
            history_turn_res,
            exit_turn_res,
        ])
        bridge_mock.create_interactive_session.return_value = session_mock

        with patch("sys.stdout", new_callable=io.StringIO):
            await run_repl(bridge_mock, dry_run=False, timeout=30.0, model_name="CORE-0")

        # Loader deve ter sido instanciado e entrado via async with para 'docker ps'
        mock_loader_cls.assert_called_once_with(message="Sentry processando...")
        mock_loader_instance.__aenter__.assert_called_once()
        mock_loader_instance.__aexit__.assert_called_once()

class TestCrossPlatformCompatibility(unittest.TestCase):
    """Testes para validar comportamento multiplataforma (Windows e Linux)."""

    def test_ollama_provider_prompts_for_windows_and_linux(self):
        with patch("sys.platform", "win32"):
            prompt_win = OllamaProvider.get_default_decision_prompt()
            self.assertIn("Windows", prompt_win)
            self.assertIn("powershell", prompt_win)

        with patch("sys.platform", "linux"):
            prompt_linux = OllamaProvider.get_default_decision_prompt()
            self.assertIn("Debian", prompt_linux)
            self.assertIn("bash", prompt_linux)

    def test_obsidian_audit_path_on_windows(self):
        with patch("sys.platform", "win32"), patch.dict("os.environ", {}, clear=True):
            path = ObsidianAuditLogger.get_default_audit_path()
            self.assertEqual(path, Path.home() / ".sentry" / "audit.md")

    def test_inspect_commands_platform_selection(self):
        executor = MagicMock(spec=ICommandExecutor)
        logger = MagicMock(spec=IAuditLogger)
        use_case = InspectHomelabUseCase(executor, logger)
        supported = use_case.get_supported_components()
        self.assertIn("docker", supported)
        self.assertIn("storage", supported)
        self.assertIn("memory", supported)

    def test_async_bash_executor_env_on_windows(self):
        executor = AsyncBashExecutor()
        ctx = ExecutionContext()
        with patch("sys.platform", "win32"):
            env = executor._build_environment(ctx)
            self.assertNotIn("DEBIAN_FRONTEND", env)
            self.assertNotIn("LC_ALL", env)

        with patch("sys.platform", "linux"):
            env_linux = executor._build_environment(ctx)
            self.assertEqual(env_linux.get("DEBIAN_FRONTEND"), "noninteractive")


class TestSentryProgressAndModernFormatting(unittest.IsolatedAsyncioTestCase):
    """Testes para telemetria em tempo real (tokens, comando) e visual moderno de CLI de código."""

    def test_loader_format_message_highlights_command_and_tokens(self):
        loader = SentryLoader()
        msg_cmd = loader._format_message("Executando: docker ps -a")
        self.assertIn("Executando:", msg_cmd)
        self.assertIn("docker ps -a", msg_cmd)
        self.assertIn(loader.YELLOW, msg_cmd)

        msg_tokens = loader._format_message("Planejando ação... [18 tokens]")
        self.assertIn("Planejando ação...", msg_tokens)
        self.assertIn("[18 tokens]", msg_tokens)
        self.assertIn(loader.CYAN, msg_tokens)

    def test_format_cli_output_with_command_execution(self):
        from sentry_cli.interfaces.cli import format_cli_output

        cmd = CommandStatement("docker ps")
        exec_res = CommandExecutionResult(0, "CONTAINER ID IMAGE STATUS", "", 45.2)
        res = SentryExecutionResult(
            user_query="verificar containers",
            command=cmd,
            execution=exec_res,
            llm_interpretation="Listar containers.",
            summary="Containers operando normalmente.",
            success=True,
        )

        formatted = format_cli_output(res, model_name="gemma4:e2b")
        self.assertIn("╭─", formatted)
        self.assertIn("docker ps", formatted)
        self.assertIn("CONTAINER ID IMAGE STATUS", formatted)
        self.assertIn("código 0", formatted)
        self.assertIn("45.2ms", formatted)
        self.assertIn("Containers operando normalmente.", formatted)
        self.assertIn("sentry • gemma4:e2b", formatted)

    def test_format_cli_output_conversational_turn(self):
        from sentry_cli.interfaces.cli import format_cli_output

        res = SentryExecutionResult(
            user_query="olá",
            command=None,
            execution=None,
            llm_interpretation="Saudação.",
            summary="Olá, operador. Homelab sob guarda.",
            success=True,
        )

        formatted = format_cli_output(res, model_name="gemma4:e2b")
        self.assertNotIn("╭─ $", formatted)
        self.assertIn("Olá, operador. Homelab sob guarda.", formatted)
        self.assertIn("sentry • gemma4:e2b", formatted)

    async def test_execute_turn_invokes_on_status_lifecycle(self):
        llm_mock = MagicMock(spec=ILLMProvider)
        cmd = CommandStatement("uptime")
        llm_mock.decide_action = AsyncMock(return_value=(cmd, "Verificar carga."))
        llm_mock.synthesize_response = AsyncMock(return_value="Carga estável.")

        executor_mock = MagicMock(spec=ICommandExecutor)
        exec_res = CommandExecutionResult(0, "load 0.1", "", 12.0)
        executor_mock.execute = AsyncMock(return_value=exec_res)

        logger_mock = MagicMock(spec=IAuditLogger)
        logger_mock.log_execution = AsyncMock()

        use_case = ExecuteSentryTurnUseCase(llm_mock, executor_mock, logger_mock)

        status_reports = []

        def track_status(msg: str):
            status_reports.append(msg)

        result = await use_case.execute("como está o servidor?", on_status=track_status)

        self.assertTrue(result.success)
        self.assertIn("Planejando ação...", status_reports)
        self.assertIn("Executando: uptime", status_reports)
        self.assertIn("Sintetizando diagnóstico...", status_reports)


if __name__ == "__main__":
    unittest.main()
