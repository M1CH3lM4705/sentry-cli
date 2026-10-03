# SENTRY CLI — Instalação e Atualização para Windows

Este pacote permite instalar, executar e atualizar o **Sentry CLI** diretamente no **Windows** (PowerShell ou CMD), conectando automaticamente ao Ollama local com **Zero Configuração**.

---

## 🔄 Como Atualizar uma Instalação Antiga (Feita na versão acoplada)

Se você já tinha instalado o Sentry no Windows quando ele ainda era acoplado ao `personal-agent`, você tem duas formas simples de atualizar para a versão desacoplada autônoma:

### Método 1: Atualização Automática (Recomendado)
1. Baixe ou clone a versão mais recente deste repositório `sentry-cli`.
2. Abra a pasta `windows/` e dê um **duplo clique em `install.bat`** (ou execute `.\windows\install.ps1` no PowerShell).
3. O script detecta automaticamente o wrapper legado anterior em `$HOME\.sentry\bin\sentry.cmd`, substitui a chamada antiga `app.sentry_cli` pelo novo pacote autônomo `sentry_cli` e registra o pacote atualizado via pip.
4. Pronto! O comando global `sentry` já estará atualizado.

### Método 2: Atualização Direta via Git / Pip (PowerShell)
Se você utiliza Git e Pip no seu terminal Windows:
```powershell
# 1. Atualizar o repositório ou instalar direto do GitHub
pip install --upgrade git+https://github.com/M1CH3lM4705/sentry-cli.git

# 2. Opcional: remover o wrapper legado antigo para que o Windows execute o executável nativo do pip
Remove-Item -Path "$HOME\.sentry\bin\sentry.cmd" -Force -ErrorAction SilentlyContinue
```

---

## 🚀 Instalação do Zero no Windows

### Opção 1: Usando o Instalador Automático
1. Baixe ou clone o repositório `sentry-cli`.
2. Dê um duplo clique no arquivo `windows/install.bat` (ou execute `.\windows\install.ps1` no PowerShell).
3. O instalador:
   - Verifica o Python (3.10+); se não encontrar, oferece instalação automática silenciosa via winget/python.org.
   - Instala a dependência assíncrona necessária (`httpx`).
   - Registra o pacote `sentry_cli` em modo editável no seu ambiente.
   - Valida a conexão com o Ollama local em `http://localhost:11434`.
   - Registra o comando global `sentry` no seu Windows (`$HOME\.sentry\bin`).
4. Abra um novo terminal PowerShell ou CMD e digite:
   ```powershell
   sentry
   ```

### Opção 2: Instalação Manual via Pip
Na raiz do repositório clonado:
```powershell
pip install httpx
pip install -e .
```

### Opção 3: Execução Portátil (Sem Instalação)
Se você não deseja instalar nada no perfil do sistema, basta navegar até a pasta `windows/` e executar:
```cmd
sentry.bat "como estão os recursos da máquina?"
```

---

## ⚙ Zero Configuração e Recursos no Windows
* **Linguagem Natural:** Faça perguntas e diagnósticos de forma fluida. O Sentry traduz suas intenções em comandos nativos do PowerShell/CMD (processos, serviços, discos, memória, Docker, etc.).
* **Ollama Local:** Conexão automática em `http://localhost:11434`. Parâmetros customizados podem ser passados via flags:
  ```powershell
  sentry --model "gemma4:e2b" --base-url "http://localhost:11434"
  ```
* **Auditoria de Operações:** Histórico de auditoria registrado automaticamente em `~/.sentry/audit.md`.
