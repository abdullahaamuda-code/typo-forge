' typo-forge silent launcher — runs the daemon with no console window.
' Works from any folder: pythonw.exe is resolved from PATH, the script path
' is derived from this file's own location.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run """pythonw.exe"" """ & scriptDir & "\typo_forge.py""", 0, False
