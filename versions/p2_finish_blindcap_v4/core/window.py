"""The Uncrashed window: capture its pixels and send it keys and clicks.

Capture uses Windows Graphics Capture on the game window itself, not the screen.
Windows on top of the game (the Claude app, a console, a notification) don't
appear in the frames, so they can't hide the ALT readout. The game must not be
minimised. It runs borderless (FullscreenMode=1), so a frame is the same
1920x1080 picture the old monitor grab gave and every crop box still applies.

Keys and clicks go through SendInput, which only reaches the foreground window,
so focus() brings the game to the front first.
"""
import ctypes
import sys
import threading
import time
from ctypes import wintypes

import numpy as np

from .capture import make_dpi_aware

GAME_EXE = "uncrashed-win64-shipping.exe"

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _exe_of(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return pid.value, ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(len(buf))
        kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
        return pid.value, buf.value
    finally:
        kernel32.CloseHandle(h)


def find_game_window():
    """The game's top-level window, found by its process name (a title match could hit
    an Explorer window named after the game). None if the game isn't running."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _exe_of(hwnd)[1].lower().endswith(GAME_EXE):
            r = client_rect(hwnd)
            found.append((r[2] * r[3], hwnd))
        return True

    user32.EnumWindows(cb, 0)
    return max(found)[1] if found else None


def client_rect(hwnd):
    """(left, top, width, height) of the client area in screen pixels."""
    make_dpi_aware()
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    p = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y, r.right - r.left, r.bottom - r.top


def client_crop(hwnd, frame_w, frame_h):
    """(x, y, w, h) of the client area inside a captured frame. Windows Graphics Capture
    returns the whole visible window; if the game runs windowed (it came back that way
    after a restart on 2026-10-24) that includes the title bar, which shifts every OSD box."""
    r = wintypes.RECT()
    # DWMWA_EXTENDED_FRAME_BOUNDS: the visible window rectangle the capture starts at
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        return 0, 0, frame_w, frame_h
    cx, cy, cw, ch = client_rect(hwnd)
    x, y = max(0, cx - r.left), max(0, cy - r.top)
    return x, y, max(1, min(cw, frame_w - x)), max(1, min(ch, frame_h - y))


def window_state(hwnd):
    return {"hwnd": hwnd, "pid": _exe_of(hwnd)[0], "client": client_rect(hwnd),
            "minimized": bool(user32.IsIconic(hwnd)), "foreground": user32.GetForegroundWindow() == hwnd}


# ---------------------------------------------------------------- capture

class WindowCapture:
    """Keeps the newest frame of a window. grab() returns (t_arrival, BGR copy).

    Frames arrive on the capture thread when the window redraws (every game frame).
    t is time.perf_counter() when the frame reached us, the same clock the pilots use."""

    def __init__(self, hwnd, min_interval_ms=None):
        from windows_capture import WindowsCapture
        make_dpi_aware()
        self.hwnd = hwnd
        self._lock = threading.Lock()
        self._new = threading.Condition(self._lock)
        self._frame = None
        self._t = 0.0
        self.count = 0
        self.closed = False
        cap = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=int(hwnd),
                             minimum_update_interval=min_interval_ms)

        self._crop_for = None  # (frame w, h) the client crop below was worked out for
        self._crop = None

        @cap.event
        def on_frame_arrived(frame, control):
            buf = frame.frame_buffer
            if self._crop_for != buf.shape[:2]:
                self._crop_for, self._crop = buf.shape[:2], client_crop(self.hwnd, buf.shape[1], buf.shape[0])
            x, y, w, h = self._crop
            img = np.array(buf[y:y + h, x:x + w, :3])  # the buffer is only valid inside this call
            with self._new:
                self._frame, self._t = img, time.perf_counter()
                self.count += 1
                self._new.notify_all()

        @cap.event
        def on_closed():
            with self._new:
                self.closed = True
                self._new.notify_all()

        self._control = cap.start_free_threaded()

    def grab(self, newer_than=None, timeout=1.0):
        """Newest frame. With newer_than=<count>, wait for a frame after that one.
        Returns (t, image, count); raises TimeoutError if nothing arrives."""
        end = time.perf_counter() + timeout
        with self._new:
            while (self._frame is None or (newer_than is not None and self.count <= newer_than)) \
                    and not self.closed:
                left = end - time.perf_counter()
                if left <= 0:
                    raise TimeoutError("no frame from the game window (minimised, or the game closed?)")
                self._new.wait(left)
            if self.closed:
                raise RuntimeError("game window capture closed")
            return self._t, self._frame, self.count

    def close(self):
        try:
            self._control.stop()
        except Exception:
            pass


def open_capture(cfg):
    """Frame source for the pilots: the game window, or the monitor if
    capture.source is "screen" in config.json."""
    if cfg["capture"].get("source", "window") == "screen":
        from .capture import MonitorCapture
        return MonitorCapture(cfg["capture"]["monitor"])
    hwnd = find_game_window()
    if not hwnd:
        raise RuntimeError("Uncrashed is not running (python tools/game.py launch)")
    cap = WindowCapture(hwnd)
    cap.grab(timeout=3.0)  # fail now, not mid-flight, if no frames come
    return cap


# ---------------------------------------------------------------- input

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0002, 0x0008
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x8000, 0x4000

VK = {"ESC": 0x1B, "ENTER": 0x0D, "TAB": 0x09, "SPACE": 0x20, "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27,
      "DOWN": 0x28, "BACKSPACE": 0x08, "MENU": 0x12, **{f"F{i}": 0x6F + i for i in range(1, 13)}}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    if user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)) != len(inputs):
        raise OSError(f"SendInput failed ({ctypes.get_last_error()})")


def vk_of(name):
    name = name.upper()
    if name in VK:
        return VK[name]
    if len(name) == 1 and name.isalnum():
        return ord(name)
    raise ValueError(f"unknown key {name!r}")


def _key_input(vk, up):
    scan = user32.MapVirtualKeyW(vk, 0)
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=KEYEVENTF_KEYUP if up else 0)
    return i


def focus(hwnd, timeout=1.0):
    """Bring the game to the front. Windows refuses SetForegroundWindow from a background
    process unless it just sent input, so tap Alt first (the usual workaround)."""
    if user32.GetForegroundWindow() == hwnd:
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    _send(_key_input(VK["MENU"], False), _key_input(VK["MENU"], True))
    user32.SetForegroundWindow(hwnd)
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.02)
    return False


def press(hwnd, key, hold_s=0.08):
    """Tap a key in the game (focuses it first). Returns False if focus failed."""
    if not focus(hwnd):
        return False
    vk = vk_of(key)
    _send(_key_input(vk, False))
    time.sleep(hold_s)
    _send(_key_input(vk, True))
    return True


def click(hwnd, x, y, hold_s=0.06):
    """Left-click at client pixel (x, y) of the game window (focuses it first)."""
    if not focus(hwnd):
        return False
    left, top, _, _ = client_rect(hwnd)
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)  # virtual desktop origin
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    ax = int(round((left + x - vx) * 65535 / max(1, vw - 1)))
    ay = int(round((top + y - vy) * 65535 / max(1, vh - 1)))
    flags = MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK

    def m(extra):
        i = INPUT(type=INPUT_MOUSE)
        i.u.mi = MOUSEINPUT(dx=ax, dy=ay, dwFlags=flags | extra)
        return i

    _send(m(MOUSEEVENTF_MOVE))
    time.sleep(0.05)  # let the UI register the hover before the press
    _send(m(MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTDOWN))
    time.sleep(hold_s)
    _send(m(MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTUP))
    return True
