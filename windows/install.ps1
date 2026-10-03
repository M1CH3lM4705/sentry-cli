<#
.SYNOPSIS
    Instalador e Atualizador Resiliente do SENTRY CLI para Windows (PowerShell & CMD).
.DESCRIPTION
    Realiza deteccao/instalacao do Python 3.10+, atualiza dependencias (httpx),
    instala o pacote desacoplado sentry_cli no ambiente, atualiza/substitui
    wrappers legados em $HOME\.sentry\bin e valida o Ollama local.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "      SENTRY CLI - Instalador e Atualizador para Windows        " -ForegroundColor Cyan
Write-Host "               Resiliente * Zero-Config * PowerShell/CMD        " -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# ==============================================================
# 0. RESOLUCAO SEGURA DE CAMINHOS
# ==============================================================
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }

$candidateParent = Join-Path $ScriptDir ".."
$candidateLocal = $ScriptDir

if (Test-Path (Join-Path $candidateParent "sentry_cli")) {
    $ProjectRoot = (Resolve-Path $candidateParent).Path
} elseif (Test-Path (Join-Path $candidateLocal "sentry_cli")) {
    $ProjectRoot = (Resolve-Path $candidateLocal).Path
} elseif (Test-Path (Join-Path $candidateParent "app\sentry_cli")) {
    $ProjectRoot = (Resolve-Path $candidateParent).Path
} else {
    $ProjectRoot = (Get-Location).Path
}

Write-Host "[0/4] Raiz do projeto SENTRY CLI detectada em:" -ForegroundColor Gray
Write-Host "      $ProjectRoot" -ForegroundColor DarkGray
Write-Host ""

# ==============================================================
# 1. DETECCAO E INSTALACAO AUTONOMA DO PYTHON
# ==============================================================
Write-Host "[1/4] Verificando interpretador Python funcional no sistema..." -ForegroundColor Yellow

function Test-PythonFunctional {
    try {
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        $output = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $prevEap

        if ($exitCode -eq 0 -and $output -match "^\d+\.\d+") {
            return $output.Trim()
        }
        return $null
    } catch {
        return $null
    }
}

function Test-PyLauncherFunctional {
    try {
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        $output = & py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $prevEap

        if ($exitCode -eq 0 -and $output -match "^\d+\.\d+") {
            return $output.Trim()
        }
        return $null
    } catch {
        return $null
    }
}

function Refresh-PathEnvironment {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = "$userPath;$machinePath"

    $commonDirs = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\Scripts"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\Scripts"),
        (Join-Path $env:ProgramFiles "Python312"),
        (Join-Path $env:ProgramFiles "Python312\Scripts")
    )
    foreach ($dir in $commonDirs) {
        if ((Test-Path $dir) -and ($env:Path -notlike "*$dir*")) {
            $env:Path = "$dir;$env:Path"
        }
    }
}

$pyVer = Test-PythonFunctional

if (-not $pyVer) {
    $pyLauncherVer = Test-PyLauncherFunctional
    if ($pyLauncherVer) {
        Write-Host "  [OK] Python Launcher (py) detectado: versao $pyLauncherVer" -ForegroundColor Green
        try {
            $realPyExe = & py -3 -c "import sys; print(sys.executable)" 2>&1
            $realPyDir = Split-Path -Parent $realPyExe
            $realScriptsDir = Join-Path $realPyDir "Scripts"
            $env:Path = "$realPyDir;$realScriptsDir;$env:Path"
            $pyVer = Test-PythonFunctional
        } catch {}
    }
}

if ($pyVer) {
    Write-Host "  [OK] Python funcional detectado: versao $pyVer" -ForegroundColor Green
} else {
    Write-Host "  [AVISO] Python nao encontrado no PATH." -ForegroundColor DarkYellow
    Write-Host "  Iniciando instalacao autonoma e silenciosa..." -ForegroundColor Cyan

    $installed = $false

    # Metodo A: winget
    if (Get-Command "winget" -ErrorAction SilentlyContinue) {
        Write-Host "  -> Tentando instalacao via winget (Python 3.12)..." -ForegroundColor Gray
        try {
            $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
            & winget install --id Python.Python.3.12 --exact --silent --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -eq 0) {
                $installed = $true
                Write-Host "  [OK] Instalacao via winget finalizada com sucesso." -ForegroundColor Green
            }
            $ErrorActionPreference = $prevEap
        } catch {
            Write-Host "  [AVISO] Execucao do winget falhou ou nao foi permitida." -ForegroundColor Gray
        }
    }

    # Metodo B: Download oficial silencioso
    if (-not $installed) {
        Write-Host "  -> Baixando instalador oficial do Python 3.12..." -ForegroundColor Gray
        $installerUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
        $installerPath = Join-Path $env:TEMP "python-3.12-installer.exe"
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
            Write-Host "  -> Executando instalador em modo silencioso (PrependPath=1)..." -ForegroundColor Gray
            $proc = Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait -PassThru
            if ($proc.ExitCode -eq 0) {
                $installed = $true
                Write-Host "  [OK] Instalador oficial executado com sucesso." -ForegroundColor Green
            }
            Remove-Item -Path $installerPath -Force -ErrorAction SilentlyContinue
        } catch {
            Write-Host "  [ERRO] Falha no download ou execucao do instalador oficial." -ForegroundColor DarkRed
        }
    }

    Refresh-PathEnvironment

    $pyVer = Test-PythonFunctional
    if ($pyVer) {
        Write-Host "  [OK] Python instalado e ativado na sessao: versao $pyVer" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "================================================================" -ForegroundColor Red
        Write-Host "          PRE-REQUISITO: INSTALACAO MANUAL DO PYTHON            " -ForegroundColor Red
        Write-Host "================================================================" -ForegroundColor Red
        Write-Host "Nao foi possivel instalar o Python automaticamente no seu ambiente." -ForegroundColor White
        Write-Host "Por favor, instale o Python 3.10+ manualmente:" -ForegroundColor Yellow
        Write-Host "  1. Acesse: https://www.python.org/downloads/" -ForegroundColor Cyan
        Write-Host "  2. Durante a instalacao, marque OBRIGATORIAMENTE a opcao:" -ForegroundColor Yellow
        Write-Host "     [X] Add Python to PATH" -ForegroundColor White
        Write-Host "  3. Em seguida, execute este instalador novamente." -ForegroundColor Gray
        Write-Host ""
        exit 1
    }
}

# ==============================================================
# 2. INSTALACAO RESILIENTE DE DEPENDENCIAS E PACOTE
# ==============================================================
Write-Host "[2/4] Instalando dependencias e registrando pacote sentry_cli..." -ForegroundColor Yellow

$prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
$pipOutput = & python -m pip install --quiet --upgrade --no-warn-script-location httpx 2>&1
$pipExitCode = $LASTEXITCODE
$ErrorActionPreference = $prevEap

if ($pipExitCode -eq 0) {
    Write-Host "  [OK] Dependencia 'httpx' verificada e instalada com sucesso." -ForegroundColor Green
} else {
    Write-Host "  [AVISO] Instalacao do 'httpx' retornou aviso (Codigo: $pipExitCode)." -ForegroundColor DarkYellow
}

# Instalacao em modo editavel do pacote sentry-cli se pyproject.toml existir
if (Test-Path (Join-Path $ProjectRoot "pyproject.toml")) {
    Write-Host "  -> Registrando pacote autônomo via pip (modo editável)..." -ForegroundColor Gray
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $pkgOutput = & python -m pip install --quiet --no-warn-script-location -e "$ProjectRoot" 2>&1
    $ErrorActionPreference = $prevEap
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] Pacote 'sentry-cli' registrado via pip com sucesso." -ForegroundColor Green
    }
}

# ==============================================================
# 3. VALIDACAO DO SERVICO OLLAMA LOCAL
# ==============================================================
Write-Host "[3/4] Verificando servico Ollama local no Windows (http://localhost:11434)..." -ForegroundColor Yellow
$ollamaUrl = "http://localhost:11434/api/tags"
try {
    $response = Invoke-RestMethod -Uri $ollamaUrl -Method Get -TimeoutSec 3 -ErrorAction Stop
    $modelCount = ($response.models | Measure-Object).Count
    Write-Host "  [OK] Ollama online! Modelos detectados: $modelCount" -ForegroundColor Green
    if ($modelCount -gt 0) {
        $modelNames = ($response.models | Select-Object -ExpandProperty name) -join ", "
        Write-Host "    Modelos disponiveis: $modelNames" -ForegroundColor Gray
    } else {
        Write-Host "    [AVISO] Nenhum modelo carregado no Ollama. Execute no terminal: ollama run gemma4:e2b" -ForegroundColor DarkYellow
    }
} catch {
    Write-Host "  [AVISO] Ollama nao respondeu em localhost:11434." -ForegroundColor DarkYellow
    Write-Host "    Certifique-se de que o aplicativo do Ollama esta rodando na bandeja do sistema." -ForegroundColor Gray
}

# ==============================================================
# 4. CONFIGURACAO E ATUALIZACAO DO COMANDO GLOBAL
# ==============================================================
Write-Host "[4/4] Configurando comando global 'sentry' no perfil do usuario..." -ForegroundColor Yellow

$sentryHome = Join-Path $HOME ".sentry"
$binDir = Join-Path $sentryHome "bin"

if (-not (Test-Path $binDir)) {
    New-Item -ItemType Directory -Path $binDir -Force | Out-Null
}

$sentryCmdPath = Join-Path $binDir "sentry.cmd"

# Verifica se existia wrapper legado apontando para app.sentry_cli
$isUpgrade = $false
if (Test-Path $sentryCmdPath) {
    $existingContent = Get-Content $sentryCmdPath -Raw
    if ($existingContent -match "app\.sentry_cli") {
        $isUpgrade = $true
        Write-Host "  [UPGRADE] Wrapper legado acoplado detectado. Migrando para sentry_cli..." -ForegroundColor Cyan
    }
}

# Gera o novo wrapper apontando para sentry_cli desacoplado
$cmdLines = @(
    "@echo off",
    "rem SENTRY CLI — Wrapper Global Desacoplado para Windows",
    "set `"PYTHONPATH=$ProjectRoot;%PYTHONPATH%`"",
    "python -m sentry_cli.interfaces.cli %*"
)
$cmdContent = $cmdLines -join "`r`n"
Set-Content -Path $sentryCmdPath -Value $cmdContent -Encoding ASCII

if ($isUpgrade) {
    Write-Host "  [OK] Wrapper legado atualizado com sucesso para o pacote autônomo sentry_cli." -ForegroundColor Green
} else {
    Write-Host "  [OK] Wrapper executavel configurado em: $sentryCmdPath" -ForegroundColor Green
}

# Adiciona permanentemente ao PATH de Usuario
$currentSysUserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentSysUserPath -notlike "*$binDir*") {
    $newSysUserPath = if ($currentSysUserPath) { "$binDir;$currentSysUserPath" } else { $binDir }
    [Environment]::SetEnvironmentVariable("Path", $newSysUserPath, "User")
    Write-Host "  [OK] Diretorio '$binDir' adicionado ao PATH de Usuario com sucesso." -ForegroundColor Green
} else {
    Write-Host "  [OK] Diretorio '$binDir' ja esta registrado no PATH de Usuario." -ForegroundColor Green
}

# Atualiza na sessao atual
if ($env:Path -notlike "*$binDir*") {
    $env:Path = "$binDir;$env:Path"
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "                 INSTALACAO/ATUALIZACAO CONCLUIDA!              " -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host "O comando 'sentry' ja esta pronto para uso nesta sessao e em novos terminais:" -ForegroundColor White
Write-Host "  sentry" -ForegroundColor Cyan
Write-Host ""
Write-Host "Exemplo de consulta em linguagem natural:" -ForegroundColor White
Write-Host '  sentry "como estao os containers docker e a memoria do sistema?"' -ForegroundColor Cyan
Write-Host ""
