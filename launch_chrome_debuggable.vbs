' Launches your REAL Chrome with remote debugging enabled, so Jarvis's
' browser tools can connect to it directly (browser_session.py) and use
' whatever's actually logged in -- instead of a separate, logged-out copy.
'
' IMPORTANT: close every Chrome window first (check the taskbar/system
' tray for lingering background processes too) -- the debugging port can
' only be enabled at launch, not added to an already-running Chrome.
'
' Run this instead of your normal Chrome shortcut whenever you want Jarvis
' to be able to control your browser. Everything else about Chrome (your
' profile, extensions, open tabs from last time) works exactly as normal.
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """C:\Program Files\Google\Chrome\Application\chrome.exe"" --remote-debugging-port=9222", 1, False
