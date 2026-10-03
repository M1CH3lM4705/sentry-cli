# SENTRY CLI (CORE-0)

[![Release](https://img.shields.io/badge/version-v0.1.1-blue.svg)](https://github.com/M1CH3lM4705/sentry-cli/releases)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Architecture](https://img.shields.io/badge/architecture-Clean%20Architecture-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**SENTRY CLI** is an autonomous tactical operations engine and system operator for Debian Homelab servers, powered by local LLMs via Ollama (`gemma4:e2b` or any compatible model).

Designed with strict **Clean Architecture**, **SOLID principles**, and **Ports & Adapters**, Sentry translates natural language intentions into safe shell commands, executes pre-calibrated system inspections, displays real-time telemetry streaming, and writes an immutable audit trail directly to an Obsidian Vault or markdown log.

---

## Key Features

- **Real-Time Telemetry & Token Streaming**: Live token generation counter and command execution status in modern CLI style.
- **Modern Code CLI UI**: Box-drawing characters (`╭─`, `│`, `╰─`), status badges, exit codes, and clean output synthesis inspired by modern developer CLIs.
- **Dual Execution Modes**:
  - **Single Turn**: Instant diagnosis or execution (`sentry "verificar containers docker"`).
  - **Interactive REPL Session**: Continuous conversational session with sliding window context memory (`sentry ❯`).
- **Pre-Calibrated Hallucination-Free Inspections**: Built-in deterministic diagnostics for `docker`, `storage`, `systemd`, `disks`, `network`, `logs`, and `memory`.
- **Dry-Run & Safe Bypasses**: Simulate actions before execution (`--dry-run`) or dispatch audited raw bash commands (`--raw-command`).
- **Immutable Audit Trail**: Async, fail-safe logging of every action, command, and diagnosis directly into your Obsidian Vault or `~/.sentry/audit.md`.
- **Cross-Platform**: Native support for Linux (Debian, Ubuntu, UmbrelOS) and Windows PowerShell/CMD.

---

## Architecture Overview

```
sentry_cli/
├── domain/                  # Enterprise Rules & Ports
│   ├── entities.py          # SentryExecutionResult, CommandStatement
│   ├── interfaces.py        # ILLMProvider, ICommandExecutor, IAuditLogger
│   └── value_objects.py     # ExecutionContext, CommandExecutionResult
├── application/             # Application Business Rules (Use Cases)
│   ├── execute_sentry_turn.py
│   ├── inspect_homelab.py
│   └── interactive_session.py
├── infrastructure/          # Adapters (Ollama, Bash, Obsidian)
│   ├── async_bash_executor.py
│   ├── ollama_provider.py
│   └── obsidian_audit_logger.py
└── interfaces/              # Presentation & CLI entrypoint
    ├── cli.py               # Argument parser, REPL, and output formatter
    ├── bridge.py            # Programmatic Python API for agents
    └── loader.py            # Async spinner and telemetry display
```

---

## Installation

### From Source (Editable / Development)

```bash
git clone https://github.com/M1CH3lM4705/sentry-cli.git
cd sentry-cli
pip install -e .
```

### With pipx (Isolated Global CLI)

```bash
pipx install git+https://github.com/M1CH3lM4705/sentry-cli.git
```

---

## Usage

### 1. Interactive Session (REPL)
Launch the interactive shell with continuous conversational memory:
```bash
sentry
```
```text
╭──────────────────────────────────────────────────────────────╮
│  SENTRY (CORE-0) — Operador Tático do Homelab                │
│  Modelo: gemma4:e2b | Contexto: 6 turnos | /help para auxílio │
╰──────────────────────────────────────────────────────────────╯

sentry ❯ verificar uso de memoria e swap
⠙  SENTRY | gerando tokens: 14...
⠸  SENTRY | Executando: free -h...
╭─ Execução de Ferramenta ────────────────────────────────────
│  $ free -h
│  total        used        free      shared  buff/cache   available
│  Mem:           15Gi       4.8Gi       1.2Gi       210Mi       9.8Gi       10Gi
│  Swap:         8.0Gi       1.1Gi       6.9Gi
╰─ ✔ código 0 (12ms) ──────────────────────────────────────────

O servidor possui 15 GiB de memória física total, com 4.8 GiB em uso e 10 GiB disponíveis. A swap está consumindo 1.1 GiB de 8.0 GiB.
● sentry • gemma4:e2b
```

Inside the interactive shell:
- `/clear` - Clears screen and flushes turn buffer.
- `/history` - Displays current retained turns.
- `/exit` or `exit` / `sair` - Exits gracefully.

### 2. Single-Turn Execution
```bash
sentry "qual a integridade dos discos e temperatura?"
```

### 3. Pre-Calibrated Inspections
Deterministic, zero-hallucination system health checks:
```bash
sentry --inspect docker
sentry --inspect storage
sentry --inspect systemd
sentry --inspect memory
sentry --inspect disks
sentry --inspect network
sentry --inspect logs
```

For JSON output (automation pipelines):
```bash
sentry --inspect storage --json
```

### 4. Safety Modes
Simulate execution without running commands on the host:
```bash
sentry --dry-run "reiniciar servico do docker"
```

Audit and execute a raw shell command directly:
```bash
sentry --raw-command "docker ps -a"
```

---

## Configuration

Sentry works out of the box with zero configuration, but respects standard environment variables:

| Variable | Default (Linux) | Default (Windows) | Description |
|---|---|---|---|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | `http://localhost:11434` | Endpoint for Ollama API |
| `SENTRY_LOCAL_MODEL` | `gemma4:e2b` | `gemma4:e2b` | Ollama model tag |
| `SENTRY_AUDIT_PATH` | Vault path or `~/.sentry/audit.md` | `~/.sentry/audit.md` | Target markdown file for execution audits |

---

## Programmatic Python API (`SentryBridge`)

You can integrate Sentry directly into other Python applications or agents without spawning shell subprocesses:

```python
from sentry_cli.interfaces.bridge import SentryBridge

bridge = SentryBridge()

# 1. Single natural language turn
resultado = await bridge.execute_turn("como estão os containers?")
print(resultado.summary)
print(resultado.execution.stdout)

# 2. Interactive session with memory
session = bridge.create_interactive_session()
turn = await session.process_input("verificar uso de disco")
print(turn.execution_result.summary)
```

---

## Testing

Run the comprehensive unit test suite:

```bash
pytest
```

---

## Lineage & Credits

Originating from the **Personal Agent** operational ecosystem as the **CORE-0** tactical kernel, Sentry CLI was decoupled into an independent open-source project to serve as a universal, resilient local operations assistant for homelabs and servers.

Developed by [Michel Matos](https://github.com/M1CH3lM4705). Licensed under the [MIT License](LICENSE).
