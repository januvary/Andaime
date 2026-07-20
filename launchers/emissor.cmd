@echo off
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%..\apps"
cd /d "%HERE%..\apps"
start "" "%HERE%..\python\pythonw.exe" -m emissor
