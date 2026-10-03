@echo off
rem SENTRY CLI — Wrapper CMD Portatil para Windows (CORE-0)
setlocal
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.."
set "PROJECT_ROOT=%CD%"
popd
set "PYTHONPATH=%PROJECT_ROOT%;%PYTHONPATH%"
python -m sentry_cli.interfaces.cli %*
endlocal
