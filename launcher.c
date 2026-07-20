/*
 * launcher.c — Smart Windows launcher for SISTEMAS apps.
 *
 * On first launch (or when the share's VERSION differs from the local copy):
 *   extracts dist.zip from the launcher's directory to %LOCALAPPDATA%\SISTEMAS\
 * On every launch:
 *   sets SISTEMAS_DATA_ROOT env var to the launcher's own directory,
 *   then runs %LOCALAPPDATA%\SISTEMAS\python\pythonw.exe -m <app>.
 *
 * The module name is derived from the .exe filename (bap.exe -> "bap").
 *
 * Compile (cross-compile on Linux):
 *   x86_64-w64-mingw32-gcc -O2 -s -o launcher.exe launcher.c -mwindows -static -lshlwapi
 */

#include <windows.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

/* --- Helpers --- */

static int
read_version_file(const char *path, char *buf, size_t bufsize)
{
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    if (!fgets(buf, bufsize, f)) { fclose(f); return -1; }
    fclose(f);
    size_t len = strlen(buf);
    while (len > 0 && (buf[len-1] == '\n' || buf[len-1] == '\r' ||
                       buf[len-1] == ' '  || buf[len-1] == '\t'))
        buf[--len] = '\0';
    return 0;
}

static int
run_hidden_and_wait(const char *cmd, DWORD *exitCode)
{
    char cmdBuf[MAX_PATH * 8];
    strncpy(cmdBuf, cmd, sizeof(cmdBuf) - 1);
    cmdBuf[sizeof(cmdBuf) - 1] = '\0';

    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessA(NULL, cmdBuf, NULL, NULL, FALSE,
                        CREATE_NO_WINDOW, NULL, NULL, &si, &pi))
        return -1;

    WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, exitCode);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}

/* --- Main --- */

int WINAPI
WinMain(HINSTANCE hInst, HINSTANCE hPrev, LPSTR lpCmdLine, int nCmdShow)
{
    /* Prevent multiple concurrent launcher instances */
    HANDLE hMutex = CreateMutexA(NULL, TRUE, "SISTEMAS_Launcher");
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        CloseHandle(hMutex);
        return 0;
    }

    /* --- Own exe path + module name --- */
    char exePath[MAX_PATH];
    if (GetModuleFileNameA(NULL, exePath, MAX_PATH) == 0) {
        ReleaseMutex(hMutex);
        return 1;
    }

    const char *slash = strrchr(exePath, '\\');
    const char *base = slash ? slash + 1 : exePath;
    char appName[MAX_PATH];
    strncpy(appName, base, MAX_PATH - 1);
    appName[MAX_PATH - 1] = '\0';
    char *dot = strrchr(appName, '.');
    if (dot) *dot = '\0';

    /* --- Own directory (share root, with trailing backslash) --- */
    char exeDir[MAX_PATH];
    strncpy(exeDir, exePath, MAX_PATH - 1);
    exeDir[MAX_PATH - 1] = '\0';
    char *lastSlash = strrchr(exeDir, '\\');
    if (!lastSlash) { ReleaseMutex(hMutex); return 1; }
    lastSlash[1] = '\0';

    /* --- %LOCALAPPDATA%\SISTEMAS --- */
    const char *lad = getenv("LOCALAPPDATA");
    if (!lad) {
        MessageBoxA(NULL, "Cannot determine LOCALAPPDATA.",
                    "SISTEMAS", MB_ICONERROR | MB_OK);
        ReleaseMutex(hMutex);
        return 1;
    }
    char localSistemas[MAX_PATH];
    snprintf(localSistemas, sizeof(localSistemas), "%s\\SISTEMAS", lad);

    /* --- Compare VERSION files --- */
    char shareVer[64] = "", localVer[64] = "";
    char pathBuf[MAX_PATH * 2];

    snprintf(pathBuf, sizeof(pathBuf), "%sVERSION", exeDir);
    read_version_file(pathBuf, shareVer, sizeof(shareVer));

    snprintf(pathBuf, sizeof(pathBuf), "%s\\VERSION", localSistemas);
    read_version_file(pathBuf, localVer, sizeof(localVer));

    /* --- Check if local Python exists --- */
    char localPython[MAX_PATH * 2];
    snprintf(localPython, sizeof(localPython),
             "%s\\python\\pythonw.exe", localSistemas);
    DWORD attr = GetFileAttributesA(localPython);
    int pythonExists = (attr != INVALID_FILE_ATTRIBUTES &&
                        !(attr & FILE_ATTRIBUTE_DIRECTORY));

    /* --- Install / update if needed --- */
    if (!pythonExists || strcmp(shareVer, localVer) != 0) {
        char distZip[MAX_PATH * 2];
        snprintf(distZip, sizeof(distZip), "%sdist.zip", exeDir);

        DWORD zipAttr = GetFileAttributesA(distZip);
        if (zipAttr == INVALID_FILE_ATTRIBUTES ||
            (zipAttr & FILE_ATTRIBUTE_DIRECTORY)) {
            char msg[512];
            snprintf(msg, sizeof(msg),
                     "SISTEMAS needs setup but dist.zip was not found:\n%s\n\n"
                     "Please contact your administrator.", distZip);
            MessageBoxA(NULL, msg, "SISTEMAS", MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }

        /* Extract dist.zip to %LOCALAPPDATA% (creates SISTEMAS\ subtree) */
        char tarCmd[MAX_PATH * 8];
        snprintf(tarCmd, sizeof(tarCmd),
                 "cmd.exe /c tar -xf \"%s\" -C \"%s\"",
                 distZip, lad);

        DWORD tarExit = 1;
        if (run_hidden_and_wait(tarCmd, &tarExit) != 0 || tarExit != 0) {
            char msg[512];
            snprintf(msg, sizeof(msg),
                     "Installation failed (tar exit code %lu).\n"
                     "Source: %s", tarExit, distZip);
            MessageBoxA(NULL, msg, "SISTEMAS", MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }

        /* Verify pythonw.exe appeared */
        attr = GetFileAttributesA(localPython);
        if (attr == INVALID_FILE_ATTRIBUTES ||
            (attr & FILE_ATTRIBUTE_DIRECTORY)) {
            MessageBoxA(NULL,
                        "Installation completed but pythonw.exe not found.\n"
                        "The dist.zip may be corrupted.",
                        "SISTEMAS", MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }
    }

    /* --- Tell the app where the network data lives --- */
    SetEnvironmentVariableA("SISTEMAS_DATA_ROOT", exeDir);

    /* --- Launch pythonw.exe -m <appName> from apps\ --- */
    char workDir[MAX_PATH * 2];
    snprintf(workDir, sizeof(workDir), "%s\\apps", localSistemas);

    char cmdLine[MAX_PATH * 4];
    if (lpCmdLine && lpCmdLine[0])
        snprintf(cmdLine, sizeof(cmdLine),
                 "\"%s\" -m %s %s", localPython, appName, lpCmdLine);
    else
        snprintf(cmdLine, sizeof(cmdLine),
                 "\"%s\" -m %s", localPython, appName);

    STARTUPINFOA si;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);

    PROCESS_INFORMATION pi;
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessA(localPython, cmdLine, NULL, NULL, FALSE,
                        0, NULL, workDir, &si, &pi)) {
        char msg[512];
        snprintf(msg, sizeof(msg),
                 "Failed to start %s.\n\nPython: %s\nError: %lu",
                 appName, localPython, GetLastError());
        MessageBoxA(NULL, msg, "SISTEMAS", MB_ICONERROR | MB_OK);
        ReleaseMutex(hMutex);
        return 1;
    }

    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    ReleaseMutex(hMutex);
    return 0;
}
