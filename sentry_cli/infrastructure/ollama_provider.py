"""
Adaptador de Infraestrutura: OllamaProvider implementando ILLMProvider.
Conecta ao serviço Ollama local com calibragem estrita para a CPU AMD FX-6300.
"""

import json
import os
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple
import httpx

try:
    from sentry_cli.config import get_ollama_base_url, get_sentry_local_model
except ImportError:
    def get_ollama_base_url() -> str:
        default_url = "http://localhost:11434" if sys.platform == "win32" else "http://127.0.0.1:11434"
        return os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_API_URL", default_url))

    def get_sentry_local_model() -> str:
        return os.getenv("SENTRY_LOCAL_MODEL", "gemma4:e2b")

from sentry_cli.domain.interfaces import ILLMProvider
from sentry_cli.domain.value_objects import (
    CommandExecutionResult,
    CommandStatement,
    ExecutionContext,
)


class OllamaProvider(ILLMProvider):
    """
    Provedor de LLM local via Ollama.
    Totalmente isolado sob a porta ILLMProvider, compatível com Linux e Windows.
    """

    DEFAULT_DECISION_PROMPT_LINUX = (
        "Você é o SENTRY (CORE-0), operador tático do homelab Debian com permissão total para inspecionar e gerenciar o sistema via comandos bash.\n"
        "O operador humano enviou uma mensagem em linguagem natural.\n\n"
        "DIRETRIZES DE DECISÃO:\n"
        "1. Se a mensagem for uma solicitação, dúvida ou pergunta sobre o estado, existência, saúde, uso ou configuração de componentes do homelab (Docker, containers, discos, storage, memória, CPU, processos, systemd, logs, rede, portas):\n"
        "   Você DEVE gerar o comando bash puro para inspecionar o sistema (ex: docker ps, free -h, df -h, systemctl status).\n"
        "   Mesmo que o operador pergunte de forma indireta ou em linguagem natural ('você pode me dizer...', 'tem algum container...', 'como estão os containers?', 'é necessário algum container estar rodando?'), gere SEMPRE o comando de inspeção!\n"
        "   Responda ESTRITAMENTE no formato:\n"
        "   COMANDO: <comando bash puro>\n"
        "   INTERPRETAÇÃO: <uma frase explicando o que o comando faz>\n\n"
        "2. NUNCA diga que não tem acesso aos containers, arquivos ou ao sistema operacional. Você tem acesso total executando comandos bash.\n\n"
        "3. Apenas se a mensagem for exclusivamente uma saudação social ou conversa geral sem nenhuma relação com infraestrutura (ex: 'olá', 'quem é você', 'me conte uma piada'), responda:\n"
        "   RESPOSTA: <sua resposta concisa em português>\n\n"
        "Não inclua blocos markdown extras ou explicações adicionais fora do formato."
    )

    DEFAULT_DECISION_PROMPT_WINDOWS = (
        "Você é o SENTRY (CORE-0), operador tático no ambiente Windows com permissão total para inspecionar o sistema via PowerShell/CMD.\n"
        "O operador humano enviou uma mensagem em linguagem natural.\n\n"
        "DIRETRIZES DE DECISÃO:\n"
        "1. Se a mensagem for uma solicitação, dúvida ou pergunta sobre o estado, existência, saúde, uso ou configuração de componentes locais (Docker, containers, discos, storage, memória, CPU, processos, serviços, rede, portas):\n"
        "   Você DEVE gerar o comando PowerShell/CMD puro para inspecionar a máquina (ex: docker ps, Get-Process, Get-Service).\n"
        "   Mesmo que o operador pergunte de forma indireta ou em linguagem natural ('você pode me dizer...', 'tem algum container...', 'como estão?'), gere SEMPRE o comando de inspeção!\n"
        "   Responda ESTRITAMENTE no formato:\n"
        "   COMANDO: <comando powershell puro>\n"
        "   INTERPRETAÇÃO: <uma frase explicando o que o comando faz>\n\n"
        "2. NUNCA diga que não tem acesso aos containers, arquivos ou ao sistema operacional. Você tem acesso total executando comandos PowerShell/CMD.\n\n"
        "3. Apenas se a mensagem for exclusivamente uma saudação social ou conversa geral sem nenhuma relação com infraestrutura (ex: 'olá', 'quem é você', 'me conte uma piada'), responda:\n"
        "   RESPOSTA: <sua resposta concisa em português>\n\n"
        "Não inclua blocos markdown extras ou explicações adicionais fora do formato."
    )

    DEFAULT_SYNTHESIS_PROMPT = (
        "Você é o SENTRY (CORE-0), operador tático operacional.\n"
        "Sintetize a saída do comando executado no sistema para o operador Michel.\n"
        "Diretrizes:\n"
        "• Responda em português em 2 a 4 frases concisas e objetivas.\n"
        "• Tom profissional, tático e levemente sarcástico/desenrolado de desenvolvedor pleno.\n"
        "• Destaque anomalias, erros ou confirme normalidade com números precisos."
    )

    @classmethod
    def get_default_decision_prompt(cls) -> str:
        if sys.platform == "win32":
            return cls.DEFAULT_DECISION_PROMPT_WINDOWS
        return cls.DEFAULT_DECISION_PROMPT_LINUX

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url or get_ollama_base_url()
        self.model = model or get_sentry_local_model()
        self.DEFAULT_DECISION_PROMPT = self.get_default_decision_prompt()
        self.timeout = httpx.Timeout(timeout, connect=10.0)
        self.options = {
            "num_thread": 5,
            "num_ctx": 2048,
            "num_predict": 150,
        }

    async def decide_action(
        self,
        user_intent: str,
        context: ExecutionContext,
        on_token: Optional[Callable[[int, str], None]] = None,
    ) -> Tuple[Optional[CommandStatement], str]:
        """Interpreta a intenção do usuário e extrai comando shell ou resposta conversacional com suporte a histórico contextual."""
        system_content = context.system_prompt or self.DEFAULT_DECISION_PROMPT
        messages = [{"role": "system", "content": system_content}]

        # Injeta histórico recente com janela deslizante limitada
        for msg in context.get_sliding_history():
            messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": f"Intenção: {user_intent}"})

        raw_reply = await self.chat(messages, on_token=on_token)

        return self._parse_decision_output(raw_reply)

    def _parse_decision_output(
        self, raw_reply: str
    ) -> Tuple[Optional[CommandStatement], str]:
        """Faz parsing seguro da saída do modelo sem depender de blocos markdown frágeis."""
        reply = raw_reply.strip()

        # Verifica formato padronizado COMANDO:
        if "COMANDO:" in reply:
            cmd_part = reply.split("COMANDO:")[1]
            lines = cmd_part.splitlines()
            raw_cmd = lines[0].strip()
            # Limpa possíveis crases ou blocos markdown inseridos
            raw_cmd = raw_cmd.strip("`").strip()

            interpretation = "Comando gerado para atendimento da solicitação."
            if "INTERPRETAÇÃO:" in reply:
                interp_part = reply.split("INTERPRETAÇÃO:")[1].strip()
                interpretation = interp_part.splitlines()[0].strip()

            try:
                command = CommandStatement(raw_cmd)
                return command, interpretation
            except ValueError as e:
                return None, f"Falha de validação do comando gerado: {str(e)}"

        # Verifica se gerou bloco de código bash
        bash_match = re.search(r"```(?:bash|sh)?\n?(.*?)\n?```", reply, re.DOTALL)
        if bash_match:
            raw_cmd = bash_match.group(1).strip()
            if raw_cmd:
                try:
                    return CommandStatement(raw_cmd), "Comando extraído de bloco de script."
                except ValueError as e:
                    return None, f"Falha de validação de comando em bloco: {str(e)}"

        # Se for resposta conversacional direta
        if "RESPOSTA:" in reply:
            clean_reply = reply.split("RESPOSTA:")[1].strip()
            return None, clean_reply

        # Fallback conversacional
        return None, reply

    async def synthesize_response(
        self,
        user_intent: str,
        command: CommandStatement,
        result: CommandExecutionResult,
        context: Optional[ExecutionContext] = None,
        on_token: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        """Sintetiza a saída da execução para o operador."""
        cmd_str = command.sanitized_str()
        output = result.combined_output()
        if len(output) > 1500:
            output = output[:1500] + "\n... [saída resumida para inferência local]"

        prompt = (
            f"Operação solicitada: {user_intent}\n"
            f"Comando executado: {cmd_str}\n"
            f"Código de retorno: {result.exit_code}\n"
            f"Saída do sistema:\n{output}"
        )

        messages = [
            {"role": "system", "content": self.DEFAULT_SYNTHESIS_PROMPT},
        ]
        if context:
            for msg in context.get_sliding_history():
                messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": prompt})

        return await self.chat(messages, on_token=on_token)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        on_token: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        """Envia mensagem ao Ollama com parâmetros de contenção e streaming opcional."""
        use_stream = on_token is not None
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": use_stream,
            "think": False,
            "options": self.options,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if use_stream:
                    chunks: List[str] = []
                    token_count = 0
                    async with client.stream(
                        "POST", f"{self.base_url}/api/chat", json=payload
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            data = json.loads(line)
                            message_dict = data.get("message", {})
                            content_piece = message_dict.get("content", "")
                            if content_piece:
                                chunks.append(content_piece)
                                token_count += 1
                                if on_token:
                                    on_token(token_count, content_piece)
                    full_content = "".join(chunks).strip()
                    if "</thought>" in full_content:
                        full_content = full_content.split("</thought>")[-1].strip()
                    return full_content or "[SENTRY]: Resposta recebida sem texto."

                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
                message_dict = data.get("message", {})
                content = message_dict.get("content", "").strip()
                if "</thought>" in content:
                    content = content.split("</thought>")[-1].strip()
                return content or "[SENTRY]: Resposta recebida sem texto."

        except httpx.ConnectError:
            return "[SENTRY OFFLINE]: Serviço Ollama inacessível em localhost:11434."
        except httpx.TimeoutException:
            return "[SENTRY TIMEOUT]: Processamento local excedeu a janela limite."
        except Exception as e:
            return f"[SENTRY ERRO]: {str(e)}"
