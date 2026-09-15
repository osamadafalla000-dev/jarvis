' Launches Jarvis's wake-word loop hidden (no console window), logging to
' jarvis_log.txt. Used by the "Jarvis Assistant" scheduled task so it starts
' automatically at logon, like a real always-on assistant.
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Ozmwd\Downloads\jarvis"
' Best-effort auto-update: pull the latest code before starting, so every
' restart runs whatever's newest on the claude/yo-njo3in branch without a
' manual `git pull` first. Waits for it to finish (True) since it has to
' happen before python starts; silently does nothing useful if this folder
' isn't a git checkout, git isn't on PATH, or there's no network -- it just
' logs to update_log.txt and Jarvis still starts on whatever code is here.
WshShell.Run "cmd /c git pull >> update_log.txt 2>&1", 0, True
WshShell.Run "cmd /c ""C:\Users\Ozmwd\Downloads\jarvis\venv\Scripts\python.exe"" -u main.py >> jarvis_log.txt 2>&1", 0, False
