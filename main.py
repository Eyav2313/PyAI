from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from io import BytesIO
from pathlib import Path
from tkinter import BOTH, LEFT, Button, Entry, Frame, Label, Tk
from urllib.parse import unquote, urlparse

import pyperclip
import requests

try:
    from PIL import Image, ImageGrab, ImageStat
except ImportError:  # pragma: no cover - optional screenshot fallback
    Image = None
    ImageGrab = None
    ImageStat = None

try:
    from winotify import Notification
except ImportError:  # pragma: no cover - fallback for non-Windows/dev installs
    Notification = None


APP_NAME = "PyAI"
DEVELOPER_LICENSE = "Nuren Zarif Haque"
DIRECT_HOTKEYS = ["f8"]
PROMPT_HOTKEYS = ["ctrl+i"]
COMMENT_HOTKEYS = ["ctrl+alt+b"]
EXIT_HOTKEYS = ["esc"]
TOAST_TOGGLE_HOTKEY = "f9"
PROMPT_HIDE_HOTKEY = "f10"
API_URL = "https://models.github.ai/inference/chat/completions"
API_VERSION = "2026-03-10"
DEFAULT_MODEL = "openai/gpt-4.1"
VISION_IMAGE_MAX_SIZE = (1400, 1000)
SOURCE_EXTENSIONS = {
    "Python": [".py"],
    "C": [".c", ".h"],
    "C++": [".cpp", ".cc", ".cxx", ".hpp", ".h"],
}
EXTENSION_LANGUAGE = {
    ".py": "Python",
    ".c": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
}
SKIP_DIRS = {".git", ".venv", ".build-venv", "__pycache__", "build", "dist", "node_modules"}
_KEYBOARD = None
_STOP_EVENT = threading.Event()
_TOASTS_HIDDEN = threading.Event()
_PROMPT_CANCEL_EVENT = threading.Event()
_RUN_LOCK = threading.Lock()
_PROMPT_ROOT = None

def app_dir() -> Path:
    # When packaged with PyInstaller --onefile, __file__ points to a temp extract.
    # We want settings/logo next to the EXE so the user can ship a private .env.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ENV_FILE = app_dir() / ".env"
LOGO_PATH = app_dir() / "assets" / "logo.png"
ERROR_LOG_PATH = app_dir() / "last_error.txt"
TOKEN_PLACEHOLDERS = {"", "your_token_here", "paste_your_token_here", "paste_token_here"}


def main() -> int:
    args = parse_args()

    if args.set_token:
        save_token()
        return 0

    if self_install_if_needed():
        return 0

    settings = load_settings()
    token = settings.get("PyAI_GITHUB_TOKEN", "").strip()

    if not token or not looks_like_github_token(token):
        notify(
            "PyAI setup needed",
            "Put a real token in .env/.env.example or configure a local token alias.",
        )
        print("Missing GitHub token. Put a real token in .env/.env.example or configure a local token alias.")
        return 1

    print(f"{APP_NAME} is running.")
    print(f"Developer license: {DEVELOPER_LICENSE}")
    print("Language: auto from selected text")
    print("Select problem text and press F8 to create code.")
    print("If website text cannot be selected, keep the page visible and press F8.")
    print("Select code/error and press Ctrl+I to open the prompt.")
    print("Select code and press Ctrl+Alt+B to add Bangla explanation comments.")
    print("Press F10 to hide the prompt. Press F9 to hide/show toast. Press ESC to quick exit.")
    notify("PyAI running", "F8 solves. Ctrl+I prompts. Ctrl+Alt+B comments.")

    hotkeys = get_keyboard()
    for hotkey in DIRECT_HOTKEYS:
        hotkeys.add_hotkey(
            hotkey,
            lambda key=hotkey: threading.Thread(target=answer_selection, args=(settings, key, "solve"), daemon=True).start(),
            suppress=True,
        )
    for hotkey in PROMPT_HOTKEYS:
        hotkeys.add_hotkey(
            hotkey,
            lambda key=hotkey: threading.Thread(target=answer_selection, args=(settings, key, "prompt"), daemon=True).start(),
            suppress=True,
        )
    for hotkey in COMMENT_HOTKEYS:
        hotkeys.add_hotkey(
            hotkey,
            lambda key=hotkey: threading.Thread(target=answer_selection, args=(settings, key, "comment"), daemon=True).start(),
            suppress=True,
        )
    for exit_hotkey in EXIT_HOTKEYS:
        hotkeys.add_hotkey(exit_hotkey, quick_exit)
    hotkeys.add_hotkey(TOAST_TOGGLE_HOTKEY, toggle_toasts)
    hotkeys.add_hotkey(PROMPT_HIDE_HOTKEY, hide_prompt)

    try:
        while not _STOP_EVENT.is_set():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass

    print("\nPyAI stopped.")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PyAI coding assistant hotkey app.")
    parser.add_argument("--set-token", action="store_true", help="Save a GitHub Models token to local .env.")
    return parser.parse_args()


def save_token() -> None:
    token = getpass.getpass("GitHub token with models:read permission: ").strip()

    if not token:
        print("No token saved.")
        return

    lines = [
        "# Local secrets for PyAI. Do not publish this file.",
        f"PyAI_GITHUB_TOKEN={token}",
        f"PyAI_MODEL={DEFAULT_MODEL}",
    ]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved token locally to {ENV_FILE}")


def self_install_if_needed() -> bool:
    if not getattr(sys, "frozen", False):
        return False

    if os.environ.get("PyAI_NO_SELF_INSTALL", "").strip().lower() in {"1", "true", "yes"}:
        original_dir = os.environ.get("PyAI_ORIGINAL_DIR", "").strip()
        if original_dir:
            hide_extraction_folder(Path(original_dir))
        return False

    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_appdata:
        return False

    source_dir = app_dir()
    install_dir = Path(local_appdata) / APP_NAME
    source_exe = Path(sys.executable).resolve()
    installed_exe = install_dir / "PyAI.exe"

    try:
        if source_exe.parent.resolve() == install_dir.resolve():
            ensure_hidden_install(install_dir)
            hide_extraction_folder(Path.cwd())
            ensure_startup_shortcut(installed_exe, install_dir)
            return False
    except OSError:
        return False

    try:
        install_dir.mkdir(parents=True, exist_ok=True)
        (install_dir / "assets").mkdir(parents=True, exist_ok=True)
        copy_if_possible(source_exe, installed_exe, overwrite=True)
        copy_if_possible(source_dir / "assets" / "logo.png", install_dir / "assets" / "logo.png", overwrite=True)
        copy_if_possible(source_dir / "uninstall_PyAI.bat", install_dir / "uninstall_PyAI.bat", overwrite=True)
        copy_if_possible(source_dir / "token_aliases.json", install_dir / "token_aliases.json", overwrite=False)

        if (source_dir / ".env").exists():
            copy_if_possible(source_dir / ".env", install_dir / ".env", overwrite=True)
        elif (source_dir / ".env.example").exists():
            copy_if_possible(source_dir / ".env.example", install_dir / ".env.example", overwrite=True)

        ensure_hidden_install(install_dir)
        hide_extraction_folder(source_dir)
        ensure_startup_shortcut(installed_exe, install_dir)

        env = dict(os.environ)
        env["PyAI_NO_SELF_INSTALL"] = "1"
        env["PyAI_ORIGINAL_DIR"] = str(source_dir)
        subprocess.Popen(
            [str(installed_exe)],
            cwd=str(install_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return True
    except OSError:
        return False


def copy_if_possible(source: Path, target: Path, overwrite: bool) -> None:
    if not source.exists():
        return

    if target.exists() and not overwrite:
        return

    shutil.copy2(source, target)


def ensure_hidden_install(install_dir: Path) -> None:
    if sys.platform != "win32":
        return

    try:
        subprocess.run(
            ["attrib", "+h", "+s", str(install_dir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    except OSError:
        pass


def hide_extraction_folder(source_dir: Path) -> None:
    if sys.platform != "win32":
        return

    if not source_dir.exists():
        return

    ensure_hidden_install(source_dir)
    parent = source_dir.parent
    hide_in_vscode_explorer(parent, source_dir.name)
    if parent.name.lower() == "pyai":
        ensure_hidden_install(parent)
        hide_in_vscode_explorer(parent.parent, parent.name)


def hide_in_vscode_explorer(workspace_dir: Path, folder_name: str) -> None:
    if not workspace_dir.exists() or not folder_name:
        return

    settings_dir = workspace_dir / ".vscode"
    settings_path = settings_dir / "settings.json"

    try:
        settings_dir.mkdir(parents=True, exist_ok=True)
        if settings_path.exists():
            settings = json.loads(settings_path.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(settings, dict):
                settings = {}
        else:
            settings = {}

        excludes = settings.get("files.exclude")
        if not isinstance(excludes, dict):
            excludes = {}

        excludes[folder_name] = True
        excludes[f"**/{folder_name}"] = True
        excludes[APP_NAME] = True
        excludes[f"**/{APP_NAME}"] = True
        settings["files.exclude"] = excludes

        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass


def ensure_startup_shortcut(installed_exe: Path, install_dir: Path) -> None:
    if sys.platform != "win32" or not installed_exe.exists():
        return

    script = (
        "$startup=[Environment]::GetFolderPath('Startup'); "
        "$shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $startup 'PyAI.lnk')); "
        f"$shortcut.TargetPath='{ps_quote(str(installed_exe))}'; "
        f"$shortcut.WorkingDirectory='{ps_quote(str(install_dir))}'; "
        "$shortcut.Save()"
    )

    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    except OSError:
        pass


def ps_quote(value: str) -> str:
    return value.replace("'", "''")


def load_settings() -> dict[str, str]:
    settings = dict(os.environ)

    for config_file in config_files():
        if not config_file.exists():
            continue

        for raw_line in config_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip().lstrip("\ufeff")
            value = value.strip().strip('"').strip("'")
            if key == "PyAI_GITHUB_TOKEN" and is_placeholder_token(value):
                continue

            if key == "PyAI_GITHUB_TOKEN":
                existing = settings.get(key, "").strip()
                if not existing or not looks_like_github_token(resolve_token_alias(existing)):
                    settings[key] = value
                continue

            settings.setdefault(key, value)

    settings.setdefault("PyAI_MODEL", DEFAULT_MODEL)
    settings.setdefault("PyAI_MAX_TOKENS", "2600")
    settings.setdefault("PyAI_TEMPERATURE", "0.1")
    settings.setdefault("PyAI_LANGUAGE", "cpp")
    settings.setdefault("PyAI_SCREENSHOT_FALLBACK", "1")
    settings.setdefault("PyAI_SELF_CHECK", "1")
    settings.setdefault("PyAI_AI_REVIEW", "0")
    settings["PyAI_GITHUB_TOKEN"] = resolve_token_alias(settings.get("PyAI_GITHUB_TOKEN", ""))
    return settings


def config_files() -> list[Path]:
    base = app_dir()
    return [
        base / ".env",
        base / "PyAI.env",
        base / "config.env",
        base / ".env.example",
    ]


def is_placeholder_token(token: str) -> bool:
    return token.strip().lower() in TOKEN_PLACEHOLDERS


def looks_like_github_token(token: str) -> bool:
    value = token.strip()
    return value.startswith(("ghp_", "github_pat_", "gho_", "ghu_", "ghs_", "ghr_"))


def resolve_token_alias(token: str) -> str:
    value = token.strip()
    if not value or is_placeholder_token(value) or looks_like_github_token(value):
        return value

    alias = re.sub(r"[^A-Za-z0-9_]", "_", value).upper()
    for env_name in (f"PyAI_TOKEN_{alias}", f"PyAI_GITHUB_TOKEN_{alias}"):
        env_value = os.environ.get(env_name, "").strip()
        if looks_like_github_token(env_value):
            return env_value

    alias_file = app_dir() / "token_aliases.json"
    if alias_file.exists():
        try:
            aliases = json.loads(alias_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            aliases = {}

        for key in (value, value.lower(), alias):
            mapped = str(aliases.get(key, "")).strip()
            if looks_like_github_token(mapped):
                return mapped

    return value


def get_keyboard():
    global _KEYBOARD

    if _KEYBOARD is not None:
        return _KEYBOARD

    if sys.platform == "win32":
        import platform

        platform.system = lambda: "Windows"

    import keyboard

    _KEYBOARD = keyboard
    return _KEYBOARD


def get_active_window_title() -> str:
    hwnd = get_active_window_handle()
    return get_window_title(hwnd)


def get_active_window_handle() -> int:
    if sys.platform != "win32":
        return 0

    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def get_window_title(hwnd: int) -> str:
    if sys.platform != "win32" or not hwnd:
        return ""

    try:
        import ctypes

        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value
    except Exception:
        return ""


def get_target_vscode_title(active_window_title: str) -> str:
    if is_vscode_title(active_window_title):
        return active_window_title

    vscode_windows = list_vscode_windows()
    minimized_windows = [window for window in vscode_windows if window["minimized"]]
    if minimized_windows:
        return str(minimized_windows[0]["title"])

    if vscode_windows:
        return str(vscode_windows[0]["title"])

    return active_window_title


def is_vscode_title(title: str) -> bool:
    lowered = title.lower()
    return "visual studio code" in lowered or lowered.endswith(" - code")


def list_vscode_windows() -> list[dict[str, object]]:
    if sys.platform != "win32":
        return []

    windows: list[dict[str, object]] = []

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True

            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if is_vscode_title(title):
                windows.append({"hwnd": int(hwnd), "title": title, "minimized": bool(user32.IsIconic(hwnd))})

            return True

        user32.EnumWindows(enum_windows_proc(callback), 0)
    except Exception:
        return []

    return windows


def answer_selection(settings: dict[str, str], hotkey: str = "", mode: str = "solve") -> None:
    if not _RUN_LOCK.acquire(blocking=False):
        print("PyAI is already working. Please wait.")
        return

    try:
        if _STOP_EVENT.is_set():
            return

        selected_language = settings.get("PyAI_LANGUAGE", "cpp")
        detected = hotkey.upper() if hotkey else "shortcut"
        active_window_handle = get_active_window_handle()
        active_window_title = get_window_title(active_window_handle)
        target_window_title = get_target_vscode_title(active_window_title)
        print(f"\nHotkey detected: {detected}. Reading selected text...")
        selected_text = read_selected_text()
        visual_context = None

        if not selected_text:
            if mode == "solve" and screenshot_fallback_enabled(settings):
                print("No selectable text was copied. Capturing the active window screenshot...")
                visual_context = capture_problem_screenshot(active_window_handle, active_window_title)
                selected_text = screenshot_prompt_text(active_window_title)
                notify("PyAI", "Reading problem from screenshot.")
            else:
                notify("PyAI error", f"Select a question or code first, then press {format_hotkeys()}.")
                print("No selected text was copied. Try selecting text again, then press the hotkey.")
                return

        if _STOP_EVENT.is_set():
            print("Stopped before generating code.")
            return

        source_path = find_source_file_any(settings, selected_text, target_window_title)
        language = detect_language(selected_text, selected_language, target_window_title, source_path)
        if mode == "prompt":
            instruction = show_prompt_window(selected_text)
        elif mode == "comment":
            instruction = bangla_comment_instruction(language)
        else:
            instruction = default_instruction(selected_text)

        if not instruction:
            print("Prompt hidden. Cancelled.")
            return

        if mode == "comment":
            fix_context = None
        elif is_fix_instruction(instruction):
            fix_context = get_active_source_context(selected_text, settings, language, target_window_title, source_path)
            if not fix_context:
                fix_context = {"path": target_window_title or "selected_source", "code": selected_text}
        else:
            fix_context = get_fix_context(selected_text, settings, language, target_window_title, source_path)
            if is_fix_instruction(instruction) and not fix_context:
                fix_context = get_active_source_context(selected_text, settings, language, target_window_title, source_path)

        if visual_context:
            print(f"Screenshot captured: {visual_context['width']}x{visual_context['height']}.")
        else:
            print(f"Selected {len(selected_text)} characters.")
        print(f"Generating {language} code...")
        notify("PyAI", f"Working on {language} code...")
        answer = request_answer(selected_text, settings, language, fix_context, instruction, visual_context)
        code = clean_code_answer(answer)
        code = maybe_self_check_code(
            code,
            selected_text,
            settings,
            language,
            fix_context,
            instruction,
            visual_context,
            mode,
        )

        if _STOP_EVENT.is_set():
            print("Stopped. Answer was not copied.")
            return

        pyperclip.copy(code)
        if mode == "comment" and paste_into_current_selection(active_window_handle):
            print("Bangla comments pasted into the selected code.")
            notify("PyAI ready", "Bangla comments pasted into selected code.")
        elif mode == "comment":
            print("Bangla comments copied. Active window changed, so PyAI did not paste.")
            notify("PyAI ready", "Bangla comments copied. Press Ctrl+V.")
        elif mode == "prompt" and is_fix_instruction(instruction) and paste_into_current_selection(active_window_handle):
            saved_path = save_fixed_source_if_possible(fix_context, code)
            print("Fixed code pasted into the active file.")
            if saved_path:
                notify("PyAI ready", f"Fixed code pasted and saved: {saved_path.name}")
            else:
                notify("PyAI ready", "Fixed code pasted into the active file.")
        elif mode == "prompt" and is_fix_instruction(instruction):
            saved_path = save_fixed_source_if_possible(fix_context, code)
            if saved_path:
                print(f"Fixed code saved to {saved_path}.")
                notify("PyAI ready", f"Fixed code saved: {saved_path.name}")
            else:
                print("Fixed code copied. Active window changed, so PyAI did not paste.")
                notify("PyAI ready", "Fixed code copied. Press Ctrl+V in the selected file.")
        else:
            output_path = save_code_file(selected_text, code, language, settings, fix_context, target_window_title)
            open_in_vscode(output_path)
            print("Code copied to clipboard.")
            notify("PyAI ready", f"Code copied and opened in VS Code: {output_path.name}")
    except Exception as exc:  # noqa: BLE001 - top-level UX boundary
        message = clean_error(str(exc))
        write_error_log(str(exc))
        notify("PyAI error", message)
    finally:
        _RUN_LOCK.release()


def format_hotkeys() -> str:
    hotkeys = DIRECT_HOTKEYS + PROMPT_HOTKEYS + COMMENT_HOTKEYS
    return " / ".join(hotkey.upper() for hotkey in hotkeys)


def quick_exit() -> None:
    _STOP_EVENT.set()
    print("\nQuick exit pressed. PyAI is stopping...")
    notify("PyAI", "Quick exit pressed. PyAI is stopping.")


def toggle_toasts() -> None:
    if _TOASTS_HIDDEN.is_set():
        _TOASTS_HIDDEN.clear()
        print("\nToast notifications shown.")
        notify_force("PyAI", "Toast notifications are shown.")
        return

    print("\nToast notifications hidden. PyAI will work silently.")
    _TOASTS_HIDDEN.set()


def hide_prompt() -> None:
    global _PROMPT_ROOT

    _PROMPT_CANCEL_EVENT.set()
    root = _PROMPT_ROOT
    if root is not None:
        try:
            root.after(0, root.destroy)
        except Exception:
            pass


def show_prompt_window(selected_text: str) -> str | None:
    global _PROMPT_ROOT

    _PROMPT_CANCEL_EVENT.clear()
    result = {"instruction": None}
    root = Tk()
    _PROMPT_ROOT = root
    root.title("PyAI")
    root.configure(bg="#1e1e1e")
    root.attributes("-topmost", True)
    root.overrideredirect(True)
    root.resizable(False, False)

    width = 560
    height = 64
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, root.winfo_screenheight() - height - 58)
    root.geometry(f"{width}x{height}+{x}+{y}")

    try:
        root.attributes("-alpha", 0.98)
    except Exception:
        pass

    container = Frame(root, bg="#1e1e1e", padx=8, pady=8, highlightbackground="#454545", highlightthickness=1)
    container.pack(fill=BOTH, expand=True)

    row = Frame(container, bg="#1e1e1e")
    row.pack(fill="x")
    Label(row, text="PyAI", bg="#1e1e1e", fg="#d4d4d4", font=("Segoe UI", 8, "bold")).pack(side=LEFT, padx=(0, 8))

    entry = Entry(
        row,
        bg="#252526",
        fg="#d4d4d4",
        insertbackground="#d4d4d4",
        relief="flat",
        font=("Segoe UI", 9),
    )
    entry.pack(side=LEFT, fill="x", expand=True, ipady=5)
    entry.insert(0, "fix errors" if looks_like_error(selected_text) else "")
    entry.focus_force()

    def submit() -> None:
        result["instruction"] = entry.get().strip() or "solve this"
        root.destroy()

    def cancel() -> None:
        result["instruction"] = None
        root.destroy()

    button_font = ("Segoe UI", 8)
    Button(row, text="Run", command=submit, bg="#0e639c", fg="#ffffff", relief="flat", width=5, font=button_font).pack(side=LEFT, padx=(6, 0), ipady=1)
    Button(row, text="Hide", command=cancel, bg="#3c3c3c", fg="#d4d4d4", relief="flat", width=5, font=button_font).pack(side=LEFT, padx=(4, 0), ipady=1)

    root.bind("<Return>", lambda _event: submit())
    root.bind("<F10>", lambda _event: cancel())
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.mainloop()

    if _PROMPT_CANCEL_EVENT.is_set():
        result["instruction"] = None

    _PROMPT_ROOT = None
    return result["instruction"]


def screenshot_fallback_enabled(settings: dict[str, str]) -> bool:
    value = settings.get("PyAI_SCREENSHOT_FALLBACK", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def screenshot_prompt_text(active_window_title: str) -> str:
    title = active_window_title.strip() or "active website"
    return (
        "No selectable text was copied. "
        f"Read the attached screenshot from this active window and solve the visible programming problem: {title}"
    )


def capture_problem_screenshot(hwnd: int, active_window_title: str = "") -> dict[str, object]:
    if Image is None or ImageGrab is None or ImageStat is None:
        raise RuntimeError("Screenshot fallback needs Pillow. Rebuild PyAI after installing requirements.")

    bbox = get_window_bbox(hwnd)
    time.sleep(0.12)
    image = grab_screenshot_image(hwnd, bbox)

    if image.width < 100 or image.height < 100:
        raise RuntimeError("Could not capture a readable screenshot from the active window.")

    image = image.convert("RGB")
    resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    image.thumbnail(VISION_IMAGE_MAX_SIZE, resampling)

    mime = "image/png"
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    image_bytes = buffer.getvalue()

    if len(image_bytes) > 3_500_000:
        mime = "image/jpeg"
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=82, optimize=True)
        image_bytes = buffer.getvalue()

    encoded = base64.b64encode(image_bytes).decode("ascii")
    return {
        "data_url": f"data:{mime};base64,{encoded}",
        "width": image.width,
        "height": image.height,
        "title": active_window_title,
    }


def grab_screenshot_image(hwnd: int, bbox: tuple[int, int, int, int] | None):
    attempts: list[tuple[str, object]] = []

    if sys.platform == "win32" and hwnd:
        attempts.append(("window", lambda: ImageGrab.grab(window=hwnd)))

    if sys.platform == "win32":
        attempts.append(("screen crop", lambda: ImageGrab.grab(bbox=bbox, all_screens=True)))

    attempts.append(("bbox", lambda: ImageGrab.grab(bbox=bbox)))
    attempts.append(("full screen", lambda: ImageGrab.grab()))

    last_error = None
    for name, attempt in attempts:
        try:
            image = attempt()
        except (OSError, TypeError) as exc:
            last_error = exc
            continue

        if is_blank_screenshot(image):
            last_error = RuntimeError(f"{name} screenshot was blank")
            continue

        return image

    raise RuntimeError(f"Could not capture the active window screenshot. {last_error}")


def is_blank_screenshot(image) -> bool:
    if image.width < 100 or image.height < 100:
        return True

    sample = image.convert("L")
    sample.thumbnail((80, 80))
    stat = ImageStat.Stat(sample)
    mean = stat.mean[0]
    stddev = stat.stddev[0]

    return (mean < 8 and stddev < 6) or (mean > 248 and stddev < 3)


def get_window_bbox(hwnd: int) -> tuple[int, int, int, int] | None:
    if sys.platform != "win32" or not hwnd:
        return None

    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        user32 = ctypes.windll.user32
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None

        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width < 320 or height < 240:
            return None

        return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        return None


def read_selected_text() -> str:
    marker = "__PyAI_WAITING_FOR_SELECTION_COPY__"
    pyperclip.copy(marker)

    time.sleep(0.15)
    release_shortcut_modifiers()
    get_keyboard().send("ctrl+c")

    deadline = time.time() + 2.0
    selected_text = ""

    while time.time() < deadline:
        current = safe_paste()
        if current and current != marker:
            selected_text = current.strip()
            break
        time.sleep(0.1)

    return selected_text


def safe_paste() -> str:
    try:
        return pyperclip.paste() or ""
    except pyperclip.PyperclipException:
        return ""


def release_shortcut_modifiers() -> None:
    keyboard = get_keyboard()
    for key in ("ctrl", "alt", "shift"):
        try:
            keyboard.release(key)
        except Exception:
            pass


def post_models(payload: dict[str, object], token: str, timeout: int = 90):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": API_VERSION,
    }

    response = None
    for attempt in range(2):
        response = requests.post(API_URL, headers=headers, data=json.dumps(payload), timeout=timeout)
        if response.status_code != 429 or attempt == 1:
            return response

        wait_seconds = retry_after_seconds(response) or 8
        print(f"GitHub Models rate limit hit. Waiting {wait_seconds} seconds, then retrying once...")
        time.sleep(wait_seconds)

    return response


def retry_after_seconds(response) -> int | None:
    value = response.headers.get("Retry-After", "").strip()
    if not value:
        return None

    try:
        return max(2, min(30, int(float(value))))
    except ValueError:
        return None


def ensure_models_response_ok(response, model: str, visual_context: dict[str, object] | None, prefix: str) -> None:
    if response.ok:
        return

    detail = response.text[:220]
    if response.status_code == 401:
        raise RuntimeError("Token rejected. Check that .env has PyAI_GITHUB_TOKEN with a valid GitHub Models token.")
    if response.status_code == 403:
        raise RuntimeError("Token has no GitHub Models access. Enable GitHub Models access or use a token from an account that can use Models.")
    if response.status_code == 404:
        raise RuntimeError(f"Model not available for this token: {model}")
    if response.status_code == 429:
        raise RuntimeError("Too many requests. GitHub Models quota/rate limit hit. Wait a while, or use another token/account with available quota.")
    if visual_context and response.status_code in {400, 415, 422}:
        raise RuntimeError(f"Screenshot reading failed. Use a vision-capable model such as openai/gpt-4.1. {detail}")

    raise RuntimeError(f"{prefix} ({response.status_code}). {detail}")


def request_answer(
    prompt: str,
    settings: dict[str, str],
    language: str | None = None,
    fix_context: dict[str, str] | None = None,
    instruction: str = "",
    visual_context: dict[str, object] | None = None,
) -> str:
    token = settings["PyAI_GITHUB_TOKEN"].strip()
    model = settings.get("PyAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    max_tokens = int(settings.get("PyAI_MAX_TOKENS", "2600"))
    temperature = float(settings.get("PyAI_TEMPERATURE", "0.1"))
    language = language or choose_language(prompt, settings.get("PyAI_LANGUAGE", "cpp"))

    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are PyAI, a coding-focused assistant. "
                    f"Default programming language: {language}. "
                    "The user wants paste-ready competitive-programming solution code. "
                    "Solve the selected problem directly in the exact chosen language. "
                    "If Language is C++, write standard C++17 code. If Language is C, write standard C11 code. If Language is Python, write Python 3 code. "
                    "Read the statement carefully and match the required input and output format exactly, including case, labels, spacing, blank lines, and newlines. "
                    "Do not print prompts, menus, debug text, explanations, examples, or any extra output not requested by the problem. "
                    "Return only complete code, with no Markdown fences, no bullet lists, and no generated-by markers. "
                    "Write original, natural, human-readable code from the problem requirements instead of copying memorized templates. "
                    "Use concise meaningful names, straightforward control flow, and idiomatic style for the selected language. "
                    "Do not add filler variables, dead code, artificial complexity, random formatting, or obfuscation. "
                    "Avoid comments unless the original problem explicitly requires them. "
                    "Use fast input/output and avoid slow or memory-heavy patterns. "
                    "Choose the intended efficient algorithm, targeting under 1 second for typical online-judge limits. "
                    "Keep memory usage low by using simple arrays, counters, and streaming logic when possible. "
                    "Before returning code, internally check for Wrong Answer, Compile Error, Runtime Error, off-by-one mistakes, bad input parsing, integer overflow, uninitialized values, stack overflow, null/empty input, and exact output formatting mistakes. "
                    "Do not rely only on sample cases; solve the general problem under the likely constraints. "
                    "Use 64-bit integers for counts, sums, products, and indexes when overflow is possible. "
                    "Avoid recursion for deep constraints unless it is clearly safe. "
                    "For C/C++, include all required headers, declare main correctly, initialize variables, bounds-check arrays, and avoid non-standard or unsafe constructs that cause CE/RE. "
                    "For Python, guard empty input where needed and avoid recursion depth or TLE-prone quadratic logic unless constraints are tiny. "
                    "If constraints are missing, assume large inputs and choose a safe O(n), O(n log n), or better approach where appropriate. "
                    "If a screenshot is attached, read the visible website/problem text from the image, focus on the programming statement, input/output, samples, and constraints, then solve it. "
                    "If the screenshot clearly requires C, C++, or Python, follow that visible language requirement; otherwise use the default language. "
                    "If parts of the screenshot are cut off, infer the safest common interpretation from the visible title, examples, and constraints without adding explanation to the final answer. "
                    "For C use scanf/printf or fgets when suitable. For C++ use ios::sync_with_stdio(false) and cin.tie(nullptr). "
                    "For Python use sys.stdin.buffer and avoid quadratic loops for large inputs. "
                    "If the selected text contains compiler errors, runtime errors, tracebacks, or VS Code Problems output, diagnose and fix the code. "
                    "When fixing, return only the complete corrected source file. Do not return a diff, explanation, checklist, or partial snippet. "
                    "If the user asks for Bangla explanation comments, keep the selected code's behavior unchanged and return only that code with concise Bangla comments added using the correct comment syntax for the language."
                ),
            },
            {
                "role": "user",
                "content": build_user_message_content(prompt, language, fix_context, instruction, visual_context),
            },
        ],
    }

    response = post_models(payload, token)
    ensure_models_response_ok(response, model, visual_context, "GitHub Models request failed")

    data = response.json()
    answer = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

    if not answer:
        raise RuntimeError("GitHub Models returned an empty answer.")

    return answer


def self_check_enabled(settings: dict[str, str]) -> bool:
    value = settings.get("PyAI_SELF_CHECK", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def maybe_self_check_code(
    code: str,
    prompt: str,
    settings: dict[str, str],
    language: str,
    fix_context: dict[str, str] | None,
    instruction: str,
    visual_context: dict[str, object] | None,
    mode: str,
) -> str:
    if mode == "comment" or not self_check_enabled(settings):
        return code

    if len(code.strip()) < 20:
        return code

    compile_result = validate_code_locally(code, language)
    if compile_result["status"] == "ok":
        print(f"Local {language} compile/syntax check passed.")
    elif compile_result["status"] == "missing":
        print(str(compile_result["message"]))
    else:
        print("Local compile/syntax check failed. Repairing with compiler error...")
        notify("PyAI", "Compile check failed. Repairing code...")
        try:
            repaired = request_compile_repair_code(
                prompt,
                settings,
                language,
                fix_context,
                instruction,
                visual_context,
                code,
                str(compile_result["message"]),
            )
            repaired_code = clean_code_answer(repaired)
            repaired_result = validate_code_locally(repaired_code, language)
            if repaired_result["status"] == "ok":
                print(f"Repaired code passed local {language} compile/syntax check.")
            elif repaired_result["status"] == "fail":
                print(f"Repair still has compile risk: {clean_error(str(repaired_result['message']))}")
            if repaired_code.strip():
                code = repaired_code
        except Exception as exc:  # noqa: BLE001 - keep candidate if repair request fails
            print(f"Compile repair skipped: {clean_error(str(exc))}")

    if not ai_review_enabled(settings):
        return code

    try:
        print("Running optional AI review for WA/RE/output edge cases...")
        notify("PyAI", "Reviewing WA/RE edge cases...")
        checked = request_quality_checked_code(
            prompt,
            settings,
            language,
            fix_context,
            instruction,
            visual_context,
            code,
        )
        checked_code = clean_code_answer(checked)
        if checked_code.strip():
            return checked_code
    except Exception as exc:  # noqa: BLE001 - keep first answer if reviewer fails
        print(f"Self-check skipped: {clean_error(str(exc))}")

    return code


def ai_review_enabled(settings: dict[str, str]) -> bool:
    value = settings.get("PyAI_AI_REVIEW", "0").strip().lower()
    return value in {"1", "true", "yes", "on", "always"}


def validate_code_locally(code: str, language: str) -> dict[str, str]:
    if language == "Python":
        try:
            compile(code, "PyAI_candidate.py", "exec")
            return {"status": "ok", "message": "Python syntax ok."}
        except SyntaxError as exc:
            return {"status": "fail", "message": format_python_syntax_error(exc)}

    if language == "C":
        compiler = find_first_executable(["gcc", "clang"])
        if not compiler:
            return {"status": "missing", "message": "No C compiler found. Install MinGW/GCC to enable local CE check."}
        return run_c_family_syntax_check(code, compiler, ".c", ["-std=c11", "-Wall", "-Wextra", "-fsyntax-only"])

    if language == "C++":
        compiler = find_first_executable(["g++", "clang++"])
        if not compiler:
            return {"status": "missing", "message": "No C++ compiler found. Install MinGW/G++ to enable local CE check."}
        return run_c_family_syntax_check(code, compiler, ".cpp", ["-std=c++17", "-Wall", "-Wextra", "-fsyntax-only"])

    return {"status": "missing", "message": f"No local checker for {language}."}


def find_first_executable(names: list[str]) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def run_c_family_syntax_check(code: str, compiler: str, suffix: str, args: list[str]) -> dict[str, str]:
    try:
        with tempfile.TemporaryDirectory(prefix="PyAI_check_") as temp_dir:
            source_path = Path(temp_dir) / f"main{suffix}"
            source_path.write_text(code, encoding="utf-8")
            command = [compiler, *args, str(source_path)]
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=12,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
    except subprocess.TimeoutExpired:
        return {"status": "fail", "message": "Local compile check timed out."}
    except OSError as exc:
        return {"status": "missing", "message": f"Local compiler check unavailable: {exc}"}

    output = (result.stderr or result.stdout or "").strip()
    if result.returncode == 0:
        return {"status": "ok", "message": "Local compile check passed."}

    return {"status": "fail", "message": output[:3000] or f"Compiler exited with {result.returncode}."}


def format_python_syntax_error(exc: SyntaxError) -> str:
    location = f"line {exc.lineno}, column {exc.offset}" if exc.lineno else "unknown location"
    text = (exc.text or "").strip()
    return f"Python syntax error at {location}: {exc.msg}\n{text}"


def request_compile_repair_code(
    prompt: str,
    settings: dict[str, str],
    language: str,
    fix_context: dict[str, str] | None,
    instruction: str,
    visual_context: dict[str, object] | None,
    candidate_code: str,
    compiler_error: str,
) -> str:
    token = settings["PyAI_GITHUB_TOKEN"].strip()
    model = settings.get("PyAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    max_tokens = int(settings.get("PyAI_MAX_TOKENS", "2600"))

    parts = [
        f"Language: {language}",
        f"User instruction:\n{instruction or 'solve this problem'}",
        f"Selected text / problem:\n{prompt}",
        f"Candidate code:\n{candidate_code}",
        f"Compiler/syntax error:\n{compiler_error}",
        "Task: return only a complete corrected source file that compiles cleanly and preserves the required input/output format.",
    ]
    if fix_context:
        parts.append(f"Current source path:\n{fix_context['path']}")
        parts.append(f"Current source code:\n{fix_context['code']}")

    user_content: str | list[dict[str, object]] = "\n\n".join(parts)
    if visual_context:
        user_content = [
            {"type": "text", "text": f"{user_content}\n\nScreenshot is attached. Use it only to confirm the statement/output format."},
            {"type": "image_url", "image_url": {"url": str(visual_context["data_url"])}},
        ]

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You repair competitive-programming code after a real compiler/syntax check failed. "
                    "Fix every compile/syntax error, missing include/import, invalid syntax, type issue, undeclared identifier, wrong main signature, and obvious runtime hazard. "
                    "Return only complete source code in the selected language. No Markdown, no diff, no explanation."
                ),
            },
            {"role": "user", "content": user_content},
        ],
    }

    response = post_models(payload, token)
    ensure_models_response_ok(response, model, visual_context, "Compile repair request failed")
    data = response.json()
    answer = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if not answer:
        raise RuntimeError("GitHub Models returned an empty compile-repair answer.")
    return answer


def request_quality_checked_code(
    prompt: str,
    settings: dict[str, str],
    language: str,
    fix_context: dict[str, str] | None,
    instruction: str,
    visual_context: dict[str, object] | None,
    candidate_code: str,
) -> str:
    token = settings["PyAI_GITHUB_TOKEN"].strip()
    model = settings.get("PyAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    max_tokens = int(settings.get("PyAI_MAX_TOKENS", "2600"))

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are PyAI's strict final code reviewer. "
                    "Your job is to prevent Wrong Answer, Compile Error, Runtime Error, Time Limit Exceeded, Memory Limit Exceeded, and output-format mistakes. "
                    "Review the candidate against the problem statement and visible screenshot if provided. "
                    "Mentally compile the code for the selected language. "
                    "Check input parsing, required headers/imports, main function, integer overflow, uninitialized variables, array bounds, null/empty input, recursion depth, stack memory, off-by-one errors, and exact sample/general behavior. "
                    "If the candidate is already acceptable, return the same complete code. "
                    "If there is any real risk, return a corrected complete source file. "
                    "Return only final code, with no Markdown fences, no explanation, no diff, and no comments unless required by the problem."
                ),
            },
            {
                "role": "user",
                "content": build_quality_check_message_content(
                    prompt,
                    language,
                    fix_context,
                    instruction,
                    visual_context,
                    candidate_code,
                ),
            },
        ],
    }

    response = post_models(payload, token)
    ensure_models_response_ok(response, model, visual_context, "Self-check request failed")

    data = response.json()
    answer = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

    if not answer:
        raise RuntimeError("GitHub Models returned an empty self-check answer.")

    return answer


def build_quality_check_message_content(
    prompt: str,
    language: str,
    fix_context: dict[str, str] | None,
    instruction: str,
    visual_context: dict[str, object] | None,
    candidate_code: str,
):
    parts = [
        f"Language: {language}",
        f"User instruction:\n{instruction or 'solve this problem'}",
        f"Selected text / problem:\n{prompt}",
        f"Candidate code:\n{candidate_code}",
        (
            "Review task: return the final accepted source code only. "
            "Fix WA/CE/RE/TLE/MLE risks, exact input/output mistakes, and missing edge cases. "
            "Do not add any explanation."
        ),
    ]

    if fix_context:
        parts.append(f"Fix source path:\n{fix_context['path']}")
        parts.append(f"Original/current source code:\n{fix_context['code']}")

    text = "\n\n".join(parts)

    if not visual_context:
        return text

    title = str(visual_context.get("title", "")).strip()
    screenshot_note = (
        "Screenshot is attached. Re-read the visible statement, samples, constraints, and required language/output format from it while reviewing the candidate."
    )
    if title:
        screenshot_note += f"\nActive window title: {title}"

    return [
        {"type": "text", "text": f"{text}\n\n{screenshot_note}"},
        {"type": "image_url", "image_url": {"url": str(visual_context["data_url"])}},
    ]


def build_user_message_content(
    prompt: str,
    language: str,
    fix_context: dict[str, str] | None,
    instruction: str = "",
    visual_context: dict[str, object] | None = None,
):
    text = build_user_prompt(prompt, language, fix_context, instruction)

    if not visual_context:
        return text

    title = str(visual_context.get("title", "")).strip()
    screenshot_note = (
        "Screenshot mode: selected text could not be copied. "
        "Read the attached active-window screenshot. Ignore browser UI, ads, and unrelated sidebars. "
        "Extract the programming problem from the visible page, infer missing wording carefully from samples/constraints when needed, "
        "and return only the final complete source code."
    )
    if title:
        screenshot_note += f"\nActive window title: {title}"

    return [
        {"type": "text", "text": f"{text}\n\n{screenshot_note}"},
        {"type": "image_url", "image_url": {"url": str(visual_context["data_url"])}},
    ]


def build_user_prompt(prompt: str, language: str, fix_context: dict[str, str] | None, instruction: str = "") -> str:
    parts = [f"Language: {language}"]

    if instruction:
        parts.append(f"User instruction:\n{instruction}")

    parts.append(f"Selected text:\n{prompt}")

    if fix_context:
        parts.append(f"Fix source path:\n{fix_context['path']}")
        parts.append(f"Current source code:\n{fix_context['code']}")
        parts.append("Task: return the full corrected source code for that same file and nothing else.")

    return "\n\n".join(parts)


def default_instruction(selected_text: str) -> str:
    if looks_like_error(selected_text):
        return "fix errors"

    return "solve this problem"


def bangla_comment_instruction(language: str) -> str:
    return (
        f"Selected language: {language}. "
        "নির্বাচিত code অংশের মানে বাংলা comment আকারে বোঝাও। "
        "Original code-er behavior change korbe na. "
        "Only selected code return korbe, Markdown/explanation/code fence chara. "
        "Important line/block-er age concise বাংলা comment add korbe. "
        "Comment syntax target language onujayi hobe."
    )


def detect_language(
    prompt: str,
    default_language: str,
    active_window_title: str = "",
    source_path: Path | None = None,
) -> str:
    source_language = language_from_path(source_path)
    if source_language:
        return source_language

    title_language = language_from_filename_text(active_window_title)
    if title_language:
        return title_language

    selected_language = language_from_filename_text(prompt)
    if selected_language:
        return selected_language

    return choose_language(prompt, default_language)


def language_from_path(path: Path | None) -> str | None:
    if not path:
        return None

    return EXTENSION_LANGUAGE.get(path.suffix.lower())


def language_from_filename_text(text: str) -> str | None:
    if not text:
        return None

    patterns = [
        r"[A-Za-z]:\\[^\r\n\"<>|?*]+\.(?:py|c|cpp|cc|cxx|hpp)\b",
        r"\b[\w.-]+\.(?:py|c|cpp|cc|cxx|hpp)\b",
    ]

    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            suffix = Path(match.strip()).suffix.lower()
            language = EXTENSION_LANGUAGE.get(suffix)
            if language:
                return language

    return None


def choose_language(prompt: str, default_language: str) -> str:
    text = f" {prompt.lower()} "
    default = (default_language or "python").strip().lower()

    if any(marker in text for marker in ["c++", "cpp", ".cpp", "cplusplus"]):
        return "C++"

    c_markers = [
        " in c",
        "using c",
        "c language",
        " c program",
        " c code",
        "ansi c",
        "সি",
        "c দিয়ে",
        "c diye",
    ]

    if any(marker in text for marker in c_markers):
        return "C"

    if "python" in text or "py " in f"{text} " or "পাইথন" in text:
        return "Python"

    if default in {"c", "clang", "c language"}:
        return "C"

    if default in {"c++", "cpp", "cplusplus"}:
        return "C++"

    return "Python"


def clean_code_answer(answer: str) -> str:
    text = answer.strip()

    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()

    return text.strip("`").strip()


def save_code_file(
    question: str,
    code: str,
    language: str,
    settings: dict[str, str],
    fix_context: dict[str, str] | None = None,
    active_window_title: str = "",
) -> Path:
    if fix_context:
        output_dir = Path(fix_context["path"]).parent
    else:
        output_dir = get_output_dir(settings, active_window_title)

    output_dir.mkdir(parents=True, exist_ok=True)

    filename = make_filename(question, language, fix_context)
    output_path = unique_path(output_dir / filename)
    output_path.write_text(code, encoding="utf-8")
    return output_path


def get_output_dir(settings: dict[str, str], active_window_title: str = "") -> Path:
    configured_dir = settings.get("PyAI_OUTPUT_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser()

    vscode_dir = find_vscode_folder(active_window_title)
    if vscode_dir:
        return vscode_dir

    return app_dir() / "outputs"


def find_vscode_folder(active_window_title: str = "") -> Path | None:
    appdata = os.environ.get("APPDATA", "")
    storage_paths = [
        Path(appdata) / "Code" / "User" / "globalStorage" / "storage.json",
        Path(appdata) / "Code - Insiders" / "User" / "globalStorage" / "storage.json",
    ]

    valid_folders: list[Path] = []

    for storage_path in storage_paths:
        if not storage_path.exists():
            continue

        try:
            data = json.loads(storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        folders = data.get("backupWorkspaces", {}).get("folders", [])
        for item in folders:
            folder = uri_to_path(item.get("folderUri", ""))
            if folder and folder.exists():
                valid_folders.append(folder)

    if not valid_folders:
        return None

    title = active_window_title.lower()
    if title:
        for folder in valid_folders:
            if folder.name.lower() in title or str(folder).lower() in title:
                return folder

    return valid_folders[-1]


def uri_to_path(uri: str) -> Path | None:
    if not uri.startswith("file://"):
        return None

    parsed = urlparse(uri)
    path = unquote(parsed.path).lstrip("/")
    return Path(path)


def make_filename(question: str, language: str, fix_context: dict[str, str] | None = None) -> str:
    extension = {"Python": ".py", "C": ".c", "C++": ".cpp"}.get(language, ".txt")

    if fix_context:
        source_path = Path(fix_context["path"])
        return f"fixed_{source_path.stem}{source_path.suffix or extension}"

    words = re.findall(r"[a-zA-Z0-9]+", question.lower())
    stop_words = {"the", "and", "for", "with", "using", "write", "program", "code", "solve", "problem", "input", "output"}
    useful_words = [word for word in words if word not in stop_words][:6]
    stem = "_".join(useful_words) or "PyAI_solution"
    return f"{stem}{extension}"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate

    return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")


def open_in_vscode(path: Path) -> None:
    try:
        subprocess.Popen(["code", "-r", str(path.parent), str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        if sys.platform == "win32":
            os.startfile(path)


def paste_into_current_selection(expected_hwnd: int) -> bool:
    try:
        if sys.platform == "win32" and expected_hwnd and get_active_window_handle() != expected_hwnd:
            return False

        time.sleep(0.18)
        release_shortcut_modifiers()
        get_keyboard().send("ctrl+v")
        return True
    except Exception:
        return False


def save_fixed_source_if_possible(fix_context: dict[str, str] | None, code: str) -> Path | None:
    if not fix_context:
        return None

    raw_path = fix_context.get("path", "")
    if not raw_path:
        return None

    path = Path(raw_path)
    if not path.exists() or not path.is_file() or path.suffix.lower() not in {".py", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"}:
        return None

    try:
        path.write_text(code, encoding="utf-8")
    except OSError:
        return None

    return path


def get_fix_context(
    selected_text: str,
    settings: dict[str, str],
    language: str,
    active_window_title: str = "",
    source_path: Path | None = None,
) -> dict[str, str] | None:
    if not looks_like_error(selected_text):
        return None

    source_path = source_path or find_source_file(settings, language, selected_text, active_window_title)
    if not source_path:
        return None

    try:
        code = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if len(code) > 24000:
        code = code[:24000]

    return {"path": str(source_path), "code": code}


def looks_like_error(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "error",
        "warning",
        "traceback",
        "exception",
        "syntaxerror",
        "nameerror",
        "typeerror",
        "undefined",
        "not declared",
        "expected",
        "cannot find",
        "failed",
        "pylance",
        "problems",
        "segmentation fault",
    ]
    return any(marker in lowered for marker in markers)


def is_fix_instruction(instruction: str) -> bool:
    lowered = instruction.lower()
    markers = ["fix", "error", "bug", "debug", "solve error", "repair", "correct"]
    return any(marker in lowered for marker in markers)


def get_active_source_context(
    selected_text: str,
    settings: dict[str, str],
    language: str,
    active_window_title: str,
    source_path: Path | None = None,
) -> dict[str, str] | None:
    source_path = source_path or find_source_file(settings, language, selected_text, active_window_title)
    if not source_path:
        return None

    try:
        code = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        code = selected_text

    if selected_text.strip() and not looks_like_error(selected_text):
        code = selected_text

    if len(code) > 24000:
        code = code[:24000]

    return {"path": str(source_path), "code": code}


def find_source_file_any(settings: dict[str, str], selected_text: str, active_window_title: str) -> Path | None:
    root = get_output_dir(settings, active_window_title)
    if not root.exists():
        return None

    extensions = all_source_extensions()

    source_from_text = find_source_file_from_text(selected_text, root, extensions)
    if source_from_text:
        return source_from_text

    source_from_title = find_source_file_from_title(active_window_title, root, extensions)
    if source_from_title:
        return source_from_title

    if looks_like_error(selected_text):
        return find_recent_source_file(root, extensions)

    return None


def all_source_extensions() -> set[str]:
    extensions: set[str] = set()
    for values in SOURCE_EXTENSIONS.values():
        extensions.update(values)
    return extensions


def find_source_file(settings: dict[str, str], language: str, selected_text: str, active_window_title: str) -> Path | None:
    root = get_output_dir(settings, active_window_title)
    if not root.exists():
        return None

    extensions = set(SOURCE_EXTENSIONS.get(language, [".c", ".cpp", ".py"]))

    source_from_text = find_source_file_from_text(selected_text, root, extensions)
    if source_from_text:
        return source_from_text

    source_from_title = find_source_file_from_title(active_window_title, root, extensions)
    if source_from_title:
        return source_from_title

    return find_recent_source_file(root, extensions)


def find_recent_source_file(root: Path, extensions: set[str]) -> Path | None:
    candidates: list[Path] = []

    for path in root.rglob("*"):
        if len(candidates) > 1000:
            break

        if any(part in SKIP_DIRS for part in path.parts):
            continue

        if path.is_file() and path.suffix.lower() in extensions and not path.name.startswith("fixed_"):
            candidates.append(path)

    if not candidates:
        return None

    return max(candidates, key=lambda item: item.stat().st_mtime)



def find_source_file_from_text(text: str, root: Path, extensions: set[str]) -> Path | None:
    path_pattern = r"[A-Za-z]:\\[^\r\n\"<>|?*]+\.(?:py|c|cpp|cc|cxx|h|hpp)"
    for match in re.findall(path_pattern, text, flags=re.IGNORECASE):
        candidate = Path(match.strip())
        if candidate.exists() and candidate.suffix.lower() in extensions:
            return candidate

    name_pattern = r"\b[\w.-]+\.(?:py|c|cpp|cc|cxx|h|hpp)\b"
    for filename in re.findall(name_pattern, text, flags=re.IGNORECASE):
        candidate = find_file_by_name(root, filename, extensions)
        if candidate:
            return candidate

    return None


def find_source_file_from_title(title: str, root: Path, extensions: set[str]) -> Path | None:
    if not title:
        return None

    name_pattern = r"\b[\w.-]+\.(?:py|c|cpp|cc|cxx|h|hpp)\b"
    for filename in re.findall(name_pattern, title, flags=re.IGNORECASE):
        candidate = find_file_by_name(root, filename, extensions)
        if candidate:
            return candidate

    return None


def find_file_by_name(root: Path, filename: str, extensions: set[str]) -> Path | None:
    matches: list[Path] = []
    target = filename.lower()

    for path in root.rglob("*"):
        if len(matches) > 100:
            break

        if any(part in SKIP_DIRS for part in path.parts):
            continue

        if path.is_file() and path.name.lower() == target and path.suffix.lower() in extensions:
            matches.append(path)

    if not matches:
        return None

    return max(matches, key=lambda item: item.stat().st_mtime)


def notify(title: str, message: str) -> None:
    if _TOASTS_HIDDEN.is_set():
        print(f"{title}: {message}")
        return

    notify_force(title, message)


def notify_force(title: str, message: str) -> None:
    if Notification is not None and sys.platform == "win32":
        kwargs = {
            "app_id": APP_NAME,
            "title": title,
            "msg": message,
            "duration": "short",
        }

        if LOGO_PATH.exists():
            kwargs["icon"] = str(LOGO_PATH)

        toast = Notification(**kwargs)
        toast.show()
        return

    print(f"{title}: {message}")


def clean_error(message: str) -> str:
    if len(message) <= 240:
        return message
    return f"{message[:237]}..."


def write_error_log(message: str) -> None:
    try:
        ERROR_LOG_PATH.write_text(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{message}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
