@echo off
chcp 65001 >nul 2>&1
setlocal

set "DIR=%~dp0"
set "DIR=%DIR:~0,-1%"

:menu
cls
echo.
echo   SISTEMAS - Criar Atalho
echo   ========================
echo.
echo   1. BAP
echo   2. Emissor
echo   3. Sair
echo.
set /p "app=Escolha (1-3): "

if "%app%"=="3" exit /b 0
if "%app%"=="1" ( set "EXE=bap.exe"     & set "NAME=BAP"     )
if "%app%"=="2" ( set "EXE=emissor.exe" & set "NAME=Emissor" )
if not defined EXE (
    echo   Escolha invalida.
    timeout /t 2 >nul
    goto menu
)

echo.
echo   Onde criar o atalho?
echo     1  Area de Trabalho
echo     2  Menu Iniciar
echo     3  Caminho personalizado
echo.
set /p "loc=Local (1-3): "

if "%loc%"=="1" (
    for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "OUTDIR=%%D"
) else if "%loc%"=="2" (
    set "OUTDIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\SISTEMAS"
) else if "%loc%"=="3" (
    echo.
    set /p "OUTDIR=Caminho da pasta: "
) else (
    echo   Opcao invalida.
    timeout /t 2 >nul
    goto menu
)

if not defined OUTDIR (
    echo   Caminho vazio.
    pause
    goto menu
)

if not exist "%OUTDIR%" mkdir "%OUTDIR%" 2>nul
if not exist "%OUTDIR%" (
    echo   Nao foi possivel criar/acessar: %OUTDIR%
    pause
    goto menu
)

set "OUTPATH=%OUTDIR%\%NAME%.lnk"

:: Pass paths via env vars to avoid quoting issues in PowerShell
set "PS_TARGET=%DIR%\%EXE%"
set "PS_OUTPATH=%OUTPATH%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$sc = $ws.CreateShortcut($env:PS_OUTPATH);" ^
  "$sc.TargetPath = $env:PS_TARGET;" ^
  "$sc.WorkingDirectory = $env:DIR;" ^
  "$sc.Description = 'SISTEMAS - %NAME%';" ^
  "$sc.Save();"

if exist "%OUTPATH%" (
    echo.
    echo   OK! Atalho criado:
    echo   %OUTPATH%
) else (
    echo.
    echo   FALHA ao criar atalho.
)
echo.
pause
