Option Explicit
Randomize

Set fso = CreateObject("Scripting.FileSystemObject")
Set wsh = CreateObject("WScript.Shell")

scriptFolder   = fso.GetParentFolderName(WScript.ScriptFullName)
If scriptFolder = "" Then scriptFolder = "."
' ==== READ CSV FOR MOUNTS ====
Dim labelsA(), remotesA(), lettersA()
Dim ts, line, fields, idx

idx = -1
If Not fso.FileExists(scriptFolder & "\mounts.csv") Then
    MsgBox "mounts.csv not found!", vbCritical, "Missing CSV"
    WScript.Quit 1
End If

Set ts = fso.OpenTextFile(scriptFolder & "\mounts.csv", 1, False)
' Skip header
If Not ts.AtEndOfStream Then ts.ReadLine

Do While Not ts.AtEndOfStream
    line = Trim(ts.ReadLine)
    If line <> "" Then
        fields = Split(line, ",")
        If UBound(fields) >= 2 Then
            idx = idx + 1
            ReDim Preserve labelsA(idx)
            ReDim Preserve remotesA(idx)
            ReDim Preserve lettersA(idx)

            labelsA(idx) = Trim(fields(0))
            remotesA(idx) = Trim(fields(1))
            lettersA(idx) = Trim(fields(2))
        End If
    End If
Loop
ts.Close
' =======================================

Dim fso, wsh, scriptFolder, appdataRclone, confPath, logFile, pw
Dim i, menu, choice


appdataRclone  = wsh.ExpandEnvironmentStrings("%APPDATA%") & "\rclone"
logFile        = scriptFolder & "\rclone_mount.log"

' Find rclone.conf (script folder first, then %APPDATA%\rclone)
If fso.FileExists(scriptFolder & "\rclone.conf") Then
  confPath = scriptFolder & "\rclone.conf"
ElseIf fso.FileExists(appdataRclone & "\rclone.conf") Then
  confPath = appdataRclone & "\rclone.conf"
Else
  MsgBox "rclone.conf not found in:" & vbCrLf & _
         " - " & scriptFolder & "\rclone.conf" & vbCrLf & _
         " - " & appdataRclone & "\rclone.conf", vbCritical, "Missing config"
  WScript.Quit 1
End If

' Ensure log exists
EnsureLogExists

' ===== Ask for password (masked) at the very beginning =====
pw = GetMaskedPassword() ' user can leave blank if config is not encrypted

WriteLog "===== RCLONE SESSION " & Now & " ====="
If pw <> "" Then
  WriteLog "[INFO] Password provided (hidden)"
  
  ' ---- Test password validity ----
  If Not TestPassword(pw) Then
    WriteLog "[ERROR] Invalid or missing password. Exiting."
    MsgBox "Invalid or missing rclone.conf password. Exiting.", vbCritical, "Rclone EZMount"
    WScript.Quit 1
  End If
Else
  WriteLog "[INFO] No password provided"
  
  ' ---- Test whether config requires password ----
  If Not TestPassword("") Then
    WriteLog "[ERROR] Config is encrypted but no password entered. Exiting."
    MsgBox "rclone.conf is encrypted but no password entered. Exiting.", vbCritical, "Rclone EZMount"
    WScript.Quit 1
  End If
End If

' ===== Menu with current status =====
menu = BuildStatus() & vbCrLf & vbCrLf & _
       "Choose action:" & vbCrLf & _
       "1. Mount Acads (" & lettersA(0) & ")" & vbCrLf & _
       "2. Unmount Acads" & vbCrLf & _
       "3. Mount Cloud (" & lettersA(1) & ")" & vbCrLf & _
       "4. Unmount Cloud" & vbCrLf & _
       "A. Mount All" & vbCrLf & _
       "B. Unmount All" & vbCrLf & _
       "L. Open Log" & vbCrLf & _
       "Q. Quit"

choice = InputBox(menu, "Rclone EZMount")

If choice = "" Then WScript.Quit
Select Case UCase(choice)
  Case "1": MountOne 0
  Case "2": UnmountOne 0
  Case "3": MountOne 1
  Case "4": UnmountOne 1
  Case "A": MountAll
  Case "B": UnmountAll
  Case "L": wsh.Run "notepad.exe """ & logFile & """", 1, False
  Case "Q": ' do nothing
  Case Else
    MsgBox "Invalid selection.", vbExclamation
End Select

MsgBox "Done. Check " & logFile, vbInformation, "Rclone"

' ==========================
' Helpers / Subroutines
' ==========================

Sub MountOne(idx)
  Dim cmd, helperPath
  If pw <> "" Then
    ' Safer: create a short-lived helper .cmd to echo password
    helperPath = CreatePasswordHelper(pw)
    cmd = "rclone --ask-password=false --password-command ""cmd /c """ & helperPath & """"" " & _
          "mount " & remotesA(idx) & " " & lettersA(idx) & _
          " --vfs-cache-mode full --config """ & confPath & """ --log-file """ & logFile & """ --log-level DEBUG"
  Else
    cmd = "rclone mount " & remotesA(idx) & " " & lettersA(idx) & _
          " --vfs-cache-mode full --config """ & confPath & """ --log-file """ & logFile & """ --log-level DEBUG"
  End If

  WriteLog "[" & Now & "] Launching mount: " & labelsA(idx) & " -> " & lettersA(idx)
  wsh.Run "cmd /c " & cmd, 0, False

  If pw <> "" Then
    ' give rclone a second to read helper, then delete it
    WScript.Sleep 3000
    On Error Resume Next
    fso.DeleteFile helperPath, True
    On Error GoTo 0
  End If
End Sub

Sub UnmountOne(idx)
  ' Try to terminate only the matching rclone mount for this remote/letter
  Dim svc, procs, p, line, hit
  hit = False
  On Error Resume Next
  Set svc = GetObject("winmgmts:root\cimv2")
  Set procs = svc.ExecQuery("SELECT * FROM Win32_Process WHERE Name='rclone.exe'")
  For Each p In procs
    line = LCase(p.CommandLine)
    If InStr(line, " mount ") > 0 And _
       InStr(line, LCase(remotesA(idx))) > 0 And _
       (InStr(line, " " & LCase(lettersA(idx)) & " ") > 0 Or InStr(line, """" & LCase(lettersA(idx)) & """") > 0) Then
      p.Terminate
      WriteLog "[" & Now & "] Terminated rclone PID " & p.ProcessId & " for " & labelsA(idx)
      hit = True
    End If
  Next
  On Error GoTo 0
  If Not hit Then
    WriteLog "[" & Now & "] No specific rclone process found for " & labelsA(idx) & " — skipping"
  End If
End Sub

Sub MountAll()
  Dim k
  For k = 0 To UBound(labelsA)
    MountOne k
    WScript.Sleep 400
  Next
End Sub

Sub UnmountAll()
  ' Kill all rclone mounts (simple)
  wsh.Run "cmd /c taskkill /f /im rclone.exe", 0, False
  WriteLog "[" & Now & "] Unmounted ALL (taskkill)"
End Sub

Function BuildStatus()
  Dim s, k, st
  s = "Status:" & vbCrLf
  For k = 0 To UBound(labelsA)
    If DriveIsMounted(lettersA(k)) Then
      st = "Mounted"
    Else
      st = "Not mounted"
    End If
    s = s & "- " & labelsA(k) & "  " & remotesA(k) & " -> " & lettersA(k) & "  [" & st & "]" & vbCrLf
  Next
  BuildStatus = s
End Function

Function DriveIsMounted(letter)
  On Error Resume Next
  DriveIsMounted = fso.DriveExists(letter)
  On Error GoTo 0
End Function

Sub EnsureLogExists()
  On Error Resume Next
  If Not fso.FileExists(logFile) Then
    Dim ts
    Set ts = fso.CreateTextFile(logFile, True)
    If Not ts Is Nothing Then ts.Close
  End If
  On Error GoTo 0
End Sub

Sub WriteLog(msg)
  On Error Resume Next
  Dim ts
  If Not fso.FileExists(logFile) Then
    Set ts = fso.CreateTextFile(logFile, True)
    If Not ts Is Nothing Then ts.Close
  End If
  Set ts = fso.OpenTextFile(logFile, 8, True)
  ts.WriteLine msg
  ts.Close
  On Error GoTo 0
End Sub

Function CreatePasswordHelper(plain)
  Dim helperPath, tf
  helperPath = scriptFolder & "\._pw_" & CStr(Int((Rnd()*900000)+100000)) & ".cmd"
  Set tf = fso.CreateTextFile(helperPath, True)
  tf.WriteLine "@echo off"
  tf.WriteLine "echo " & plain
  tf.Close
  On Error Resume Next
  fso.GetFile(helperPath).Attributes = 2 ' hidden
  On Error GoTo 0
  CreatePasswordHelper = helperPath
End Function

Function GetMaskedPassword()
  Dim ps, ex, out
  ps = "powershell -NoProfile -Command " & _
     """$p = Read-Host 'Enter rclone.conf password (leave blank if none)' -AsSecureString; " & _
     "$b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($p); " & _
     "[Runtime.InteropServices.Marshal]::PtrToStringAuto($b)"""
  On Error Resume Next
  Set ex = wsh.Exec(ps)
  If Err.Number <> 0 Then
    On Error GoTo 0
    GetMaskedPassword = ""
    Exit Function
  End If
  On Error GoTo 0
  out = ex.StdOut.ReadAll
  GetMaskedPassword = Trim(out)
End Function

Function TestPassword(plain)
  Dim helperPath, cmd, exitCode
  If plain <> "" Then
    helperPath = CreatePasswordHelper(plain)
    cmd = "cmd /c rclone listremotes --ask-password=false --password-command ""cmd /c """ & helperPath & """"" --config """ & confPath & """ >nul 2>&1"
    exitCode = wsh.Run(cmd, 0, True)
    On Error Resume Next
    fso.DeleteFile helperPath, True
    On Error GoTo 0
  Else
    cmd = "cmd /c rclone listremotes --ask-password=false --config """ & confPath & """ >nul 2>&1"
    exitCode = wsh.Run(cmd, 0, True)
  End If
  TestPassword = (exitCode = 0)
End Function
