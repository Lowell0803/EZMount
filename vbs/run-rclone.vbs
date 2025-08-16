Option Explicit

Dim fso, wsh, scriptFolder, appdata, confPath, logFile
Dim labelsA, remotesA, lettersA
Dim i, pw, cmd, rc, ts

Set fso = CreateObject("Scripting.FileSystemObject")
Set wsh = CreateObject("WScript.Shell")

' Arrays for labels, remotes, and letters
labelsA  = Array("Acads", "Cloud")
remotesA = Array("backblaze-acads:", "backblaze-cloud:")
lettersA = Array("X:", "Y:")

' Paths
scriptFolder = fso.GetParentFolderName(WScript.ScriptFullName)
appdata = wsh.ExpandEnvironmentStrings("%APPDATA%") & "\rclone"
logFile = scriptFolder & "\rclone_mount.log"
confPath = ""

' Check if rclone.conf exists
If fso.FileExists(scriptFolder & "\rclone.conf") Then
    confPath = scriptFolder & "\rclone.conf"
ElseIf fso.FileExists(appdata & "\rclone.conf") Then
    confPath = appdata & "\rclone.conf"
Else
    MsgBox "rclone.conf not found in script folder or AppData\rclone", vbCritical, "Error"
    WScript.Quit 1
End If

' Ask if password is needed
pw = InputBox("If your rclone.conf is password protected, enter the password here." & vbCrLf & _
              "If not, just leave it blank.", "Rclone Config Password")

' Clear old log
If fso.FileExists(logFile) Then fso.DeleteFile logFile

' Write header to log
Set ts = fso.OpenTextFile(logFile, 8, True)
ts.WriteLine "===== RCLONE MOUNT SESSION " & Now & " ====="
ts.Close

' Build and run mount commands
For i = 0 To UBound(labelsA)
    cmd = "rclone mount " & remotesA(i) & " " & lettersA(i) & _
          " --vfs-cache-mode full --config """ & confPath & """ --log-file """ & logFile & """ --log-level DEBUG"
    
    If pw <> "" Then
        cmd = "rclone --ask-password=false --password-command ""cmd /c echo " & pw & """ mount " & remotesA(i) & " " & lettersA(i) & _
            " --vfs-cache-mode full --config """ & confPath & """ --log-file """ & logFile & """ --log-level DEBUG"
    Else
        cmd = "rclone mount " & remotesA(i) & " " & lettersA(i) & _
            " --vfs-cache-mode full --config """ & confPath & """ --log-file """ & logFile & """ --log-level DEBUG"
    End If

    
    ' Log what command is being launched
    Set ts = fso.OpenTextFile(logFile, 8, True)
    ts.WriteLine "[" & Now & "] Launching: " & cmd
    ts.Close
    
    ' Run minimized in background
    rc = wsh.Run("cmd /c " & cmd, 0, False)
Next

MsgBox "Mount commands launched. See rclone_mount.log for details.", vbInformation, "Done"
