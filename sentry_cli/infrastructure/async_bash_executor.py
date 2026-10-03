"""
Adaptador de Infraestrutura: AsyncBashExecutor implementando ICommandExecutor.
Executa comandos assíncronos no shell do Debian com controle de timeout,
limites de buffer, truncamento semântico e contenção de falhas.
"""

import asyncio
import os
import sys
import time
from typing import Dict, Tuple

from sentry_cli.domain.interfaces import ICommandExecutor
from sentry_cli.domain.value_objects import (
    CommandExecutionResult,
    CommandStatement,
    ExecutionContext,
)


class AsyncBashExecutor(ICommandExecutor):
    """
    Executor de comandos assíncronos no sistema operacional (Debian / Windows).
    Garante isolamento contra travamentos de processos filhos e estouro de memória.
    """

    async def execute(
        self, command: CommandStatement, context: ExecutionContext
    ) -> CommandExecutionResult:
        """Executa um comando no SO com contenção estrita de recursos."""
        start_time = time.perf_counter()
        raw_cmd = command.sanitized_str()

        env = self._build_environment(context)
        working_dir = (
            context.working_directory
            if (context.working_directory and os.path.exists(context.working_directory))
            else None
        )

        try:
            if sys.platform == "win32":
                process = await asyncio.create_subprocess_exec(
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    raw_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=working_dir,
                    env=env,
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    raw_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=working_dir,
                    env=env,
                )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=context.timeout_seconds
            )

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            exit_code = process.returncode if process.returncode is not None else 0

            stdout_str = self._decode_and_truncate(
                stdout_bytes, context.max_output_length
            )
            stderr_str = self._decode_and_truncate(
                stderr_bytes, context.max_output_length
            )

            return CommandExecutionResult(
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                duration_ms=elapsed_ms,
                timed_out=False,
            )

        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            await self._terminate_timed_out_process(process)
            return CommandExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Execução interrompida por exceder timeout de {context.timeout_seconds:.1f}s.",
                duration_ms=elapsed_ms,
                timed_out=True,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return CommandExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"Erro de baixo nível ao invocar comando: {str(e)}",
                duration_ms=elapsed_ms,
                timed_out=False,
            )

    def _build_environment(self, context: ExecutionContext) -> Dict[str, str]:
        """Constrói variáveis de ambiente seguras e não interativas."""
        env = os.environ.copy()
        if sys.platform != "win32":
            env["DEBIAN_FRONTEND"] = "noninteractive"
            env["PAGER"] = "cat"
            env["LC_ALL"] = "C.UTF-8"
        if context.environment:
            env.update(context.environment)
        return env

    def _decode_and_truncate(self, data: bytes, max_len: int) -> str:
        """Decodifica saída de bytes e aplica truncamento semântico nas bordas se necessário."""
        text = data.decode("utf-8", errors="replace").strip()
        if len(text) <= max_len:
            return text

        excess = len(text) - max_len
        head_len = int(max_len * 0.6)
        tail_len = int(max_len * 0.4)

        head = text[:head_len]
        tail = text[-tail_len:]
        marker = f"\n[... Truncado pelo Sentry Executor: {excess} caracteres omitidos ...]\n"
        return f"{head}{marker}{tail}"

    async def _terminate_timed_out_process(
        self, process: asyncio.subprocess.Process
    ) -> None:
        """Encerra o processo estourado de forma resiliente."""
        try:
            process.kill()
            await process.wait()
        except ProcessLookupError:
            pass
