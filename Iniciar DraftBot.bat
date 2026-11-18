@echo off
chcp 65001 >nul
cd /d "%~dp0"
title DraftBot - deixe esta janela aberta
set "PY="
rem 1) Python portatil baixado pelo proprio DraftBot
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
rem 2) Python ja instalado no PC (Anaconda, py ou python)
if not defined PY if exist "%USERPROFILE%\anaconda3\python.exe" set "PY=%USERPROFILE%\anaconda3\python.exe"
if not defined PY call :try py
if not defined PY call :try python
rem 3) Nenhum: baixa o Python portatil oficial (python.org, ~11 MB, so na primeira vez)
if not defined PY call :download
if not defined PY (
  echo.
  echo Nao consegui preparar o Python. Verifique a internet ou instale em https://www.python.org/downloads/
  pause
  exit /b 1
)
"%PY%" draftbot.py
pause
exit /b 0

:try
%1 -c "import ssl,sys; sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1 && set "PY=%1"
exit /b 0

:download
echo Primeira execucao: baixando o Python portatil oficial (~11 MB) so para o DraftBot...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip' -OutFile 'python.zip'; Expand-Archive -Force 'python.zip' 'python'; Remove-Item 'python.zip'"
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
exit /b 0
