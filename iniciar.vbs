' Abre la app con doble clic desde Windows: arranca el servidor en WSL (oculto)
' si no está corriendo y luego abre el navegador.
Const APP_URL = "http://127.0.0.1:8000/"

Set shell = CreateObject("WScript.Shell")

' \\wsl.localhost\Ubuntu\home\... -> distro "Ubuntu" y ruta Linux /home/...
scriptDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\") - 1)
parts = Split(Mid(scriptDir, 3), "\")
distro = parts(1)
linuxDir = "/" & Join(Slice(parts, 2), "/")

If Not ServidorActivo() Then
  shell.Run "wsl.exe -d " & distro & " -- bash -lc ""cd '" & linuxDir & "' && bash run.sh > servidor.log 2>&1""", 0, False
  For i = 1 To 90
    WScript.Sleep 1000
    If ServidorActivo() Then Exit For
  Next
  If Not ServidorActivo() Then
    MsgBox "No se pudo iniciar el servidor. Revisa servidor.log en la carpeta del proyecto.", vbExclamation, "YouTube Downloader"
    WScript.Quit 1
  End If
End If

shell.Run APP_URL

Function ServidorActivo()
  On Error Resume Next
  Set http = CreateObject("MSXML2.ServerXMLHTTP")
  http.setTimeouts 1000, 1000, 1000, 1000
  http.Open "GET", APP_URL, False
  http.Send
  ServidorActivo = (Err.Number = 0 And http.Status = 200)
End Function

Function Slice(arr, start)
  Dim result(), i
  ReDim result(UBound(arr) - start)
  For i = start To UBound(arr)
    result(i - start) = arr(i)
  Next
  Slice = result
End Function
