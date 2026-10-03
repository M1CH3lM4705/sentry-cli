"""
Ponto de entrada CLI (Command Line Interface) do subsistema Sentry.
Suporta execução direta por argumento, inspeções pré-configuradas e modo interativo REPL.
"""

import argparse
import asyncio
import json
import sys
from typing import List, Optional

from sentry_cli.domain.entities import SentryExecutionResult
from sentry_cli.domain.value_objects import (
    CommandStatement,
    ExecutionContext,
    SecurityViolationError,
)
from sentry_cli.infrastructure.async_bash_executor import AsyncBashExecutor
from sentry_cli.infrastructure.obsidian_audit_logger import ObsidianAuditLogger
from sentry_cli.infrastructure.ollama_provider import OllamaProvider
from sentry_cli.interfaces.bridge import SentryBridge
from sentry_cli.interfaces.loader import SentryLoader

# Cores ANSI para saída no terminal
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
GRAY = "\033[90m"


def print_banner(model_name: str = "CORE-0") -> None:
    """Imprime o cabeçalho tático moderno do Sentry CLI."""
    platform_label = "Windows (PowerShell)" if sys.platform == "win32" else "Debian Homelab"
    print(
        f"\n{CYAN}{BOLD}╭─ SENTRY CLI ─────────────────────────────────────────────────────────╮{RESET}\n"
        f"{CYAN}{BOLD}│{RESET}  {BOLD}◈ CORE-0 Operador Tático{RESET} {GRAY}•{RESET} {platform_label:<21} {GRAY}•{RESET} Clean Architecture {CYAN}{BOLD}│{RESET}\n"
        f"{CYAN}{BOLD}│{RESET}  {GRAY}Modelo:{RESET} {CYAN}{BOLD}{model_name:<16}{RESET} {GRAY}• Ollama local (CPU)             {CYAN}{BOLD}│{RESET}\n"
        f"{CYAN}{BOLD}╰──────────────────────────────────────────────────────────────────────╯{RESET}\n"
        f"{GRAY}  Digite {CYAN}/clear{GRAY} para limpar contexto, {CYAN}/history{GRAY} para histórico ou {YELLOW}exit{GRAY} para sair.{RESET}\n"
    )


def format_cli_output(result: SentryExecutionResult, model_name: str = "CORE-0") -> str:
    """Formata o resultado da execução para exibição elegante no estilo de CLIs de código modernas."""
    lines: List[str] = []

    # 1. Bloco de Ferramenta / Execução de Comando (se houver)
    if result.command:
        cmd_str = result.command.sanitized_str()
        lines.append(f"{CYAN}╭─ {BOLD}${RESET} {YELLOW}{BOLD}{cmd_str}{RESET}")

        if result.execution:
            output = result.execution.combined_output().strip()
            if output:
                for out_line in output.splitlines():
                    lines.append(f"{CYAN}│{RESET} {GRAY}{out_line}{RESET}")
            else:
                lines.append(f"{CYAN}│{RESET} {GRAY}(comando executado sem saída de texto){RESET}")

            # Rodapé do bloco de execução com status do SO e latência
            duration_str = f"{result.execution.duration_ms:.1f}ms"
            if result.execution.timed_out:
                status_badge = f"{RED}{BOLD}✖ timeout{RESET}"
            elif result.execution.exit_code == 0:
                status_badge = f"{GREEN}{BOLD}✔ código 0{RESET}"
            else:
                status_badge = f"{RED}{BOLD}✖ código {result.execution.exit_code}{RESET}"

            lines.append(f"{CYAN}╰─{RESET} {status_badge} {GRAY}({duration_str}){RESET}\n")
        else:
            lines.append(f"{CYAN}╰─{RESET} {YELLOW}⚡ validado para execução{RESET}\n")

    # 2. Resposta / Síntese do Sentry (texto direto e legível)
    if result.summary:
        lines.append(f"{result.summary}")

    # 3. Badge sutil de telemetria no rodapé
    status_icon = f"{GREEN}●{RESET}" if result.success else f"{RED}●{RESET}"
    lines.append(f"\n{GRAY}  {status_icon} sentry • {model_name}{RESET}")

    return "\n".join(lines)


async def run_repl(bridge: SentryBridge, dry_run: bool, timeout: float, model_name: str) -> None:
    """Inicia a sessão interativa contínua REPL com memória contextual."""
    print_banner(model_name)
    session = bridge.create_interactive_session(dry_run=dry_run, timeout=timeout)

    while True:
        try:
            prompt = input(f"{CYAN}{BOLD}sentry{RESET} {GREEN}❯{RESET} ").strip()
            if not prompt:
                continue

            if session.is_internal_command(prompt):
                turn_result = await session.process_input(prompt)
            else:
                loader = SentryLoader(message="Sentry processando...")
                async with loader:
                    turn_result = await session.process_input(
                        prompt,
                        on_status=loader.set_message,
                    )

            if turn_result.should_exit:
                if turn_result.internal_message:
                    print(f"{YELLOW}{turn_result.internal_message}{RESET}")
                break

            if turn_result.should_clear_terminal:
                print("\033[H\033[2J", end="")
                if turn_result.internal_message:
                    print(f"{GREEN}✔ {turn_result.internal_message}{RESET}\n")
                continue

            if turn_result.is_internal_command:
                if turn_result.internal_message:
                    print(f"{CYAN}{turn_result.internal_message}{RESET}\n")
                continue

            if turn_result.execution_result:
                print(format_cli_output(turn_result.execution_result, model_name=model_name))
                print()

        except (KeyboardInterrupt, EOFError):
            print(f"\n{YELLOW}Interrupção detectada. Sessão Sentry encerrada com segurança.{RESET}")
            break
        except Exception as e:
            print(f"{RED}Erro na execução do turno: {str(e)}{RESET}\n")


async def async_main(args: argparse.Namespace) -> int:
    """Ponto de entrada assíncrono principal."""
    llm_timeout = max(90.0, args.timeout)
    llm = OllamaProvider(base_url=args.base_url, model=args.model, timeout=llm_timeout)
    executor = AsyncBashExecutor()
    logger = ObsidianAuditLogger()
    bridge = SentryBridge(llm_provider=llm, executor=executor, audit_logger=logger)

    # 1. Modo Inspeção Direta
    if args.inspect:
        if not args.json and sys.stdout.isatty():
            loader = SentryLoader(message=f"Inspecionando {args.inspect}...")
            async with loader:
                result = await bridge.inspect(
                    args.inspect,
                    dry_run=args.dry_run,
                    timeout=args.timeout,
                    on_status=loader.set_message,
                )
        else:
            result = await bridge.inspect(args.inspect, dry_run=args.dry_run, timeout=args.timeout)

        if args.json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(format_cli_output(result, model_name=llm.model))
        return 0 if result.success else 1

    # 2. Modo Comando Bruto (Bypass de IA com Auditoria e Contenção)
    if args.raw_command:
        try:
            stmt = CommandStatement(args.raw_command)
        except SecurityViolationError as sec_err:
            print(f"{RED}{BOLD}VIOLAÇÃO DE SEGURANÇA:{RESET} {str(sec_err)}")
            return 2
        except ValueError as val_err:
            print(f"{RED}Comando inválido:{RESET} {str(val_err)}")
            return 2

        ctx = ExecutionContext(dry_run=args.dry_run, timeout_seconds=args.timeout)
        if args.dry_run:
            print(f"{YELLOW}[DRY-RUN]: O comando `{stmt.sanitized_str()}` foi validado mas não executado.{RESET}")
            return 0

        exec_res = await executor.execute(stmt, ctx)
        result = SentryExecutionResult(
            user_query=f"raw-command: {stmt.sanitized_str()}",
            command=stmt,
            execution=exec_res,
            llm_interpretation="Execução direta de comando sem interpretação LLM.",
            summary=exec_res.combined_output(),
            success=exec_res.is_success(),
        )
        await logger.log_execution(result)

        if args.json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(format_cli_output(result, model_name="RAW"))
        return 0 if result.success else 1

    # 3. Argumento direto de consulta
    if args.query:
        query_str = " ".join(args.query)
        if not args.json and sys.stdout.isatty():
            loader = SentryLoader(message="Sentry processando...")
            async with loader:
                result = await bridge.execute_turn(
                    query_str,
                    dry_run=args.dry_run,
                    timeout=args.timeout,
                    on_status=loader.set_message,
                )
        else:
            result = await bridge.execute_turn(query_str, dry_run=args.dry_run, timeout=args.timeout)

        if args.json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(format_cli_output(result, model_name=llm.model))
        return 0 if result.success else 1

    # 4. Sem argumentos: Inicia REPL interativo contínuo
    await run_repl(bridge, dry_run=args.dry_run, timeout=args.timeout, model_name=llm.model)
    return 0


def main() -> None:
    """Função invocada pelo ponto de entrada de linha de comando."""
    parser = argparse.ArgumentParser(
        prog="sentry",
        description="SENTRY CLI — Motor Operacional Homelab (CORE-0)",
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Instrução em linguagem natural para o Sentry (ex: 'verificar containers docker')",
    )
    parser.add_argument(
        "--inspect",
        choices=["docker", "storage", "systemd", "disks", "network", "logs", "memory"],
        help="Executa diagnóstico pré-calibrado direto no componente especificado",
    )
    parser.add_argument(
        "--raw-command",
        type=str,
        help="Executa comando shell direto com auditoria no Obsidian e contenção defensiva",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula a execução sem aplicar alterações no sistema operacional",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Tempo limite máximo para execução do comando em segundos (padrão: 30s)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Formata a saída estritamente em JSON estruturado",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Sobrescreve o modelo do Ollama local para este turno",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Sobrescreve a URL base do Ollama para este turno",
    )

    if sys.platform == "win32":
        try:
            import os
            os.system("")
        except Exception:
            pass

    args = parser.parse_args()

    try:
        exit_code = asyncio.run(async_main(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupção pelo operador. Homelab sob guarda.{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
