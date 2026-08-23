/*
 * launcher.c — Windows launcher for SISTEMAS apps.
 *
 * Two modes, selected at compile time:
 *
 *   1. Standalone (APP_REPO defined):
 *      First launch downloads payload.zip from GitHub Releases
 *      to %LOCALAPPDATA%\SISTEMAS\<module>\.
 *      Subsequent launches skip download if local install exists.
 *
 *   2. SISTEMAS multi-app (APP_REPO NOT defined):
 *      Extracts dist.zip from one directory above the launcher
 *      (the share root: <root>\<APP>\<app>.exe → <root>\dist.zip)
 *      to %LOCALAPPDATA%\SISTEMAS\ (shared across apps).
 *
 * Both modes:
 *   - Set SISTEMAS_DATA_ROOT env var to the launcher's own directory (exeDir).
 *     The app writes data to exeDir\data\, so it works from any directory.
 *   - Launch pythonw.exe -m <appName> from the local install.
 *   - Derive module name from the .exe filename (bap.exe → "bap").
 *
 * Compile (standalone):
 *   x86_64-w64-mingw32-gcc -O2 -s -o rac.exe launcher.c \
 *       -DAPP_REPO=\"januvary/RAC\" -DAPP_MODULE=\"rac\" \
 *       -DAPP_DISPLAY=\"RAC\" \
 *       -mwindows -static -lshlwapi -lcomctl32 -lwininet
 *
 * Compile (SISTEMAS):
 *   x86_64-w64-mingw32-gcc -O2 -s -o rac.exe launcher.c \
 *       -mwindows -static -lshlwapi -lcomctl32
 */

#include <windows.h>
#include <commctrl.h>
#include <shlwapi.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>

#ifdef APP_REPO
#include <wininet.h>
#endif

/* PORTABLE_MODE: shared install at %LOCALAPPDATA%\SISTEMAS,
 * tries local dist.zip first, falls back to GitHub download.
 * Standalone: per-app install at %LOCALAPPDATA%\SISTEMAS\<module>,
 * always downloads from GitHub. */

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

/* Read a key:value pair from a VERSION manifest file.
 * e.g., read_version_key(path, "runtime", buf, sizeof(buf)) → "98839a5a" */
static int
read_version_key(const char *path, const char *key, char *out, size_t outSize)
{
    FILE *f = fopen(path, "r");
    if (!f) { out[0] = '\0'; return -1; }

    char prefix[128];
    snprintf(prefix, sizeof(prefix), "%s:", key);
    size_t prefixLen = strlen(prefix);

    char line[256];
    while (fgets(line, sizeof(line), f)) {
        char *p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (strncmp(p, prefix, prefixLen) == 0) {
            p += prefixLen;
            while (*p == ' ' || *p == '\t') p++;
            size_t i = 0;
            while (*p && *p != '\n' && *p != '\r' &&
                   *p != ' ' && *p != '\t' && i < outSize - 1)
                out[i++] = *p++;
            out[i] = '\0';
            fclose(f);
            return 0;
        }
    }
    fclose(f);
    out[0] = '\0';
    return -1;
}

/* Debug logging. Writes to %LOCALAPPDATA%\SISTEMAS\launcher.log so we can
 * diagnose failures on real Windows machines without a debugger. */
static char _log_path[MAX_PATH * 2] = "";

static void
log_init(const char *localAppData)
{
    if (_log_path[0]) return;
    snprintf(_log_path, sizeof(_log_path),
             "%s\\SISTEMAS\\launcher.log", localAppData);
}

static void
log_message(const char *fmt, ...)
{
    if (!_log_path[0]) {
        char lad[MAX_PATH];
        DWORD len = GetEnvironmentVariableA("LOCALAPPDATA", lad, sizeof(lad));
        if (len == 0 || len >= sizeof(lad)) return;
        log_init(lad);
    }

    FILE *f = fopen(_log_path, "a");
    if (!f) return;

    SYSTEMTIME st;
    GetLocalTime(&st);
    fprintf(f, "[%04d-%02d-%02d %02d:%02d:%02d] ",
            st.wYear, st.wMonth, st.wDay,
            st.wHour, st.wMinute, st.wSecond);

    va_list args;
    va_start(args, fmt);
    vfprintf(f, fmt, args);
    va_end(args);

    fprintf(f, "\n");
    fclose(f);
}

/* Recursively create a directory tree (like mkdir -p). */
static int
mkdir_recursive(const char *path)
{
    char buf[MAX_PATH * 2];
    strncpy(buf, path, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';
    char *p = buf;
    if (p[1] == ':' && p[2] == '\\') p += 3;

    for (; *p; ++p) {
        if (*p == '\\' || *p == '/') {
            char sep = *p;
            *p = '\0';
            CreateDirectoryA(buf, NULL);
            *p = sep;
        }
    }
    CreateDirectoryA(buf, NULL);
    return 0;
}

/* Recursively delete a directory tree (like `rd /s /q`), natively.
 *
 * We must NOT shell out to cmd.exe for this: cmd is a console app, so a
 * GUI launcher spawning it flashes a terminal window, and when the exe
 * runs from a network share cmd.exe also prints the "UNC paths are not
 * supported" warning (it cannot inherit a UNC current directory).
 *
 * Failures are logged to launcher.log (not silently ignored) but do not
 * abort the sweep — remaining entries are still attempted. */
static void
delete_tree_log(const char *path, int depth, int *failures)
{
    if (!path || !*path) return;

    char pattern[MAX_PATH * 2];
    snprintf(pattern, sizeof(pattern), "%s\\*", path);

    WIN32_FIND_DATAA fd;
    HANDLE hFind = FindFirstFileA(pattern, &fd);
    if (hFind == INVALID_HANDLE_VALUE) {
        /* Not a directory (or missing) — try a plain file delete. */
        if (!SetFileAttributesA(path, FILE_ATTRIBUTE_NORMAL))
            log_message("delete_tree: attrs failed (%lu): %s",
                        GetLastError(), path);
        if (!DeleteFileA(path)) {
            (*failures)++;
            log_message("delete_tree: DeleteFileA failed (%lu): %s",
                        GetLastError(), path);
        }
        return;
    }

    do {
        if (!strcmp(fd.cFileName, ".") || !strcmp(fd.cFileName, ".."))
            continue;

        char child[MAX_PATH * 2];
        snprintf(child, sizeof(child), "%s\\%s", path, fd.cFileName);

        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            delete_tree_log(child, depth + 1, failures);
        } else {
            if (!SetFileAttributesA(child, FILE_ATTRIBUTE_NORMAL))
                log_message("delete_tree: attrs failed (%lu): %s",
                            GetLastError(), child);
            if (!DeleteFileA(child)) {
                (*failures)++;
                log_message("delete_tree: DeleteFileA failed (%lu): %s",
                            GetLastError(), child);
            }
        }
    } while (FindNextFileA(hFind, &fd));

    FindClose(hFind);
    if (!RemoveDirectoryA(path)) {
        (*failures)++;
        log_message("delete_tree: RemoveDirectoryA failed (%lu): %s "
                    "(%d failures beneath)",
                    GetLastError(), path, *failures);
    }
}

static void
delete_tree(const char *path)
{
    int failures = 0;
    delete_tree_log(path, 0, &failures);
    if (failures > 0)
        log_message("delete_tree: %d failure(s) under %s", failures, path);
}

/* --- Progress dialog --- */
#define IDD_PROGRESS 100
#define IDC_PROGRESS 101

/* app.log: single append-only session log; truncated once if it grows
 * past this (crash-loop protection). */
#define APPLOG_MAX_BYTES (1024 * 1024)

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

/* Drain the message queue so the progress dialog keeps painting (and the
 * marquee keeps animating) while the GUI thread does blocking work.
 * Call from inside download/extract loops. */
static void
pump_messages(void)
{
    MSG msg;
    while (PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE)) {
        TranslateMessage(&msg);
        DispatchMessageA(&msg);
    }
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

#include "miniz.h"

/* Extract a .zip file using the embedded miniz library. Creates directories
 * as needed and skips entries with path-traversal components. Returns 0 on
 * success, non-zero on failure. Errors are logged to launcher.log. */
static int
extract_miniz(const char *zipPath, const char *destPath, HWND hdlg)
{
    mz_zip_archive zip;
    mz_zip_zero_struct(&zip);

    if (!mz_zip_reader_init_file(&zip, zipPath, 0)) {
        log_message("miniz: failed to open zip: %s", zipPath);
        return 1;
    }

    int fileCount = (int)mz_zip_reader_get_num_files(&zip);
    log_message("miniz: %d entries in %s", fileCount, zipPath);

    /* Determinate progress over entries (replaces the marquee). */
    HWND hBar = hdlg ? GetDlgItem(hdlg, IDC_PROGRESS) : NULL;
    if (hBar && fileCount > 0) {
        SendMessageA(hBar, PBM_SETMARQUEE, FALSE, 0);
        SendMessageA(hBar, PBM_SETRANGE32, 0, fileCount);
    }

    int errors = 0;
    for (int i = 0; i < fileCount; i++) {
        mz_zip_archive_file_stat stat;
        if (!mz_zip_reader_file_stat(&zip, i, &stat)) {
            log_message("miniz: failed to stat entry %d", i);
            errors++;
            continue;
        }

        /* Reject path traversal. */
        if (strstr(stat.m_filename, "..")) {
            log_message("miniz: skipping suspicious path: %s", stat.m_filename);
            continue;
        }

        /* Build output path: destPath + \ + filename. */
        char outPath[MAX_PATH * 4];
        snprintf(outPath, sizeof(outPath), "%s\\%s", destPath, stat.m_filename);
        for (char *p = outPath; *p; ++p) {
            if (*p == '/') *p = '\\';
        }

        if (stat.m_is_directory) {
            mkdir_recursive(outPath);
            continue;
        }

        /* Ensure parent directory exists. */
        char parent[MAX_PATH * 4];
        strncpy(parent, outPath, sizeof(parent) - 1);
        parent[sizeof(parent) - 1] = '\0';
        char *lastSlash = strrchr(parent, '\\');
        if (lastSlash) {
            *lastSlash = '\0';
            mkdir_recursive(parent);
        }

        if (!mz_zip_reader_extract_to_file(&zip, i, outPath, 0)) {
            log_message("miniz: failed to extract: %s", stat.m_filename);
            errors++;
            continue;
        }

        if (hBar) SendMessageA(hBar, PBM_SETPOS, i + 1, 0);
        pump_messages();
    }

    mz_zip_reader_end(&zip);

    if (errors > 0) {
        log_message("miniz: extraction finished with %d error(s)", errors);
        return 1;
    }

    log_message("miniz: extraction complete");
    return 0;
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
    log_message("http_download: url=%s dest=%s", url, destPath);

    /* Use an empty agent in InternetOpenA because we set the real User-Agent
     * header explicitly below. Some servers reject duplicate User-Agent
     * headers or ignore the agent from InternetOpenA. */
    HINTERNET hInternet = InternetOpenA(
        "",
        INTERNET_OPEN_TYPE_PRECONFIG,
        NULL, NULL, 0);
    if (!hInternet) {
        log_message("InternetOpenA failed: %lu", GetLastError());
        return -1;
    }

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
        log_message("InternetCrackUrlA failed: %lu", GetLastError());
        InternetCloseHandle(hInternet);
        return -1;
    }

    /* nScheme uses INTERNET_SCHEME_HTTPS / HTTP enum values. */
    INTERNET_PORT port = uc.nPort;
    if (port == 0) {
        port = (uc.nScheme == INTERNET_SCHEME_HTTPS) ? INTERNET_DEFAULT_HTTPS_PORT
                                                      : INTERNET_DEFAULT_HTTP_PORT;
    }

    log_message("Parsed URL: scheme=%s host=%s port=%d path=%s",
                scheme, host, (int)port, path);

    HINTERNET hConnect = InternetConnectA(
        hInternet, host, port, NULL, NULL,
        INTERNET_SERVICE_HTTP, 0, 0);
    if (!hConnect) {
        log_message("InternetConnectA failed: %lu", GetLastError());
        InternetCloseHandle(hInternet);
        return -1;
    }

    /* Combine path + extra info (query string/fragment). */
    char fullPath[sizeof(path) + sizeof(extra)];
    snprintf(fullPath, sizeof(fullPath), "%s%s", path, extra);

    /* Request flags: reload, no cache, secure (for HTTPS), follow redirects.
     * We do NOT set INTERNET_FLAG_NO_AUTO_REDIRECT so WinINet follows 302
     * redirects (needed for GitHub asset downloads). */
    DWORD flags = INTERNET_FLAG_RELOAD
                | INTERNET_FLAG_NO_CACHE_WRITE
                | INTERNET_FLAG_NO_COOKIES;
    if (uc.nScheme == INTERNET_SCHEME_HTTPS) {
        flags |= INTERNET_FLAG_SECURE;
    }

    HINTERNET hRequest = HttpOpenRequestA(
        hConnect, "GET", fullPath, NULL, NULL, NULL, flags, 0);
    if (!hRequest) {
        log_message("HttpOpenRequestA failed: %lu", GetLastError());
        InternetCloseHandle(hConnect);
        InternetCloseHandle(hInternet);
        return -1;
    }

    /* Headers required by GitHub API and useful for asset downloads. */
    static const char *headers =
        "User-Agent: SISTEMAS-Launcher/1.0\r\n"
        "Accept: application/vnd.github+json\r\n";

    if (!HttpSendRequestA(hRequest, headers, (DWORD)-1, NULL, 0)) {
        log_message("HttpSendRequestA failed: %lu", GetLastError());
        InternetCloseHandle(hRequest);
        InternetCloseHandle(hConnect);
        InternetCloseHandle(hInternet);
        return -1;
    }

    log_message("HttpSendRequestA succeeded");

    DWORD idx = 0;

    /* Check HTTP status. Query as a string to avoid WinINet quirks
     * with HTTP_QUERY_FLAG_NUMBER. The string may contain a reason
     * phrase (e.g. "200 OK"), so we parse only the leading digits. */
    char statusStr[64] = "";
    DWORD statusLen = sizeof(statusStr);
    idx = 0;
    if (!HttpQueryInfoA(hRequest,
                        HTTP_QUERY_STATUS_CODE,
                        statusStr, &statusLen, &idx)) {
        log_message("HttpQueryInfoA(STATUS_CODE) failed: %lu", GetLastError());
        InternetCloseHandle(hRequest);
        InternetCloseHandle(hConnect);
        InternetCloseHandle(hInternet);
        return -1;
    }

    /* Robust parse: skip non-digits, then read digits. */
    int statusCode = 0;
    const char *p = statusStr;
    while (*p && !isdigit((unsigned char)*p)) p++;
    while (*p && isdigit((unsigned char)*p)) {
        statusCode = statusCode * 10 + (*p - '0');
        p++;
    }

    log_message("HTTP status: '%s' parsed as %d", statusStr, statusCode);

    if (statusCode < 200 || statusCode >= 300) {
        log_message("HTTP status not success: %d", statusCode);
        InternetCloseHandle(hRequest);
        InternetCloseHandle(hConnect);
        InternetCloseHandle(hInternet);
        return -1;
    }

    /* Query content length for progress. */
    DWORD contentLength = 0;
    char contentLenStr[32] = "";
    DWORD bufLen = sizeof(contentLenStr);
    idx = 0;
    if (HttpQueryInfoA(hRequest,
                       HTTP_QUERY_CONTENT_LENGTH,
                       contentLenStr, &bufLen, &idx)) {
        contentLength = (DWORD)atoi(contentLenStr);
        log_message("Content-Length: %lu", contentLength);
    }

    /* Switch progress bar from marquee to determinate. */
    HWND hBar = hdlg ? GetDlgItem(hdlg, IDC_PROGRESS) : NULL;
    if (hBar && contentLength > 0) {
        SendMessageA(hBar, PBM_SETMARQUEE, FALSE, 0);
        SendMessageA(hBar, PBM_SETRANGE32, 0, 100);
    }

    FILE *fp = fopen(destPath, "wb");
    if (!fp) {
        log_message("fopen failed for '%s': errno=%d", destPath, errno);
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
        if (hdlg) pump_messages();
    }

    fclose(fp);
    InternetCloseHandle(hRequest);
    InternetCloseHandle(hConnect);
    InternetCloseHandle(hInternet);

    log_message("Download complete: %lu bytes, ok=%d", totalRead, ok);
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

        /* Backtrack to find the asset name.
         * GitHub's JSON has a large uploader object between "name" and
         * "browser_download_url", so we need a generous backtrack window. */
        const char *nameStart = p - 2048;
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

/* --- Launcher-side update check (throttled, once/day) --- */

static void
launcher_update_check(const char *localRoot, const char *appName,
                      const char *displayName)
{
    /* Skip if Python updater already staged something. */
    char updateTagPath[MAX_PATH * 2];
    snprintf(updateTagPath, sizeof(updateTagPath),
             "%s\\_update_staging\\.update_tag", localRoot);
    if (GetFileAttributesA(updateTagPath) != INVALID_FILE_ATTRIBUTES) {
        log_message("Pending staging detected, skipping launcher check");
        return;
    }

    /* Throttle: once per day. */
    char lastCheckPath[MAX_PATH * 2];
    snprintf(lastCheckPath, sizeof(lastCheckPath),
             "%s\\.last_check", localRoot);

    SYSTEMTIME st;
    GetLocalTime(&st);
    char today[16];
    snprintf(today, sizeof(today), "%04d-%02d-%02d",
             st.wYear, st.wMonth, st.wDay);

    char lastDate[16] = "";
    read_version_file(lastCheckPath, lastDate, sizeof(lastDate));
    if (strcmp(today, lastDate) == 0) return;
    write_file(lastCheckPath, today);

    /* Read local hashes. */
    char versionPath[MAX_PATH * 2];
    snprintf(versionPath, sizeof(versionPath), "%s\\VERSION", localRoot);

    char localRuntime[16] = "";
    char localApp[16] = "";
    char localAndaime[16] = "";
    read_version_key(versionPath, "runtime", localRuntime, sizeof(localRuntime));
    read_version_key(versionPath, appName, localApp, sizeof(localApp));
    read_version_key(versionPath, "andaime", localAndaime, sizeof(localAndaime));

    /* Query GitHub API. */
    char tempDir[MAX_PATH * 2];
    snprintf(tempDir, sizeof(tempDir), "%s\\_download", localRoot);
    mkdir_recursive(tempDir);

    char jsonPath[MAX_PATH * 2];
    snprintf(jsonPath, sizeof(jsonPath), "%s\\release.json", tempDir);

    char apiUrl[512];
    snprintf(apiUrl, sizeof(apiUrl),
             "https://api.github.com/repos/%s/releases/latest", APP_REPO);

    if (http_download(apiUrl, jsonPath, NULL) != 0) {
        log_message("Update check: API failed, skipping");
        return;
    }

    DWORD jsonSize = 0;
    char *json = read_file_to_buffer(jsonPath, &jsonSize);
    if (!json) return;

    char tag[64] = "";
    json_find_string(json, "tag_name", tag, sizeof(tag));

    /* Find + download remote VERSION. */
    char versionUrl[1024] = "";
    json_find_asset_url(json, "VERSION", versionUrl, sizeof(versionUrl));
    if (!versionUrl[0]) {
        free(json);
        log_message("Update check: no VERSION asset");
        return;
    }

    char remoteVersionPath[MAX_PATH * 2];
    snprintf(remoteVersionPath, sizeof(remoteVersionPath),
             "%s\\remote_version", tempDir);

    if (http_download(versionUrl, remoteVersionPath, NULL) != 0) {
        free(json);
        log_message("Update check: VERSION download failed");
        return;
    }

    char remoteRuntime[16] = "";
    char remoteApp[16] = "";
    char remoteAndaime[16] = "";
    read_version_key(remoteVersionPath, "runtime", remoteRuntime, sizeof(remoteRuntime));
    read_version_key(remoteVersionPath, appName, remoteApp, sizeof(remoteApp));
    read_version_key(remoteVersionPath, "andaime", remoteAndaime, sizeof(remoteAndaime));

    /* Compare. Missing remote key = update needed (unifies with Python's
     * origin — a release that omits a hash must still push an update rather
     * than silently skipping). A release-side guard prevents bad VERSIONs
     * from ever being published. */
    int needPayload = (!remoteRuntime[0] ||
                       (remoteRuntime[0] && strcmp(remoteRuntime, localRuntime) != 0));
    int needAppUpdate = needPayload ||
                        (!remoteApp[0] ||
                         (remoteApp[0] && strcmp(remoteApp, localApp) != 0)) ||
                        (!remoteAndaime[0] ||
                         (remoteAndaime[0] && strcmp(remoteAndaime, localAndaime) != 0));

    if (!needPayload && !needAppUpdate) {
        free(json);
        log_message("Update check: up to date");
        delete_tree(tempDir);
        return;
    }

    /* A shared mutex across ALL apps protects _update_staging/ from being
     * written by two instances at once (each launch has its own per-app
     * mutex, so they'd otherwise race on the same staging folder). Try-lock:
     * if another app is already staging, skip and launch normally — it will
     * apply the update this or next launch. */
    HANDLE hUpdateMutex = CreateMutexA(NULL, TRUE,
                                       "SISTEMAS_Update_Staging");
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        CloseHandle(hUpdateMutex);
        free(json);
        log_message("Another app is staging; skipping launcher staging");
        return;
    }

    log_message("Update available: %s (payload=%d app-update=%d)",
                tag, needPayload, needAppUpdate);

    /* Download + extract to staging. */
    char stagingPath[MAX_PATH * 2];
    snprintf(stagingPath, sizeof(stagingPath),
             "%s\\_update_staging", localRoot);

    delete_tree(stagingPath);
    mkdir_recursive(stagingPath);

    HWND hdlg = show_progress(displayName);

    if (needPayload) {
        char url[1024] = "";
        json_find_asset_url(json, "payload", url, sizeof(url));
        if (url[0]) {
            char zipPath[MAX_PATH * 2];
            snprintf(zipPath, sizeof(zipPath), "%s\\payload.zip", tempDir);
            SetWindowTextW(hdlg, L"Baixando atualização...");
            if (http_download(url, zipPath, hdlg) == 0) {
                SetWindowTextW(hdlg, L"Extraindo arquivos...");
                extract_miniz(zipPath, stagingPath, hdlg);
            }
        }
    }

    if (needAppUpdate) {
        char url[1024] = "";
        json_find_asset_url(json, "app-update", url, sizeof(url));
        if (url[0]) {
            char zipPath[MAX_PATH * 2];
            snprintf(zipPath, sizeof(zipPath), "%s\\app-update.zip", tempDir);
            SetWindowTextW(hdlg, L"Baixando atualização...");
            if (http_download(url, zipPath, hdlg) == 0) {
                SetWindowTextW(hdlg, L"Extraindo arquivos...");
                extract_miniz(zipPath, stagingPath, hdlg);
            }
        }
    }

    free(json);
    if (hdlg) DestroyWindow(hdlg);

    /* Write .update_tag so apply_pending_update picks it up. */
    char tagFilePath[MAX_PATH * 2];
    snprintf(tagFilePath, sizeof(tagFilePath),
             "%s\\.update_tag", stagingPath);
    write_file(tagFilePath, tag);

    /* Clean up temp. */
    delete_tree(tempDir);

    ReleaseMutex(hUpdateMutex);
    CloseHandle(hUpdateMutex);
    log_message("Update staged: %s", tag);
}

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

    /* Initialize logging so we can diagnose Windows-specific failures. */
    log_init(lad);
    log_message("Launcher started: %s", appName);

    /*
     * User-facing layout (standalone zip / portable share):
     *   <DIR>/<app>.exe   +   <DIR>/data/
     * The exe stays wherever the user put it. Data lives next to it.
     * Works from any directory (Downloads, Desktop, USB, network share).
     */

    /* --- Local install path (shared across all apps) --- */
    char localRoot[MAX_PATH * 2];
    snprintf(localRoot, sizeof(localRoot), "%s\\SISTEMAS", lad);

    /* --- Check if local install is valid ---
     * Both python.exe AND VERSION must exist. If either is missing,
     * the previous extraction was interrupted or corrupted — wipe and
     * re-download from scratch. */

    char localPython[MAX_PATH * 2];
    snprintf(localPython, sizeof(localPython),
             "%s\\python\\python.exe", localRoot);
    DWORD attr = GetFileAttributesA(localPython);
    int pythonExists = (attr != INVALID_FILE_ATTRIBUTES &&
                        !(attr & FILE_ATTRIBUTE_DIRECTORY));

    char versionPath[MAX_PATH * 2];
    snprintf(versionPath, sizeof(versionPath),
             "%s\\VERSION", localRoot);
    int versionExists = (GetFileAttributesA(versionPath) !=
                         INVALID_FILE_ATTRIBUTES);

    int installValid = pythonExists && versionExists;

    if (!installValid && (pythonExists || versionExists)) {
        /* Partial install detected — wipe before re-downloading. */
        log_message("Incomplete install detected (python=%d version=%d), wiping",
                    pythonExists, versionExists);
        delete_tree(localRoot);
    }

    /* --- Install / update --- */
    if (!installValid) {
        int installed = 0;

#ifdef PORTABLE_MODE
        /* ============================================================
         * Portable: try local dist.zip first (offline install).
         * ============================================================ */
        char distZip[MAX_PATH * 2];
        snprintf(distZip, sizeof(distZip), "%s..\\dist.zip", exeDir);

        DWORD zipAttr = GetFileAttributesA(distZip);
        if (zipAttr == INVALID_FILE_ATTRIBUTES ||
            (zipAttr & FILE_ATTRIBUTE_DIRECTORY)) {
            snprintf(distZip, sizeof(distZip), "%sdist.zip", exeDir);
            zipAttr = GetFileAttributesA(distZip);
        }

        if (zipAttr != INVALID_FILE_ATTRIBUTES &&
            !(zipAttr & FILE_ATTRIBUTE_DIRECTORY)) {
            mkdir_recursive(localRoot);

            char progressTitle[256];
            snprintf(progressTitle, sizeof(progressTitle),
                     "SISTEMAS - Instalando...");
            HWND hdlg = show_progress(progressTitle);

            if (extract_miniz(distZip, localRoot, hdlg) == 0) {
                if (hdlg) DestroyWindow(hdlg);
                log_message("Portable: extracted local dist.zip to %s", localRoot);

                attr = GetFileAttributesA(localPython);
                if (attr != INVALID_FILE_ATTRIBUTES &&
                    !(attr & FILE_ATTRIBUTE_DIRECTORY)) {
                    installed = 1;
                }
            } else {
                if (hdlg) DestroyWindow(hdlg);
                log_message("Portable: local dist.zip extraction failed, falling back to GitHub");
            }
        }
#endif /* PORTABLE_MODE */

        if (!installed) {
            /* ============================================================
             * GitHub download (standalone always, portable fallback).
             * ============================================================ */

        /* Create local directory (recursively, like mkdir -p). */
        mkdir_recursive(localRoot);

        /* Temp directory for download. */
        char tempDir[MAX_PATH * 2];
        snprintf(tempDir, sizeof(tempDir), "%s\\_download", localRoot);
        mkdir_recursive(tempDir);

        /* Step 1: Download release JSON from GitHub API. */
        char jsonPath[MAX_PATH * 2];
        snprintf(jsonPath, sizeof(jsonPath), "%s\\release.json", tempDir);

        char apiUrl[512];
        snprintf(apiUrl, sizeof(apiUrl),
                 "https://api.github.com/repos/%s/releases/latest", APP_REPO);

        char progressTitle[256];
        snprintf(progressTitle, sizeof(progressTitle),
                 "%s - Conectando...", displayName);
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
                 "%s - Baixando %s...", displayName, tag[0] ? tag : "update");
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

        /* Step 4: Extract to localRoot using the embedded miniz extractor.
         * extract_miniz switches the bar to determinate per-file progress. */
        snprintf(progressTitle, sizeof(progressTitle),
                 "%s - Instalando...", displayName);
        SetWindowTextA(hdlg, progressTitle);

        if (extract_miniz(zipPath, localRoot, hdlg) != 0) {
            if (hdlg) DestroyWindow(hdlg);
            char msg[512];
            snprintf(msg, sizeof(msg),
                     "Installation failed.\n"
                     "See details in: %%LOCALAPPDATA%%\\SISTEMAS\\launcher.log");
            MessageBoxA(NULL, msg, displayName, MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }

        if (hdlg) DestroyWindow(hdlg);

        /* Clean up temp directory. */
        delete_tree(tempDir);

        /* Verify python.exe appeared. */
        attr = GetFileAttributesA(localPython);
        if (attr == INVALID_FILE_ATTRIBUTES ||
            (attr & FILE_ATTRIBUTE_DIRECTORY)) {
            MessageBoxA(NULL,
                        "Installation completed but python.exe not found.\n"
                        "The payload.zip may be corrupted.",
                        displayName, MB_ICONERROR | MB_OK);
            ReleaseMutex(hMutex);
            return 1;
        }
        } /* !installed */
    }

    /* --- Launcher-side update check (throttled, once/day) --- */
    launcher_update_check(localRoot, appName, displayName);

    /* --- Tell the app where its data lives ---
     * Data always lives next to the exe, in whatever directory it runs from.
     * SISTEMAS_DATA_ROOT = exeDir; the app writes to exeDir\data\. */
    SetEnvironmentVariableA("SISTEMAS_DATA_ROOT", exeDir);

    /* --- Launch python.exe -m <appName> (CREATE_NO_WINDOW = no console) --- */
    char workDir[MAX_PATH * 2];
    snprintf(workDir, sizeof(workDir), "%s\\apps", localRoot);

    char cmdLine[MAX_PATH * 4];
    if (lpCmdLine && lpCmdLine[0])
        snprintf(cmdLine, sizeof(cmdLine),
                 "\"%s\" -m %s %s", localPython, appName, lpCmdLine);
    else
        snprintf(cmdLine, sizeof(cmdLine),
                 "\"%s\" -m %s", localPython, appName);

    log_message("Launching: %s cwd=%s", cmdLine, workDir);

    /* Capture stdout/stderr to a log file so python.exe crashes are visible.
     * NOTE: the handles MUST be created inheritable (bInheritHandle=TRUE).
     * With NULL security attributes they are not, and despite
     * bInheritHandles=TRUE in CreateProcess the child receives invalid
     * std handles — CPython then sets sys.stdout/sys.stderr to None and
     * app.log stays forever empty (no logs, no crash tracebacks).
     *
     * Append so previous sessions' crash tracebacks survive; truncate
     * once if the file has grown past APPLOG_MAX_BYTES (crash-loop
     * protection). Opened with FILE_APPEND_DATA + full sharing so
     * multiple apps can hold the log concurrently — every write goes to
     * EOF, so sessions interleave at line granularity (fine for a log). */
    SECURITY_ATTRIBUTES secAttrs = { sizeof(SECURITY_ATTRIBUTES), NULL, TRUE };

    char appLogPath[MAX_PATH * 2];
    snprintf(appLogPath, sizeof(appLogPath), "%s\\app.log", localRoot);
    HANDLE hAppLog = CreateFileA(appLogPath,
                                 FILE_APPEND_DATA,
                                 FILE_SHARE_READ | FILE_SHARE_WRITE,
                                 &secAttrs,
                                 OPEN_ALWAYS,
                                 FILE_ATTRIBUTE_NORMAL,
                                 NULL);
    if (hAppLog != INVALID_HANDLE_VALUE) {
        LARGE_INTEGER size;
        if (GetFileSizeEx(hAppLog, &size) &&
            size.QuadPart > APPLOG_MAX_BYTES) {
            /* Too big (crash loop?) — start fresh. */
            CloseHandle(hAppLog);
            hAppLog = CreateFileA(appLogPath,
                                  FILE_APPEND_DATA,
                                  FILE_SHARE_READ | FILE_SHARE_WRITE,
                                  &secAttrs,
                                  CREATE_ALWAYS,
                                  FILE_ATTRIBUTE_NORMAL,
                                  NULL);
        }
    }

    HANDLE hStdIn = CreateFileA("NUL", GENERIC_READ, FILE_SHARE_READ,
                                &secAttrs, OPEN_EXISTING, 0, NULL);

    STARTUPINFOA si;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    if (hAppLog != INVALID_HANDLE_VALUE && hStdIn != INVALID_HANDLE_VALUE) {
        si.dwFlags = STARTF_USESTDHANDLES;
        si.hStdInput = hStdIn;
        si.hStdOutput = hAppLog;
        si.hStdError = hAppLog;
    }

    PROCESS_INFORMATION pi;
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessA(localPython, cmdLine, NULL, NULL, TRUE,
                          CREATE_NO_WINDOW, NULL, workDir, &si, &pi)) {
        log_message("CreateProcessA failed: %lu", GetLastError());
        char msg[512];
        snprintf(msg, sizeof(msg),
                 "Failed to start %s.\n\nPython: %s\nError: %lu",
                 appName, localPython, GetLastError());
        MessageBoxA(NULL, msg, displayName, MB_ICONERROR | MB_OK);
        if (hAppLog != INVALID_HANDLE_VALUE) CloseHandle(hAppLog);
        if (hStdIn != INVALID_HANDLE_VALUE) CloseHandle(hStdIn);
        ReleaseMutex(hMutex);
        return 1;
    }

    log_message("Process started, pid=%lu", pi.dwProcessId);

    /* Wait briefly to detect immediate crashes. */
    DWORD waitResult = WaitForSingleObject(pi.hProcess, 5000);
    if (waitResult == WAIT_OBJECT_0) {
        DWORD exitCode = 0;
        GetExitCodeProcess(pi.hProcess, &exitCode);
        log_message("Process exited with code: %lu", exitCode);

        if (exitCode != 0) {
            char msg[1024];
            snprintf(msg, sizeof(msg),
                     "%s fechou inesperadamente (codigo %lu).\n\n"
                     "Reinstalar pode resolver o problema.",
                     displayName, exitCode);
            if (MessageBoxA(NULL, msg, displayName,
                            MB_ICONQUESTION | MB_YESNO) == IDYES) {
                log_message("User chose to reinstall after crash");
                delete_tree(localRoot);

                /* Re-launch self (triggers fresh download). */
                STARTUPINFOA rsi;
                PROCESS_INFORMATION rpi;
                ZeroMemory(&rsi, sizeof(rsi));
                rsi.cb = sizeof(rsi);
                ZeroMemory(&rpi, sizeof(rpi));
                CreateProcessA(exePath, NULL, NULL, NULL, FALSE,
                               0, NULL, NULL, &rsi, &rpi);
                CloseHandle(rpi.hThread);
                CloseHandle(rpi.hProcess);
            }
        }
    } else {
        log_message("App running normally, launcher exiting");
    }

    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    if (hAppLog != INVALID_HANDLE_VALUE) CloseHandle(hAppLog);
    if (hStdIn != INVALID_HANDLE_VALUE) CloseHandle(hStdIn);

    ReleaseMutex(hMutex);
    return 0;
}
