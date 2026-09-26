# Typo Forge — engineering notes

One-hotkey Windows tool that repairs garbled fast-typed text via Groq.
Read this before changing anything.

## What it does

Copy your smashed text, press **Ctrl+Alt+G**, the daemon sends the
clipboard to Groq (`openai/gpt-oss-120b`, `reasoning_effort: low`, temperature 0),
writes the repaired text back to the clipboard, shows a preview toast, and
auto-wipes the clipboard 30 seconds later — but only if the clipboard still holds
exactly the forge output. The tool injects **zero keystrokes**.

## Files

| File | Role |
|---|---|
| `typo_forge.py` | everything: daemon, hotkey, clipboard, repair, toast. CONFIG dict on top. |
| `keys.txt` | user-owned Groq keys, one `gsk_...` per line (git-ignored). Failover across lines, live-reload per forge (no restart needed). |
| `keys.txt.example` | template shipped instead of the real `keys.txt` |
| `typo-forge-start.vbs` | silent launcher, path-independent; copy into `shell:startup` for autostart |
| `typo-forge.log` | one line per forge: sizes, latency, errors. Read this FIRST when debugging. |

Key failover order in `load_keys()`: `GROQ_API_KEY` env → `keys.txt`.

## Debug playbook

```bash
python -c "import ast; ast.parse(open('typo_forge.py', encoding='utf-8').read())"   # syntax
python typo_forge.py --test    # built-in garble sample through the live API
python typo_forge.py --once    # repair current clipboard, exit (no hotkey needed)
```

Restart the daemon after code changes (keys.txt changes need NO restart):

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like '*typo_forge*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
wscript typo-forge-start.vbs
```

Verify: process alive after 3 s + `daemon started` line in the log. If the daemon
exits instantly, the hotkey registration failed — another instance is running.

## Failure signatures

| Symptom | Cause | Fix |
|---|---|---|
| HTTP 403 "Access denied" from Groq | dead keys (the curl transport already handles Cloudflare) | rotate keys in `keys.txt` |
| "Invalid API Key" | key dead | fresh `gsk_` key in `keys.txt` (one per line, failover is automatic, live reload) |
| Daemon dies at start | hotkey already registered (duplicate instance) or syntax error | kill all `pythonw.exe` with `typo_forge` in CommandLine, re-check syntax, relaunch VBS |
| Console windows flash on hotkey | a subprocess lost `creationflags=_NO_WINDOW` | every `subprocess.run` needs it |
| Access violation in clipboard ops | ctypes handle truncation | the 64-bit argtypes/restypes block near the top is load-bearing — never remove it |
| Tool repairs its own old output | the historic "ghost loop" | guards: refuse when clipboard == `_last_output`; auto-wipe 30 s after forge. Never remove either |

## History — do not reintroduce these bugs

1. Synthetic key injection (keybd_event/SendInput) was removed on purpose:
   scancode-0 injections never trigger Chromium/Electron accelerators, focus is
   unreliable, and copy-with-empty-selection handlers blank the clipboard. The
   user's own Ctrl+C is the capture. Do not add selection capture back.
2. `pythonw` spawns children WITH console windows unless every subprocess call
   passes `CREATE_NO_WINDOW` — caused visible console flashes.
3. ctypes on x64 truncates HANDLEs to 32-bit without explicit
   argtypes/restypes — caused access violations on clipboard write.
4. Module-level ordering: `_user32`/`_kernel32` bindings must precede any
   prototype assignment.
5. The repair quality rubric lives in the `SYSTEM_PROMPT` constant and grows one
   rule per real failure (e.g. "a statement never gets upgraded to a question").
   Extend it from evidence, never from speculation.

## Conventions

- Python stdlib only — no pip dependencies.
- `snake_case` functions, intent-named symbols, errors logged not raised in the
  hotkey path (one bad press must never kill the daemon).
- Model id: `openai/gpt-oss-120b`. Check live models with
  `curl -s https://api.groq.com/openai/v1/models -H "Authorization: Bearer <key>"`.
