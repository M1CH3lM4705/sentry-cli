"""
Caso de uso: Inspeção Direta de Homelab (Docker, Storage, Systemd, Discos, Rede, Logs).
Executa diagnósticos de infraestrutura de alta confiabilidade com contenção e auditoria.
"""

import sys
from typing import Callable, Dict, Optional
from sentry_cli.domain.entities import SentryExecutionResult
from sentry_cli.domain.interfaces import IAuditLogger, ICommandExecutor, ILLMProvider
from sentry_cli.domain.value_objects import (
    CommandExecutionResult,
    CommandStatement,
    ExecutionContext,
)


class InspectHomelabUseCase:
    """
    Caso de uso especializado para inspeção de componentes fundamentais (Debian / Windows).
    Dispensa alucinação de comandos para verificações rotineiras pré-calibradas.
    """

    _INSPECTION_COMMANDS_LINUX: Dict[str, str] = {
        "docker": 'docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"',
        "storage": "df -h / /mnt/umbrel-pool /mnt/umbrel-disk2 2>/dev/null || df -h",
        "systemd": "systemctl --failed --no-legend --no-pager",
        "disks": "lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT,STATE",
        "network": "ip -brief address show; ip -brief route show default",
        "logs": "journalctl -p 3 -xb -n 25 --no-pager 2>/dev/null || dmesg -l err,crit | tail -n 20",
        "memory": "free -h",
    }

    _INSPECTION_COMMANDS_WINDOWS: Dict[str, str] = {
        "docker": 'docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"',
        "storage": "Get-PSDrive -PSProvider FileSystem | Select-Object Name, Used, Free",
        "systemd": 'Get-Service | Where-Object {$_.Status -eq "Running"} | Select-Object -First 25',
        "disks": "Get-PhysicalDisk | Select-Object DeviceId, FriendlyName, MediaType, OperationalStatus, Size",
        "network": 'Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.InterfaceAlias -notlike "*Loopback*"} | Select-Object InterfaceAlias, IPAddress',
        "logs": "Get-EventLog -LogName System -Newest 15 -EntryType Error,Warning",
        "memory": "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize, FreePhysicalMemory",
    }

    _INSPECTION_COMMANDS: Dict[str, str] = (
        _INSPECTION_COMMANDS_WINDOWS if sys.platform == "win32" else _INSPECTION_COMMANDS_LINUX
    )

    def __init__(
        self,
        executor: ICommandExecutor,
        audit_logger: IAuditLogger,
        llm_provider: Optional[ILLMProvider] = None,
    ) -> None:
        self._executor = executor
        self._logger = audit_logger
        self._llm = llm_provider

    def get_supported_components(self) -> list[str]:
        """Lista componentes suportados para inspeção direta."""
        return list(self._INSPECTION_COMMANDS.keys())

    async def execute(
        self,
        component: str,
        context: Optional[ExecutionContext] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> SentryExecutionResult:
        """Executa inspeção direcionada de um componente do Homelab."""
        normalized = component.strip().lower()
        ctx = context or ExecutionContext()

        if normalized not in self._INSPECTION_COMMANDS:
            return await self._handle_unknown_component(normalized)

        raw_cmd = self._INSPECTION_COMMANDS[normalized]
        command = CommandStatement(raw_cmd)

        if ctx.dry_run:
            return await self._handle_dry_run(normalized, command)

        return await self._handle_inspection_execution(
            normalized, command, ctx, on_status=on_status
        )

    async def _handle_unknown_component(
        self, component: str
    ) -> SentryExecutionResult:
        valid_options = ", ".join(self.get_supported_components())
        msg = f"Componente desconhecido '{component}'. Opções válidas: {valid_options}."
        result = SentryExecutionResult(
            user_query=f"Inspecionar {component}",
            command=None,
            execution=None,
            llm_interpretation="Componente inválido.",
            summary=msg,
            success=False,
        )
        await self._logger.log_execution(result)
        return result

    async def _handle_dry_run(
        self, component: str, command: CommandStatement
    ) -> SentryExecutionResult:
        simulated = CommandExecutionResult(
            exit_code=0,
            stdout=f"[DRY-RUN]: Inspeção de '{component}' executaria: `{command.sanitized_str()}`",
            stderr="",
            duration_ms=0.0,
            timed_out=False,
        )
        result = SentryExecutionResult(
            user_query=f"Inspecionar {component}",
            command=command,
            execution=simulated,
            llm_interpretation="Inspeção direta simulada.",
            summary=f"Inspeção de {component} validada em dry-run.",
            success=True,
        )
        await self._logger.log_execution(result)
        return result

    async def _handle_inspection_execution(
        self,
        component: str,
        command: CommandStatement,
        context: ExecutionContext,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> SentryExecutionResult:
        if on_status:
            on_status(f"Executando: {command.sanitized_str()}")

        execution_result = await self._executor.execute(command, context)

        summary = execution_result.combined_output()
        if self._llm:
            if on_status:
                on_status("Sintetizando diagnóstico...")

            def on_synth_token(count: int, chunk: str) -> None:
                if on_status:
                    on_status(f"Sintetizando diagnóstico... [{count} tokens]")

            summary = await self._llm.synthesize_response(
                f"Inspecionar {component}",
                command,
                execution_result,
                on_token=on_synth_token if on_status else None,
            )

        result = SentryExecutionResult(
            user_query=f"Inspecionar {component}",
            command=command,
            execution=execution_result,
            llm_interpretation=f"Inspeção do subsistema {component}.",
            summary=summary,
            success=execution_result.is_success(),
        )
        await self._logger.log_execution(result)
        return result
