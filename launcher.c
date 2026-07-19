/*
 * launcher.c — Generic Windows .exe launcher for SISTEMAS apps.
 *
 * Derives the module name from its own filename (bap.exe → "bap"),
 * then runs:  ..\python\pythonw.exe -m <name>   from ..\apps\
 *
 * (cwd must be ..\apps\ — the parent of the package dir — so that
 *  "python -m bap" can import the bap package via apps\bap\__init__.py)
 *
 * Compile (cross-compile on Linux):
 *   x86_64-w64-mingw32-gcc -o launcher.exe launcher.c -mwindows -static -s
 *
 * Copy as bap.exe / emissor.exe.
 */

#include <windows.h>
#include <string.h>
#include <stdio.h>

int WINAPI
WinMain(HINSTANCE hInst, HINSTANCE hPrev, LPSTR lpCmdLine, int nCmdShow)
{
    char exePath[MAX_PATH];
    DWORD pathLen = GetModuleFileNameA(NULL, exePath, MAX_PATH);
    if (pathLen == 0 || pathLen >= MAX_PATH)
        return 1;

    /* --- App name = filename without extension --- */
    const char *slash = strrchr(exePath, '\\');
    const char *base  = slash ? slash + 1 : exePath;
    char appName[MAX_PATH];
    strncpy(appName, base, MAX_PATH - 1);
    appName[MAX_PATH - 1] = '\0';
    char *dot = strrchr(appName, '.');
    if (dot)
        *dot = '\0';

    /* --- Exe directory (with trailing backslash) --- */
    char exeDir[MAX_PATH];
    strncpy(exeDir, exePath, MAX_PATH - 1);
    exeDir[MAX_PATH - 1] = '\0';
    char *lastSlash = strrchr(exeDir, '\\');
    if (!lastSlash)
        return 1;
    lastSlash[1] = '\0';

    /* --- Resolve relative paths --- */
    char pythonExe[MAX_PATH * 2];
    char workDir[MAX_PATH * 2];
    char cmdLine[MAX_PATH * 4];

    snprintf(pythonExe, sizeof(pythonExe),
             "%s..\\python\\pythonw.exe", exeDir);
    snprintf(workDir, sizeof(workDir),
             "%s..\\apps", exeDir);

    if (lpCmdLine && lpCmdLine[0])
        snprintf(cmdLine, sizeof(cmdLine),
                 "\"%s\" -m %s %s", pythonExe, appName, lpCmdLine);
    else
        snprintf(cmdLine, sizeof(cmdLine),
                 "\"%s\" -m %s", pythonExe, appName);

    /* --- Launch --- */
    STARTUPINFOA si;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_SHOWNORMAL;

    PROCESS_INFORMATION pi;
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessA(
            pythonExe,
            cmdLine,
            NULL, NULL,
            FALSE,
            0,
            NULL,
            workDir,
            &si, &pi))
    {
        char msg[512];
        snprintf(msg, sizeof(msg),
                 "Failed to start %s.\n\n"
                 "Python: %s\n"
                 "WorkDir: %s\n"
                 "Error: %lu",
                 appName, pythonExe, workDir, GetLastError());
        MessageBoxA(NULL, msg, "SISTEMAS Launcher", MB_ICONERROR | MB_OK);
        return 1;
    }

    CloseHandle(pi.hThread);
    WaitForSingleObject(pi.hProcess, INFINITE);

    DWORD exitCode = 0;
    GetExitCodeProcess(pi.hProcess, &exitCode);
    CloseHandle(pi.hProcess);
    return (int)exitCode;
}
