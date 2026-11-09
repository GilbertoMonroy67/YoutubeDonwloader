' Detiene el servidor de la app que corre oculto en WSL.
Set shell = CreateObject("WScript.Shell")
shell.Run "wsl.exe -- pkill -f ""uvicorn app.main:app""", 0, True
MsgBox "YouTube Downloader se detuvo.", vbInformation, "YouTube Downloader"
