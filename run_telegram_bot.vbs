' Launches the Telegram bot hidden (no console window), logging to
' telegram_bot_log.txt. Used by the "Jarvis Telegram Bot" scheduled task so
' phone access works automatically after every reboot/login too.
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Ozmwd\Downloads\jarvis"
' Best-effort auto-update: pull the latest code before starting, so every
' restart runs whatever's newest on the claude/yo-njo3in branch without a
' manual `git pull` first. Waits for it to finish (True) since it has to
' happen before python starts; silently does nothing useful if this folder
' isn't a git checkout, git isn't on PATH, or there's no network -- it just
' logs to update_log.txt and Jarvis still starts on whatever code is here.
WshShell.Run "cmd /c git pull >> update_log.txt 2>&1", 0, True
WshShell.Run "cmd /c ""C:\Users\Ozmwd\Downloads\jarvis\venv\Scripts\python.exe"" -u telegram_bot.py >> telegram_bot_log.txt 2>&1", 0, False
