"""
Componente visual de carregamento (Loader / Spinner) para o Sentry CLI.
Projetado para operações táticas assíncronas com contenção visual no terminal Debian.
"""

import asyncio
import sys
from typing import Optional, TextIO


class SentryLoader:
    """
    Spinner visual assíncrono para o terminal do Sentry CLI.
    Fornece feedback visual fluido durante turnos de inferência de IA e execuções no SO.
    Pode ser utilizado como context manager assíncrono ou explicitamente via start/stop.
    """

    SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    FALLBACK_FRAMES = ("|", "/", "-", "\\")

    # Sequências ANSI para controle do terminal
    CYAN = "\033[36m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
    GRAY = "\033[90m"
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    HIDE_CURSOR = "\033[?25l"
    SHOW_CURSOR = "\033[?25h"
    CLEAR_LINE = "\r\033[K"

    def __init__(
        self,
        message: str = "Sentry processando...",
        interval: float = 0.08,
        stream: Optional[TextIO] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self._message = message
        self._interval = interval
        self._stream = stream or sys.stdout
        self._enabled = enabled if enabled is not None else self._is_tty()
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def _is_tty(self) -> bool:
        """Verifica se o fluxo de saída é um terminal TTY interativo."""
        return getattr(self._stream, "isatty", lambda: False)()

    @property
    def is_running(self) -> bool:
        """Indica se o loader está ativamente em execução."""
        return self._running

    @property
    def message(self) -> str:
        """Retorna a mensagem atual do loader."""
        return self._message

    def set_message(self, message: str) -> None:
        """Permite atualizar a mensagem exibida enquanto o loader gira."""
        self._message = message

    async def start(self) -> None:
        """Inicia a animação do loader em background."""
        if self._running or not self._enabled:
            return

        self._running = True
        self._stop_event.clear()

        # Oculta o cursor para evitar tremor visual na linha
        try:
            self._stream.write(self.HIDE_CURSOR)
            self._stream.flush()
        except Exception:
            pass

        self._task = asyncio.create_task(self._spin())

    async def stop(self) -> None:
        """Para a animação do loader e limpa a linha no terminal com segurança."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._enabled:
            try:
                # Limpa a linha atual e restaura a visibilidade do cursor
                self._stream.write(f"{self.CLEAR_LINE}{self.SHOW_CURSOR}")
                self._stream.flush()
            except Exception:
                pass

    def _format_message(self, raw_msg: str) -> str:
        """Formata dinamicamente mensagens táticas destacando comandos e contadores de tokens."""
        if not raw_msg:
            return ""
        if raw_msg.startswith("Executando:"):
            cmd_part = raw_msg[len("Executando:"):].strip()
            return f"{self.GRAY}Executando:{self.RESET} {self.YELLOW}{self.BOLD}{cmd_part}{self.RESET}"
        if "[" in raw_msg and "tokens]" in raw_msg:
            prefix, token_part = raw_msg.split("[", 1)
            return f"{self.GRAY}{prefix}{self.RESET}{self.CYAN}[{token_part}{self.RESET}"
        return f"{self.GRAY}{raw_msg}{self.RESET}"

    async def _spin(self) -> None:
        """Loop de animação que cicla os frames do spinner."""
        frames = self.SPINNER_FRAMES
        # Testa se a codificação suporta caracteres unicode dos frames
        try:
            encoding = getattr(self._stream, "encoding", "utf-8") or "utf-8"
            "⠋".encode(encoding)
        except (UnicodeEncodeError, LookupError):
            frames = self.FALLBACK_FRAMES

        idx = 0
        total_frames = len(frames)

        try:
            while not self._stop_event.is_set():
                frame = frames[idx % total_frames]
                formatted_msg = self._format_message(self._message)
                text = (
                    f"{self.CLEAR_LINE}"
                    f"{self.CYAN}{self.BOLD}{frame}{self.RESET} "
                    f"{formatted_msg}"
                )
                try:
                    self._stream.write(text)
                    self._stream.flush()
                except Exception:
                    break

                idx += 1
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._interval
                    )
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass

    async def __aenter__(self) -> "SentryLoader":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()
