"""Start Uncrashed through Steam and bring its window to the front."""
import os
import sys
import time


def find_window(title_part):
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if title_part.lower() in buf.value.lower():
                    found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def focus_window(hwnd):
    import ctypes
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)


def launch(game_cfg, wait=True):
    title = game_cfg.get("window_title", "Uncrashed")
    hwnd = find_window(title)
    if hwnd:
        print("Game already running, bringing it to the front.")
        focus_window(hwnd)
        return hwnd
    if sys.platform != "win32":
        raise SystemExit("Launching the game only works on Windows.")
    print(f"Starting {game_cfg['steam_url']} ...")
    os.startfile(game_cfg["steam_url"])
    if not wait:
        return None
    deadline = time.time() + float(game_cfg.get("startup_timeout_s", 120))
    while time.time() < deadline:
        hwnd = find_window(title)
        if hwnd:
            time.sleep(3)
            focus_window(hwnd)
            print("Game window found.")
            return hwnd
        time.sleep(1)
    raise SystemExit(f"No window with '{title}' in its title after waiting. Is Steam running?")


def ensure_focus(game_cfg):
    hwnd = find_window(game_cfg.get("window_title", "Uncrashed"))
    if hwnd:
        focus_window(hwnd)
    return hwnd
