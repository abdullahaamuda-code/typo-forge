# typo-forge — one hotkey that repairs garbled fast-typed text via Groq gpt-oss-120b.
# Language: Python 3.10+ · Windows 10/11 · stdlib only
# Usage:
#   pythonw typo_forge.py          daemon — copy your garble, Ctrl+Alt+G repairs the clipboard
#   python typo_forge.py --once    repair the current clipboard and exit
#   python typo_forge.py --test    run the built-in garble sample and exit
#
# Workflow anywhere in Windows: copy your smashed text, press Ctrl+Alt+G, wait for
# the toast, paste. The repaired text replaces the clipboard; 30s later the clipboard
# wipes itself if you haven't copied anything new — no stale text ever comes back.

import ctypes
from ctypes import wintypes
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

CONFIG = {
    "model": "openai/gpt-oss-120b",
    "reasoning_effort": "low",      # measured equal quality, ~40% faster than default
    "hotkey": ("G", "Ctrl+Alt+G"),  # repairs the current clipboard
    "wipe_after_s": 30,             # clear the clipboard once the forge has been pasted
    "max_chars": 8000,
    "timeout_s": 25,
    "log_file": Path(__file__).with_name("typo-forge.log"),
    "log_max_bytes": 1_000_000,
}

SYSTEM_PROMPT = """\
You repair text that was typed extremely fast on a keyboard and is full of typos.
Return ONLY the repaired text. Never answer it, never comment on it, never add anything.

The typing is phonetic garble: missing letters, merged words, wrong vowels,
keyboard-neighbor slips. Examples of the pattern: "jsu"->"just", "uegt"->"you get",
"frr"->"for real", "btw" stays "btw", "th" inside a word is usually "the".
Re-derive each word from sentence context; when a word stays ambiguous,
pick the reading that fits the sentence's meaning.

Hard rules:
- Preserve meaning exactly. Never invent content that is not implied.
- Repair punctuation, don't redesign it: keep the original sentence breaks, add a
  comma or question mark only where the grammar clearly demands one. A statement
  stays a statement — never upgrade it to a question. When unsure, prefer no
  punctuation over invented punctuation.
- Preserve line breaks and blank-line structure.
- Preserve URLs, file paths, code, @handles, and numbers verbatim.
- Preserve the casing of product and tool names (iPhone, GitHub, ChatGPT, GPT-OSS, Groq).
- Keep the original language.
- Keep the register: casual text stays casual, all-caps words stay all-caps.
"""

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
_NO_WINDOW = subprocess.CREATE_NO_WINDOW  # child curl must not flash a console

# 64-bit safety: without explicit restypes, ctypes truncates HANDLEs to 32 bits
# and every GlobalLock/SetClipboardData call operates on a garbage pointer.
_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.GetClipboardData.argtypes = [wintypes.UINT]
_user32.GetClipboardData.restype = wintypes.HANDLE
_user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_user32.SetClipboardData.restype = wintypes.HANDLE
_user32.CloseClipboard.argtypes = []
_kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
_kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalLock.restype = wintypes.LPVOID
_kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

_inflight = threading.Lock()
_last_output: str | None = None  # guards against re-repairing our own output
_wipe_timer: threading.Timer | None = None


def log(message: str) -> None:
    path: Path = CONFIG["log_file"]
    try:
        if path.exists() and path.stat().st_size > CONFIG["log_max_bytes"]:
            path.write_text("", encoding="utf-8")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}  {message}\n")
    except OSError:
        pass


def load_keys() -> list[str]:
    """Failover order: GROQ_API_KEY env > keys.txt beside this script.
    Reloaded on every forge, so keys.txt edits need no restart."""
    keys: list[str] = []
    env_key = os.environ.get("GROQ_API_KEY", "").strip()
    if env_key.startswith("gsk_"):
        keys.append(env_key)
    local = Path(__file__).with_name("keys.txt")
    if local.exists():
        for line in local.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("gsk_"):
                keys.append(line)
    return list(dict.fromkeys(keys))


def groq_repair(text: str, keys: list[str]) -> tuple[str | None, str | None]:
    payload = json.dumps({
        "model": CONFIG["model"],
        "temperature": 0,
        **({"reasoning_effort": CONFIG["reasoning_effort"]}
           if CONFIG["reasoning_effort"] else {}),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    })
    last_error = "no keys"
    for key in keys:
        # curl.exe transport: api.groq.com sits behind Cloudflare, which denies
        # python-urllib's TLS fingerprint even with a browser User-Agent.
        result = subprocess.run(
            ["curl", "-s", "--max-time", str(CONFIG["timeout_s"]),
             "https://api.groq.com/openai/v1/chat/completions",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, text=True, encoding="utf-8",
            timeout=CONFIG["timeout_s"] + 5,
            creationflags=_NO_WINDOW,
        )
        try:
            body = json.loads(result.stdout)
            return body["choices"][0]["message"]["content"], None
        except (KeyError, json.JSONDecodeError) as error:
            last_error = f"{type(error).__name__}: {result.stdout[:200]}"
            log(f"key ...{key[-4:]} failed: {last_error}")
    return None, last_error


_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002


def read_clipboard() -> str:
    for _ in range(3):
        if _user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return ""
    try:
        handle = _user32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            _kernel32.GlobalUnlock(handle)
    finally:
        _user32.CloseClipboard()


def write_clipboard(text: str) -> bool:
    for _ in range(3):
        if _user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        _user32.EmptyClipboard()
        size = (len(text) + 1) * 2
        handle = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, size)
        if not handle:
            return False
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            _kernel32.GlobalFree(handle)
            return False
        try:
            ctypes.memmove(pointer, ctypes.create_unicode_buffer(text), size)
        finally:
            _kernel32.GlobalUnlock(handle)
        # on success the system owns the handle — do not GlobalFree it
        return bool(_user32.SetClipboardData(_CF_UNICODETEXT, handle))
    finally:
        _user32.CloseClipboard()


def wipe_if_ours(expected: str) -> None:
    """Clear the clipboard once the forge has presumably been pasted — but never
    touch newer content the user copied after the forge."""
    current = read_clipboard().strip()
    if current == expected:
        if _user32.OpenClipboard(None):
            try:
                _user32.EmptyClipboard()
                log("clipboard wiped (forge consumed)")
            finally:
                _user32.CloseClipboard()


def show_toast(text: str, ok: bool) -> None:
    try:
        import tkinter as tk
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.92)
        width, height = 380, 64
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        root.geometry(f"{width}x{height}+{screen_w - width - 24}+{screen_h - height - 60}")
        root.configure(bg="#111913" if ok else "#1d1113")
        tk.Label(
            root, text=text, fg="#4ade80" if ok else "#f87171", bg=root["bg"],
            font=("Consolas", 9), justify="left", wraplength=width - 16,
        ).pack(expand=True, fill="both")
        root.after(1800, root.destroy)
        root.mainloop()
    except Exception:
        beep = 0x00000000 if ok else 0x00000030  # MB_OK vs MB_ICONHAND
        _user32.MessageBeep(beep)


def forge() -> None:
    """Repair the current clipboard. Never injects keys — your own Ctrl+C is the capture."""
    global _last_output, _wipe_timer
    if not _inflight.acquire(blocking=False):
        show_toast("forge already running", ok=False)
        return
    try:
        started = time.perf_counter()
        original = read_clipboard().strip()
        if not original:
            show_toast("clipboard empty — copy your garble first", ok=False)
            return
        if original == _last_output:
            show_toast("clipboard still holds the last forge — copy new text first", ok=False)
            return
        if len(original) > CONFIG["max_chars"]:
            show_toast(f"too long: {len(original)} > {CONFIG['max_chars']}", ok=False)
            return
        keys = load_keys()
        if not keys:
            show_toast("no Groq key found", ok=False)
            return
        fixed, error = groq_repair(original, keys)
        if fixed is None:
            show_toast(f"forge failed: {error}", ok=False)
            return
        preview = original if len(original) <= 40 else original[:39] + "…"
        if not write_clipboard(fixed):
            show_toast("could not write clipboard", ok=False)
            return
        elapsed = time.perf_counter() - started
        show_toast(f'✓ "{preview}"\nforged in {elapsed:.1f}s — paste it', ok=True)
        _last_output = fixed
        _wipe_timer = threading.Timer(CONFIG["wipe_after_s"], wipe_if_ours, (fixed,))
        _wipe_timer.daemon = True
        _wipe_timer.start()
        log(f"ok {len(original)} -> {len(fixed)} chars in {elapsed:.1f}s")
    except Exception as error:  # never let the daemon die on one hotkey press
        show_toast(f"forge error: {error}", ok=False)
        log(f"error: {error}")
    finally:
        _inflight.release()


def hotkey_loop() -> None:
    vk, name = CONFIG["hotkey"]
    if not _user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT, ord(vk)):
        print(f"hotkey {name} already registered — another instance is running")
        log("hotkey registration failed — already running?")
        sys.exit(1)
    message = wintypes.MSG()
    print(f"typo-forge live — copy your garble, press {name}, paste the repair")
    while _user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        if message.message == WM_HOTKEY and message.wParam == 1:
            threading.Thread(target=forge, daemon=True).start()


def run_sample() -> None:
    sample = ("okay wow yes let sbuild no 1 plsss frr liekd dammna dn also llama 3.3 70B "
              "bt doesn towkr its now gtpt 0ss 120b or os that works anyways yes pls do that oaky")
    print(f"GARBLED:\n{sample}\n")
    fixed, error = groq_repair(sample, load_keys())
    if fixed is None:
        print(f"FAILED: {error}")
        sys.exit(2)
    print(f"FORGED:\n{fixed}")


def main() -> None:
    if "--once" in sys.argv:
        forge()
    elif "--test" in sys.argv:
        run_sample()
    else:
        log("daemon started")
        hotkey_loop()


if __name__ == "__main__":
    main()
