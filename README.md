# PyAI

PyAI is a Windows Python hotkey assistant for coding help.

Start PyAI, select any problem text and press `F8` to create a solution file in the target VS Code folder. If a website problem cannot be selected, keep the page visible and press `F8`; PyAI reads the active window screenshot. Select code or an error message and press `Ctrl+I` to open the prompt. Type `fix errors`, `optimize`, or any instruction, then press Enter. Select code and press `Ctrl+Alt+B` to add Bangla explanation comments.

`Code ready and copied. Paste it wherever you need.`

Generated code is locally checked before final copy when possible. Python syntax is checked inside PyAI; C/C++ compile checks run automatically if GCC/G++ or Clang/Clang++ is installed. If a local compile error is found, PyAI asks the model to repair with the exact compiler error.

Developer license: Nuren Zarif Haque

Logo: `assets/logo.png`

## Important security note

Do not publish your GitHub token in source code.

This project stores the real token only in local `.env`. Save or replace your token with:

```powershell
python main.py --set-token
```

That creates a local `.env` file, and `.env` is ignored by git.

If you pasted a real token in chat or anywhere public, revoke it from GitHub and create a new token with `models:read` permission.

## Install

```powershell
python -m pip install -r requirements.txt
python main.py --set-token
python main.py
```

You can also double-click `run_pyai.bat` after installing requirements and saving the token.

## Use

1. Start PyAI.
2. Select problem text, code, or an error from VS Code Problems/terminal. If website text cannot be selected, leave that page visible.
3. Press `F8` to solve directly into a new file. If no selected text is copied, `F8` uses screenshot reading automatically. Press `Ctrl+I` to open the prompt for selected text/code.
4. Type an instruction, such as `fix errors`, then press Enter.
5. To understand selected code, press `Ctrl+Alt+B`; Bangla comments are pasted into the selected code.
6. Wait for the toast notification.
7. For fixes, the selected code is replaced in the same editor. For new solutions, use the opened VS Code file or paste the copied code.

Press `Esc` to exit PyAI.
Press `F9` to hide/show toast notifications. When hidden, PyAI works silently.
Press `F10` to hide/cancel the prompt window.
Run `uninstall_PyAI.bat` to stop PyAI, remove Startup, remove the installed app folder, and clean PyAI VS Code exclude entries. It does not delete unrelated project files.

Language is detected from the detected source file first, then the VS Code window title: `.cpp` uses C++, `.py` uses Python, and `.c` uses C. If multiple VS Code windows are open, PyAI uses the active VS Code window first, then a minimized VS Code window, then the latest folder from VS Code storage.

## Build EXE

```powershell
.\build_exe.ps1
```

You can also double-click `build_exe.bat`; it keeps the window open so build errors are visible.

The executable will be created in `dist\PyAI.exe`.

Build note: the build script tries Python 3.14, 3.13, then 3.12.

Keep `.env` private. Do not bundle it with the EXE when publishing.

## Run EXE

After building or downloading the zip, keep these next to each other:

```text
dist\PyAI.exe
dist\.env.example
dist\assets\logo.png
```

On a new Windows 10/11 PC, open `.env.example`, replace `your_token_here` with a GitHub token, save it, then run `PyAI.exe`. You can also copy `.env.example` to a private `.env`. GitHub Desktop, Git, Python, PowerShell scripts, or packages are not required for the EXE.

If GitHub Models request fails, check that the token is valid and the GitHub account has GitHub Models access. PyAI writes the latest detailed error to `last_error.txt` beside the EXE.

Double-click `PyAI.exe`, select text anywhere, press `F8` for direct solve-to-file or press `Ctrl+I` for the prompt. Press `F10` to hide the prompt, `F9` to hide/show toast notifications, and `Esc` to stop PyAI.

## Install Without Commands

GitHub source zip URLs like `https://github.com/.../zipball/main` always extract into a generated top folder. This folder name is created by GitHub and cannot be changed from the repository files.

When `PyAI.exe` is started from any extracted folder, it copies itself into `%LOCALAPPDATA%\PyAI`, marks that installed folder hidden, creates a Windows Startup shortcut, starts the installed copy, and exits the temporary copy. If it was started from a `PyAI` extraction folder, it also hides that extraction folder and writes VS Code `files.exclude` settings for that folder. Run `uninstall_PyAI.bat` to remove only PyAI app files, Startup, and PyAI VS Code exclude entries.

Do not publish real tokens. If you want to write a short alias in `.env`, configure the real token only on that PC using an environment variable named like `PyAI_TOKEN_ALIASNAME`, or a private `token_aliases.json` beside the EXE. A public EXE cannot safely turn an alias into a real token unless that secret exists privately on the PC.

```json
{
  "aliasname": "github_pat_or_ghp_token_here"
}
```

GitHub Models can return rate-limit or too-many-requests errors. If that happens, wait a while and try again, or use another valid token/account with available GitHub Models quota.

To make C++ the default language, add this to `.env`:

```text
PyAI_LANGUAGE=cpp
```

To disable screenshot fallback:

```text
PyAI_SCREENSHOT_FALLBACK=0
```

To disable the local correctness/compile self-check:

```text
PyAI_SELF_CHECK=0
```

To enable an extra AI review pass for WA/RE/output edge cases:

```text
PyAI_AI_REVIEW=1
```
