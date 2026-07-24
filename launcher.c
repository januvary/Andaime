/*
 * launcher.c — Smart Windows launcher for SISTEMAS apps.
 *
 * On first launch (or when the share's VERSION differs from the local copy):
 *   shows a progress dialog, then extracts dist.zip from the launcher's
 *   directory to %LOCALAPPDATA%\SISTEMAS\
 * On every launch:
 *   sets SISTEMAS_DATA_ROOT env var to the launcher's own directory,
 *   then runs %LOCALAPPDATA%\SISTEMAS\python\pythonw.exe -m <app>.
 *
 * The module name is derived from the .exe filename (bap.exe -> "bap").
 *
 * Compile (cross-compile on Linux):
 *   x86_64-w64-mingw32-gcc -O2 -s -o launcher.exe launcher.c -mwindows -static -lshlwapi -lcomctl32
 */

#include <windows.h>
#include <commctrl.h>
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

/* --- Progress dialog (shown during first install / update extraction) --- */
#define IDD_PROGRESS 100
#define IDC_PROGRESS 101

static INT_PTR CALLBACK progress_dlgproc(HWND, UINT, WPARAM, LPARAM);

static HWND
show_progress(void)
{
    INITCOMMONCONTROLSEX icc;
    icc.dwSize = sizeof(icc);
    icc.dwICC = ICC_PROGRESS_CLASS;
    InitCommonControlsEx(&icc);

    HINSTANCE hInst = GetModuleHandleA(NULL);
    HWND hdlg = CreateDialogA(hInst, MAKEINTRESOURCE(IDD_PROGRESS), NULL,
                              progress_dlgproc);
    if (hdlg) {
        HWND bar = GetDlgItem(hdlg, IDC_PROGRESS);
        if (bar) SendMessageA(bar, PBM_SETMARQUEE, TRUE, 0);
        ShowWindow(hdlg, SW_SHOW);
        UpdateWindow(hdlg);
    }
    return hdlg;
}

static INT_PTR CALLBACK
progress_dlgproc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    (void)wParam; (void)lParam;
    switch (msg) {
        case WM_INITDIALOG: {
            RECT r, dr;
            GetWindowRect(GetDesktopWindow(), &dr);
            GetWindowRect(hwnd, &r);
            int x = (dr.right - r.right) / 2;
            int y = (dr.bottom - r.bottom) / 2;
            SetWindowPos(hwnd, NULL, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER);
            return TRUE;
        }
        default:
            return FALSE;
    }
}

/* Run a command, pumping messages so the progress dialog keeps animating. */
static DWORD
run_and_pump(HWND hdlg, const char *cmd)
{
    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessA(NULL, (char *)cmd, NULL, NULL, FALSE,
                        CREATE_NO_WINDOW, NULL, NULL, &si, &pi))
        return (DWORD)-1;

    for (;;) {
        DWORD rc = MsgWaitForMultipleObjects(1, &pi.hProcess, FALSE,
                                              INFINITE, QS_ALLINPUT);
        if (rc == WAIT_OBJECT_0)
            break;
        MSG msg;
        while (PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE)) {
            if (!IsDialogMessageA(hdlg, &msg)) {
                TranslateMessage(&msg);
                DispatchMessageA(&msg);
            }
        }
    }

    DWORD exitCode = 1;
    GetExitCodeProcess(pi.hProcess, &exitCode);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return exitCode;
}

/* --- Main --- */

int WINAPI
WinMain(HINSTANCE hInst, HINSTANCE hPrev, LPSTR lpCmdLine, int nCmdShow)
{
    /* --- Own exe path + module name --- */
    char exePath[MAX_PATH];
    if (GetModuleFileNameA(NULL, exePath, MAX_PATH) == 0) {
        return 1;
    }

    const char *slash = strrchr(exePath, '\\');
    const char *base = slash ? slash + 1 : exePath;
    char appName[MAX_PATH];
    strncpy(appName, base, MAX_PATH - 1);
    appName[MAX_PATH - 1] = '\0';
    char *dot = strrchr(appName, '.');
    if (dot) *dot = '\0';

    /* Prevent multiple concurrent launcher instances (per-app) */
    char mutexName[128];
    snprintf(mutexName, sizeof(mutexName), "SISTEMAS_Launcher_%s", appName);
    HANDLE hMutex = CreateMutexA(NULL, TRUE, mutexName);
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        CloseHandle(hMutex);
        return 0;
    }

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
        HWND hdlg = show_progress();
        tarExit = run_and_pump(hdlg, tarCmd);
        if (hdlg) DestroyWindow(hdlg);
        if (tarExit != 0) {
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
