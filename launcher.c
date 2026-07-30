/*
 * launcher.c — Smart Windows launcher for SISTEMAS apps.
 *
 * Two modes, selected at compile time:
 *
 *   1. Standalone (APP_REPO defined):
 *      First launch downloads payload.zip from GitHub Releases
 *      to %LOCALAPPDATA%\SISTEMAS\<module>\.
 *      Subsequent launches skip download if local install exists.
 *
 *   2. SISTEMAS multi-app (APP_REPO NOT defined — legacy):
 *      Extracts dist.zip from the launcher's own directory
 *      to %LOCALAPPDATA%\SISTEMAS\ (shared across apps).
 *
 * Both modes:
 *   - Set SISTEMAS_DATA_ROOT env var to the launcher's own directory.
 *   - Launch pythonw.exe -m <appName> from the local install.
 *   - Derive module name from the .exe filename (bap.exe → "bap").
 *
 * Compile (standalone):
 *   x86_64-w64-mingw32-gcc -O2 -s -o rac.exe launcher.c \
 *       -DAPP_REPO=\"januvary/RAC\" -DAPP_MODULE=\"rac\" \
 *       -DAPP_DISPLAY=\"RAC\" \
 *       -mwindows -static -lshlwapi -lcomctl32 -lwininet
 *
 * Compile (legacy SISTEMAS):
 *   x86_64-w64-mingw32-gcc -O2 -s -o rac.exe launcher.c \
 *       -mwindows -static -lshlwapi -lcomctl32
 */

#include <windows.h>
#include <commctrl.h>
#include <shlwapi.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

#ifdef APP_REPO
#include <wininet.h>
#endif

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
write_file(const char *path, const char *content)
{
    FILE *f = fopen(path, "w");
    if (!f) return -1;
    fputs(content, f);
    fclose(f);
    return 0;
}

/* --- Progress dialog --- */
#define IDD_PROGRESS 100
#define IDC_PROGRESS 101

static INT_PTR CALLBACK progress_dlgproc(HWND, UINT, WPARAM, LPARAM);

static HWND
show_progress(const char *caption)
{
    INITCOMMONCONTROLSEX icc;
    icc.dwSize = sizeof(icc);
    icc.dwICC = ICC_PROGRESS_CLASS;
    InitCommonControlsEx(&icc);

    /* Build dialog template dynamically so we can customize the caption. */
    HINSTANCE hInst = GetModuleHandleA(NULL);

    /* Use a simple window instead of a dialog template for flexibility. */
    HWND hdlg = CreateWindowExA(
        WS_EX_DLGMODALFRAME | WS_EX_TOPMOST,
        "STATIC", caption ?: "SISTEMAS",
        SS_LEFT | WS_VISIBLE | WS_POPUP | WS_CAPTION,
        CW_USEDEFAULT, CW_USEDEFAULT, 360, 130,
        NULL, NULL, hInst, NULL);

    if (!hdlg) return NULL;

    /* Replace the static control with a proper dialog-like layout. */
    SetWindowTextA(hdlg, caption ?: "SISTEMAS");

    HWND hBar = CreateWindowExA(
        0, PROGRESS_CLASSA, NULL,
        WS_CHILD | WS_VISIBLE | PBS_MARQUEE,
        20, 70, 320, 18,
        hdlg, (HMENU)IDC_PROGRESS, hInst, NULL);

    if (hBar)
        SendMessageA(hBar, PBM_SETMARQUEE, TRUE, 0);

    /* Center on screen */
    RECT r, dr;
    GetWindowRect(GetDesktopWindow(), &dr);
    GetWindowRect(hdlg, &r);
    /* Adjust rect — CreateWindowEx used default size */
    GetClientRect(hdlg, &r);
    int w = 360, h = 130;
    int x = (dr.right - dr.left - w) / 2;
    int y = (dr.bottom - dr.top - h) / 2;
    SetWindowPos(hdlg, NULL, x, y, w, h, SWP_NOZORDER);

    ShowWindow(hdlg, SW_SHOW);
    UpdateWindow(hdlg);
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

/* Pump messages while waiting for a process (keeps UI alive). */
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

#ifdef APP_REPO
/* --- GitHub download (standalone mode) --- */

/*
 * Download a URL to a file using WinINet.
 * Updates the progress bar on hdlg if provided.
 *
 * This version uses HttpOpenRequestA so we can set the User-Agent
 * and Accept headers required by the GitHub API.
 */
static int
http_download(const char *url, const char *destPath, HWND hdlg)
{
    HINTERNET hInternet = InternetOpenA(
        "SISTEMAS-Launcher",
        INTERNET_OPEN_TYPE_PRECONFIG,
        NULL, NULL, 0);
    if (!hInternet) return -1;

    /* Parse URL into host, port, path, scheme. */
    URL_COMPONENTSA uc;
    char scheme[32] = "";
    char host[256] = "";
    char path[4096] = "";
    char extra[1024] = "";

    ZeroMemory(&uc, sizeof(uc));
    uc.dwStructSize = sizeof(uc);
    uc.lpszScheme = scheme;
    uc.dwSchemeLength = sizeof(scheme);
    uc.lpszHostName = host;
    uc.dwHostNameLength = sizeof(host);
    uc.lpszUrlPath = path;
    uc.dwUrlPathLength = sizeof(path);
    uc.lpszExtraInfo = extra;
    uc.dwExtraInfoLength = sizeof(extra);

    if (!InternetCrackUrlA(url, 0, ICU_DECODE, &uc)) {
        InternetCloseHandle(hInternet);
        return -1;
    }

    /* nScheme uses INTERNET_SCHEME_HTTPS / HTTP enum values. */
    INTERNET_PORT port = uc.nPort;
    if (port == 0) {
        port = (uc.nScheme == INTERNET_SCHEME_HTTPS) ? INTERNET_DEFAULT_HTTPS_PORT
                                                      : INTERNET_DEFAULT_HTTP_PORT;
    }

    HINTERNET hConnect = InternetConnectA(
        hInternet, host, port, NULL, NULL,
        INTERNET_SERVICE_HTTP, 0, 0);
    if (!hConnect) {
        InternetCloseHandle(hInternet);
        return -1;
    }

    /* Combine path + extra info (query string/fragment). */
    char fullPath[sizeof(path) + sizeof(extra)];
    snprintf(fullPath, sizeof(fullPath), "%s%s", path, extra);

    /* Request flags: reload, no cache, secure (for HTTPS), follow redirects. */
    DWORD flags = INTERNET_FLAG_RELOAD
                | INTERNET_FLAG_NO_CACHE_WRITE
                | INTERNET_FLAG_NO_COOKIES;
    if (uc.nScheme == INTERNET_SCHEME_HTTPS) {
        flags |= INTERNET_FLAG_SECURE;
    }

    HINTERNET hRequest = HttpOpenRequestA(
        hConnect, "GET", fullPath, NULL, NULL, NULL, flags, 0);
    if (!hRequest) {
        InternetCloseHandle(hConnect);
        InternetCloseHandle(hInternet);
        return -1;
    }

    /* Headers required by GitHub API and useful for asset downloads. */
    static const char *headers =
        "User-Agent: SISTEMAS-Launcher/1.0\r\n"
        "Accept: application/vnd.github+json\r\n";

    if (!HttpSendRequestA(hRequest, headers, (DWORD)-1, NULL, 0)) {
        InternetCloseHandle(hRequest);
        InternetCloseHandle(hConnect);
        InternetCloseHandle(hInternet);
        return -1;
    }

    /* Check HTTP status. WinINet follows 30x redirects automatically
     * unless INTERNET_FLAG_NO_AUTO_REDIRECT is set. */
    DWORD statusCode = 0;
    DWORD statusLen = sizeof(statusCode);
    DWORD idx = 0;
    if (!HttpQueryInfoA(hRequest,
                        HTTP_QUERY_STATUS_CODE | HTTP_QUERY_FLAG_NUMBER,
                        &statusCode, &statusLen, &idx)) {
        InternetCloseHandle(hRequest);
        InternetCloseHandle(hConnect);
        InternetCloseHandle(hInternet);
        return -1;
    }

    if (statusCode < 200 || statusCode >= 300) {
        InternetCloseHandle(hRequest);
        InternetCloseHandle(hConnect);
        InternetCloseHandle(hInternet);
        return -1;
    }

    /* Query content length for progress. */
    DWORD contentLength = 0;
    DWORD bufLen = sizeof(contentLength);
    idx = 0;
    HttpQueryInfoA(hRequest,
                   HTTP_QUERY_CONTENT_LENGTH | HTTP_QUERY_FLAG_NUMBER,
                   &contentLength, &bufLen, &idx);

    /* Switch progress bar from marquee to determinate. */
    HWND hBar = hdlg ? GetDlgItem(hdlg, IDC_PROGRESS) : NULL;
    if (hBar && contentLength > 0) {
        SendMessageA(hBar, PBM_SETMARQUEE, FALSE, 0);
        SendMessageA(hBar, PBM_SETRANGE32, 0, 100);
    }

    FILE *fp = fopen(destPath, "wb");
    if (!fp) {
        InternetCloseHandle(hRequest);
        InternetCloseHandle(hConnect);
        InternetCloseHandle(hInternet);
        return -1;
    }

    char buffer[65536];
    DWORD bytesRead;
    DWORD totalRead = 0;
    int ok = 1;

    while (InternetReadFile(hRequest, buffer, sizeof(buffer), &bytesRead)) {
        if (bytesRead == 0) break;
        if (fwrite(buffer, 1, bytesRead, fp) != bytesRead) {
            ok = 0;
            break;
        }
        totalRead += bytesRead;

        if (hBar && contentLength > 0) {
            int pct = (int)(((DWORD64)totalRead * 100) / contentLength);
            SendMessageA(hBar, PBM_SETPOS, pct, 0);
        }

        /* Pump messages to keep UI responsive. */
        if (hdlg) {
            MSG msg;
            while (PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE)) {
                TranslateMessage(&msg);
                DispatchMessageA(&msg);
            }
        }
    }

    fclose(fp);
    InternetCloseHandle(hRequest);
    InternetCloseHandle(hConnect);
    InternetCloseHandle(hInternet);
    return ok ? 0 : -1;
}

/*
 * Read a file into a malloc'd buffer (caller frees).
 */
static char *
read_file_to_buffer(const char *path, DWORD *outSize)
{
    HANDLE hFile = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL,
                               OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (hFile == INVALID_HANDLE_VALUE) return NULL;

    DWORD fileSize = GetFileSize(hFile, NULL);
    if (fileSize == INVALID_FILE_SIZE) {
        CloseHandle(hFile);
        return NULL;
    }

    char *buf = (char *)malloc(fileSize + 1);
    if (!buf) {
        CloseHandle(hFile);
        return NULL;
    }

    DWORD bytesRead = 0;
    if (!ReadFile(hFile, buf, fileSize, &bytesRead, NULL)) {
        free(buf);
        CloseHandle(hFile);
        return NULL;
    }

    buf[bytesRead] = '\0';
    CloseHandle(hFile);

    if (outSize) *outSize = bytesRead;
    return buf;
}

/*
 * Extract a JSON string value for a given key.
 * Simple search — not a real parser, but adequate for GitHub API output.
 */
static int
json_find_string(const char *json, const char *key, char *out, size_t outSize)
{
    char needle[128];
    snprintf(needle, sizeof(needle), "\"%s\"", key);
    const char *p = strstr(json, needle);
    if (!p) return -1;

    p += strlen(needle);
    /* Skip : " */
    while (*p && (*p == ':' || *p == ' ' || *p == '\t' || *p == '\n' ||
                  *p == '\r')) p++;
    if (*p != '"') return -1;
    p++;

    size_t i = 0;
    while (*p && *p != '"' && i < outSize - 1) {
        if (*p == '\\' && p[1]) {
            p++; /* skip escape char, take literal */
        }
        out[i++] = *p++;
    }
    out[i] = '\0';
    return 0;
}

/*
 * Find the browser_download_url for an asset whose name contains *substr*.
 * Searches the assets array in the JSON.
 */
static int
json_find_asset_url(const char *json, const char *substr,
                    char *out, size_t outSize)
{
    const char *p = json;
    for (;;) {
        /* Find next occurrence of "browser_download_url" */
        p = strstr(p, "\"browser_download_url\"");
        if (!p) return -1;

        /* Backtrack to find the asset name */
        const char *nameStart = p - 512;
        if (nameStart < json) nameStart = json;

        /* Look backwards for "name": */
        const char *nameP = NULL;
        for (const char *q = p - 1; q >= nameStart; q--) {
            if (!strncmp(q, "\"name\"", 6)) {
                nameP = q;
                break;
            }
        }

        /* Extract the URL value */
        const char *urlP = p + strlen("\"browser_download_url\"");
        while (*urlP && (*urlP == ':' || *urlP == ' ' || *urlP == '\t')) urlP++;
        if (*urlP != '"') { p++; continue; }
        urlP++;

        /* If we have a name match, check it contains substr. */
        if (nameP && substr && *substr) {
            char name[256] = "";
            const char *ns = nameP + 6;
            while (*ns && (*ns == ':' || *ns == ' ' || *ns == '\t')) ns++;
            if (*ns == '"') {
                ns++;
                size_t ni = 0;
                while (*ns && *ns != '"' && ni < sizeof(name) - 1)
                    name[ni++] = *ns++;
                name[ni] = '\0';
            }
            /* Case-insensitive search */
            char lowerName[256];
            strncpy(lowerName, name, sizeof(lowerName) - 1);
            lowerName[sizeof(lowerName) - 1] = '\0';
            for (char *c = lowerName; *c; c++) *c = tolower(*c);

            char lowerSubstr[128];
            strncpy(lowerSubstr, substr, sizeof(lowerSubstr) - 1);
            lowerSubstr[sizeof(lowerSubstr) - 1] = '\0';
            for (char *c = lowerSubstr; *c; c++) *c = tolower(*c);

            if (strstr(lowerName, lowerSubstr)) {
                /* Found the right asset — extract URL */
                size_t i = 0;
                while (*urlP && *urlP != '"' && i < outSize - 1)
                    out[i++] = *urlP++;
                out[i] = '\0';
                return 0;
            }
        } else {
            /* No substr filter — return first URL found */
            size_t i = 0;
            while (*urlP && *urlP != '"' && i < outSize - 1)
                out[i++] = *urlP++;
            out[i] = '\0';
            return 0;
        }

        p = urlP;
    }
}
#endif /* APP_REPO */

/* --- Main --- */

int WINAPI
WinMain(HINSTANCE hInst, HINSTANCE hPrev, LPSTR lpCmdLine, int nCmdShow)
{
    (void)hInst; (void)hPrev;

    /* --- Module name (from exe filename or compile-time define) --- */
#ifdef APP_MODULE
    const char *appName = APP_MODULE;
#else
    char exePath0[MAX_PATH];
    GetModuleFileNameA(NULL, exePath0, MAX_PATH);
    const char *slash0 = strrchr(exePath0, '\\');
    const char *base0 = slash0 ? slash0 + 1 : exePath0;
    static char appNameBuf[MAX_PATH];
    strncpy(appNameBuf, base0, MAX_PATH - 1);
    appNameBuf[MAX_PATH - 1] = '\0';
    char *dot0 = strrchr(appNameBuf, '.');
    if (dot0) *dot0 = '\0';
    const char *appName = appNameBuf;
#endif

#ifdef APP_DISPLAY
    const char *displayName = APP_DISPLAY;
#else
    const char *displayName = "SISTEMAS";
#endif

    /* Prevent multiple concurrent launcher instances (per-app) */
    char mutexName[128];
    snprintf(mutexName, sizeof(mutexName), "SISTEMAS_Launcher_%s", appName);
    HANDLE hMutex = CreateMutexA(NULL, TRUE, mutexName);
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        CloseHandle(hMutex);
        return 0;
    }

    /* --- Own exe path + directory --- */
    char exePath[MAX_PATH];
    if (GetModuleFileNameA(NULL, exePath, MAX_PATH) == 0) {
        ReleaseMutex(hMutex);
        return 1;
    }

    char exeDir[MAX_PATH];
    strncpy(exeDir, exePath, MAX_PATH - 1);
    exeDir[MAX_PATH - 1] = '\0';
    char *lastSlash = strrchr(exeDir, '\\');
    if (!lastSlash) { ReleaseMutex(hMutex); return 1; }
    lastSlash[1] = '\0';

    /* --- %LOCALAPPDATA% --- */
    const char *lad = getenv("LOCALAPPDATA");
    if (!lad) {
        MessageBoxA(NULL, "Cannot determine LOCALAPPDATA.",
                    displayName, MB_ICONERROR | MB_OK);
        ReleaseMutex(hMutex);
        return 1;
    }

    /* --- Local install path --- */
    char localRoot[MAX_PATH * 2];

#ifdef APP_REPO
    /* Standalone: %LOCALAPPDATA%\SISTEMAS\<module> */
    snprintf(localRoot, sizeof(localRoot), "%s\\SISTEMAS\\%s", lad, appName);
#else
    /* Legacy SISTEMAS: %LOCALAPPDATA%\SISTEMAS (shared) */
    snprintf(localRoot, sizeof(localRoot), "%s\\SISTEMAS", lad);
#endif

    /* --- Check if local Python exists --- */
    char localPython[MAX_PATH * 2];
    snprintf(localPython, sizeof(localPython),
             "%s\\python\\pythonw.exe", localRoot);
    DWORD attr = GetFileAttributesA(localPython);
    int pythonExists = (attr != INVALID_FILE_ATTRIBUTES &&
                        !(attr & FILE_ATTRIBUTE_DIRECTORY));

    /* --- Install / update --- */
    if (!pythonExists) {

#ifdef APP_REPO
        /* ============================================================
         * Standalone mode: download from GitHub Releases.
         * ============================================================ */

        /* Create local directory. */
        CreateDirectoryA(localRoot, NULL);

        /* Temp directory for download. */
        char tempDir[MAX_PATH * 2];
        snprintf(tempDir, sizeof(tempDir), "%s\\_download", localRoot);
        CreateDirectoryA(tempDir, NULL);

        /* Step 1: Download release JSON from GitHub API. */
        char jsonPath[MAX_PATH * 2];
        snprintf(jsonPath, sizeof(jsonPath), "%s\\release.json", tempDir);

        char apiUrl[512];
        snprintf(apiUrl, sizeof(apiUrl),
                 "https://api.github.com/repos/%s/releases/latest", APP_REPO);

        char progressTitle[256];
        snprintf(progressTitle, sizeof(progressTitle),
                 "%s — Conectando...", displayName);
        HWND hdlg = show_progress(progressTitle);

        if (http_download(apiUrl, jsonPath, NULL) != 0) {
            if (hdlg) DestroyWindow(hdlg);
            char msg[512];
            snprintf(msg, sizeof(msg),
                     "Failed to check for updates.\n"
                     "URL: %s\n\n"
                     "Please check your internet connection.", apiUrl);
            MessageBoxA(NULL, msg, displayName, MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }

        /* Step 2: Parse JSON for tag + payload asset URL. */
        DWORD jsonSize = 0;
        char *json = read_file_to_buffer(jsonPath, &jsonSize);
        if (!json) {
            if (hdlg) DestroyWindow(hdlg);
            MessageBoxA(NULL, "Failed to parse release info.",
                        displayName, MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }

        char tag[64] = "";
        json_find_string(json, "tag_name", tag, sizeof(tag));

        /* Find payload.zip asset (fallback to any .zip). */
        char assetUrl[1024] = "";
        if (json_find_asset_url(json, "payload", assetUrl, sizeof(assetUrl)) != 0) {
            json_find_asset_url(json, ".zip", assetUrl, sizeof(assetUrl));
        }
        free(json);

        if (!assetUrl[0]) {
            if (hdlg) DestroyWindow(hdlg);
            MessageBoxA(NULL,
                        "No downloadable payload found in latest release.\n"
                        "Please verify the release assets.",
                        displayName, MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }

        /* Step 3: Download payload.zip. */
        snprintf(progressTitle, sizeof(progressTitle),
                 "%s — Baixando %s...", displayName, tag[0] ? tag : "update");
        SetWindowTextA(hdlg, progressTitle);

        char zipPath[MAX_PATH * 2];
        snprintf(zipPath, sizeof(zipPath), "%s\\payload.zip", tempDir);

        if (http_download(assetUrl, zipPath, hdlg) != 0) {
            if (hdlg) DestroyWindow(hdlg);
            char msg[512];
            snprintf(msg, sizeof(msg),
                     "Download failed.\nURL: %s", assetUrl);
            MessageBoxA(NULL, msg, displayName, MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }

        /* Step 4: Extract to localRoot. */
        snprintf(progressTitle, sizeof(progressTitle),
                 "%s — Instalando...", displayName);
        SetWindowTextA(hdlg, progressTitle);

        /* Reset progress bar to marquee for extraction. */
        HWND hBar = GetDlgItem(hdlg, IDC_PROGRESS);
        if (hBar) {
            SendMessageA(hBar, PBM_SETMARQUEE, TRUE, 0);
        }

        char tarCmd[MAX_PATH * 8];
        snprintf(tarCmd, sizeof(tarCmd),
                 "cmd.exe /c tar -xf \"%s\" -C \"%s\"",
                 zipPath, localRoot);

        DWORD tarExit = run_and_pump(hdlg, tarCmd);

        if (hdlg) DestroyWindow(hdlg);

        if (tarExit != 0) {
            char msg[512];
            snprintf(msg, sizeof(msg),
                     "Installation failed (tar exit code %lu).\n"
                     "Source: %s", tarExit, zipPath);
            MessageBoxA(NULL, msg, displayName, MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }

        /* Clean up temp directory. */
        char cleanupCmd[MAX_PATH * 4];
        snprintf(cleanupCmd, sizeof(cleanupCmd),
                 "cmd.exe /c rd /s /q \"%s\" 2>nul", tempDir);
        system(cleanupCmd);

        /* Verify pythonw.exe appeared. */
        attr = GetFileAttributesA(localPython);
        if (attr == INVALID_FILE_ATTRIBUTES ||
            (attr & FILE_ATTRIBUTE_DIRECTORY)) {
            MessageBoxA(NULL,
                        "Installation completed but pythonw.exe not found.\n"
                        "The payload.zip may be corrupted.",
                        displayName, MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }

#else  /* !APP_REPO — Legacy SISTEMAS mode */
        /* ============================================================
         * Legacy: extract dist.zip from the launcher's directory.
         * ============================================================ */

        char distZip[MAX_PATH * 2];
        snprintf(distZip, sizeof(distZip), "%sdist.zip", exeDir);

        DWORD zipAttr = GetFileAttributesA(distZip);
        if (zipAttr == INVALID_FILE_ATTRIBUTES ||
            (zipAttr & FILE_ATTRIBUTE_DIRECTORY)) {
            char msg[512];
            snprintf(msg, sizeof(msg),
                     "SISTEMAS needs setup but dist.zip was not found:\n%s\n\n"
                     "Please contact your administrator.", distZip);
            MessageBoxA(NULL, msg, displayName, MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }

        /* Remove old installation to avoid stale-file conflicts. */
        char delCmd[MAX_PATH * 4];
        snprintf(delCmd, sizeof(delCmd),
                 "cmd.exe /c rd /s /q \"%s\" 2>nul", localRoot);
        system(delCmd);

        /* Extract dist.zip (creates SISTEMAS\ subtree in %LOCALAPPDATA%). */
        char tarCmd[MAX_PATH * 8];
        snprintf(tarCmd, sizeof(tarCmd),
                 "cmd.exe /c tar -xf \"%s\" -C \"%s\"",
                 distZip, lad);

        HWND hdlg = show_progress(NULL);
        DWORD tarExit = run_and_pump(hdlg, tarCmd);
        if (hdlg) DestroyWindow(hdlg);

        if (tarExit != 0) {
            char msg[512];
            snprintf(msg, sizeof(msg),
                     "Installation failed (tar exit code %lu).\n"
                     "Source: %s", tarExit, distZip);
            MessageBoxA(NULL, msg, displayName, MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }

        /* Verify pythonw.exe. */
        attr = GetFileAttributesA(localPython);
        if (attr == INVALID_FILE_ATTRIBUTES ||
            (attr & FILE_ATTRIBUTE_DIRECTORY)) {
            MessageBoxA(NULL,
                        "Installation completed but pythonw.exe not found.\n"
                        "The dist.zip may be corrupted.",
                        displayName, MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }
#endif /* APP_REPO */
    }

    /* --- Tell the app where the network data lives --- */
    SetEnvironmentVariableA("SISTEMAS_DATA_ROOT", exeDir);

    /* --- Launch pythonw.exe -m <appName> --- */
    char workDir[MAX_PATH * 2];
    snprintf(workDir, sizeof(workDir), "%s\\apps", localRoot);

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
        MessageBoxA(NULL, msg, displayName, MB_ICONERROR | MB_OK);
        ReleaseMutex(hMutex);
        return 1;
    }

    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    ReleaseMutex(hMutex);
    return 0;
}
