' Auto-launches Chrome with remote debugging enabled at every login, so a
' debuggable Chrome window is normally already there by the time Jarvis
' needs it -- no more manually closing Chrome and running
' launch_chrome_debuggable.vbs by hand every time. (browser_session.py also
' now auto-launches Chrome itself if it finds none running at all when a
' browser tool is used -- this just means that usually won't even be
' necessary, since Chrome's already up before Jarvis asks.)
'
' Only launches if Chrome isn't already running (checked via tasklist), so
' it doesn't fight a Chrome that auto-started some other way, or double-
' launch on a slow login. If Chrome IS already running without the flag
' (e.g. it was open before this ran), this can't fix that retroactively --
' close every Chrome window once and it'll come back debuggable next time,
' same as always.
Set WshShell = CreateObject("WScript.Shell")
Set WshExec = WshShell.Exec("tasklist /FI ""IMAGENAME eq chrome.exe"" /NH")
chromeRunning = False
Do While Not WshExec.StdOut.AtEndOfStream
    line = WshExec.StdOut.ReadLine()
    If InStr(LCase(line), "chrome.exe") > 0 Then
        chromeRunning = True
    End If
Loop
If Not chromeRunning Then
    WshShell.Run """C:\Program Files\Google\Chrome\Application\chrome.exe"" --remote-debugging-port=9222", 1, False
End If
