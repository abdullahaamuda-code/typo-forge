# Typo Forge

One hotkey that repairs garbled fast-typed text, system-wide in Windows, in ~1.5 seconds.

```
you copy:   fir spic is th new on th grren one th b;u ei sh olf one
you press:  Ctrl+Alt+G
you paste:  the first pic is the new one, the green one; the blue is the old one
```

Type fast and the keyboard can't keep up: dropped letters, merged words, wrong
vowels, neighbor keys — and autocorrect has no idea what you *meant*. Typo Forge
sends your clipboard to Groq's `openai/gpt-oss-120b` with a repair-only prompt and
hands back clean text. Context-aware, not dictionary-based: it re-derives every
word from sentence meaning.

Measured on real use: **1.2–1.7 s** per forge. Python stdlib only, no pip installs.

## Use

1. Copy your garbled text (in any app — your own Ctrl+C, nothing is injected).
2. Press **Ctrl+Alt+G**.
3. Wait for the green toast (it previews the source text), paste.

Thirty seconds after each forge the clipboard wipes itself — but only if it still
holds exactly the forge output. Anything you copy in the meantime is never touched.

## Setup (~2 minutes)

1. **Python 3.10+** on PATH (`pythonw.exe` must resolve — the python.org installer
   covers this if you keep "Add to PATH" ticked).
2. **A free Groq key** from [console.groq.com](https://console.groq.com).
3. Copy `keys.txt.example` to `keys.txt` and paste your key in — or set the
   `GROQ_API_KEY` environment variable instead. Multiple keys in `keys.txt`
   (one per line) give automatic failover; edits are live-reloaded, no restart.
4. Double-click **`typo-forge-start.vbs`** — silent daemon, no console window.
5. Want it at every login? `Win+R` → `shell:startup` → copy the `.vbs` in.

**Uninstall:** delete the `.vbs` from `shell:startup`, kill the `pythonw` process,
delete the folder. Nothing else is touched.

## CLI

```bash
python typo_forge.py --test   # run the built-in garble sample through the live API
python typo_forge.py --once   # forge the current clipboard and exit
```

## Guards

- Clipboard still holds the last forge result → refused ("copy new text first").
  The tool can never re-repair its own output.
- Empty clipboard → refused.
- The 30 s self-wipe only fires on an exact match — newer copies are safe.
- In-flight lock — mashing the hotkey can't stack requests.

## How it works

1. A `RegisterHotKey` message loop; each hotkey press spawns a worker thread that
   reads the clipboard, repairs it, writes it back, and shows a preview toast.
2. HTTP runs through **`curl.exe`** as a subprocess: api.groq.com sits behind
   Cloudflare, which denies python-urllib's TLS fingerprint regardless of
   User-Agent. `temperature: 0`, `reasoning_effort: low`.
3. The clipboard is raw Win32 via `ctypes`, with explicit 64-bit
   `argtypes`/`restypes` — without them HANDLEs truncate to 32 bits and
   `SetClipboardData` dereferences garbage.

## Why there is no selection mode

An earlier build had a second hotkey that injected synthetic `Ctrl+C` keystrokes
into the focused window to capture the selection. Three failure modes, one root:
Chromium/Electron apps ignore scancode-0 injections, injected copies are
focus-dependent, and copy-with-empty-selection handlers blank the clipboard.
So the tool injects **zero keystrokes** — your real Ctrl+C is the capture, and
it always works.

## Files

| File | Role |
|---|---|
| `typo_forge.py` | everything: daemon, hotkey, clipboard, repair, toast. `CONFIG` dict on top. |
| `typo-forge-start.vbs` | silent launcher; copy it into `shell:startup` for autostart |
| `keys.txt.example` | template for your Groq keys (git-ignored `keys.txt` holds the real ones) |
| `typo-forge.log` | one line per forge: sizes, latency, errors (created at runtime) |

## Troubleshooting

| Symptom | Fix |
|---|---|
| Toast: `forge failed` with HTTP 403 "Access denied" | dead key — put a fresh `gsk_` key in `keys.txt` (the curl transport is already the right one for Cloudflare) |
| Toast: `no Groq key found` | neither `GROQ_API_KEY` is set nor `keys.txt` exists beside the script |
| Daemon exits instantly | the hotkey is already registered — another instance is running |
| `pythonw` not found | Python is not on PATH — reinstall with "Add to PATH" |
| Repairs stop after edits | check `typo-forge.log` — one line per forge, reads bottom-up |

## Config

Everything lives in the `CONFIG` dict at the top of `typo_forge.py`:

| Key | Default | Meaning |
|---|---|---|
| `model` | `openai/gpt-oss-120b` | any Groq chat model works |
| `reasoning_effort` | `low` | measured equal quality, ~40% faster than default |
| `hotkey` | `Ctrl+Alt+G` | repair the current clipboard |
| `wipe_after_s` | `30` | self-wipe delay after a forge |
| `max_chars` | `8000` | hard cap before the API call |
| `timeout_s` | `25` | per-request HTTP timeout |

## License

[MIT](LICENSE)

---

Built by Abdullah A-Amuda.
