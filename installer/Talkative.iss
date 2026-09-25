; Talkative installer (product spec section 8).
; Build:  ISCC.exe installer\Talkative.iss   (from the project root, after
; a fresh PyInstaller build in dist\).
;
; Decisions from the spec, deliberately:
; - Per-user install: no admin prompt, no UAC. Installs under
;   %LOCALAPPDATA%\Programs\Talkative.
; - Neither the speech model nor the grammar engine is bundled (changed
;   2026-09-13, see CHANGELOG.md): the app ships defaulting to Cloud
;   processing, which needs neither. Both are downloadable on demand from
;   Settings -> General -> Processing if the user switches to Local (the
;   app owns download/retry machinery for both -- a dead installer
;   download would leave a broken install). This also shrinks the
;   installer from ~1.6 GB to a small base.
; - The installer itself never touches the network -- only the app does,
;   post-install, and only when the user opts into Local. The VC++
;   runtime is bundled and installed silently only when absent.
; - Uninstall asks whether to also remove models and settings (no
;   half-gigabyte left behind).

#define MyAppName "Talkative"
#define MyAppVersion "1.3.5"
#define MyAppExeName "Talkative.exe"

[Setup]
AppId={{7E1B3C52-9A44-4E0B-B7D1-52B4A46C1F0D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Sumit Chatterjee
DefaultDirName={userpf}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; Detect and close any running Talkative.exe (via Windows Restart Manager,
; which checks actual open file handles in {app} -- not just a process-name
; match, so it catches both the onefile bootloader process AND its child
; interpreter process, since --onefile always launches as a parent+child
; pair at runtime) before install OR uninstall proceeds. Added 2026-09-20
; after a user reported the app still running (and still visible in Task
; Manager) after uninstalling -- CurUninstallStepChanged below only ran
; AFTER files were already gone, so nothing had ever actually stopped the
; process. Also fixes the long-standing manual "check for and kill a live
; instance before rebuilding" step documented in the project's own
; CLAUDE.md, though scripts\rebuild.ps1's own check is unaffected since it
; runs before ISCC.exe, not through this installer.
CloseApplications=yes
RestartApplications=no
OutputDir=Output
OutputBaseFilename=TalkativeSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\assets\icon.ico

[Tasks]
Name: "autostart"; Description: "Start {#MyAppName} when Windows starts"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "redist\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; \
    StatusMsg: "Installing system components..."; Check: VCRuntimeMissing
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent

[Code]
{ /UPDATE is passed only by the app's own one-click updater (updater.py),
  always together with /VERYSILENT. In that mode the installer makes sure
  the old app is gone before copying files, and relaunches the app when it
  finishes -- including when the install FAILED (Inno has already rolled
  the old files back by then), so an update can never leave the user with
  Talkative silently not running. }
function IsUpdateMode: Boolean;
begin
  Result := Pos('/UPDATE', UpperCase(GetCmdTail)) > 0;
end;

function TalkativeRunning: Boolean;
var
  ResultCode: Integer;
  OutFile: String;
  Output: AnsiString;
begin
  Result := False;
  OutFile := ExpandConstant('{tmp}\tasklist.txt');
  if Exec(ExpandConstant('{cmd}'),
          '/C tasklist /FI "IMAGENAME eq {#MyAppExeName}" /NH > "' + OutFile + '"',
          '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
     and LoadStringFromFile(OutFile, Output) then
    Result := Pos(Lowercase('{#MyAppExeName}'), Lowercase(String(Output))) > 0;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  I: Integer;
begin
  Result := '';
  if IsUpdateMode then
  begin
    { The app exits by itself right after launching this installer; wait
      up to ~15s for that, then force-kill whatever is left so the EXE
      isn't locked. NO /T here, unlike uninstall below: this installer was
      started BY Talkative, so it's part of Talkative's process tree, and
      /T killed the installer itself mid-update (found in live testing,
      2026-09-25). /IM alone still gets both onefile processes -- they
      share the EXE name. tasklist's output contains the EXE name only
      while a matching process exists. }
    for I := 1 to 30 do
    begin
      if not TalkativeRunning then
        Break;
      Sleep(500);
    end;
    if TalkativeRunning then
    begin
      Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#MyAppExeName}',
        '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      Sleep(1000);
    end;
  end;
end;

procedure DeinitializeSetup;
var
  ResultCode: Integer;
  Exe: String;
begin
  if not IsUpdateMode then
    Exit;
  try
    Exe := ExpandConstant('{app}\{#MyAppExeName}');
  except
    Exe := ExpandConstant('{userpf}\{#MyAppName}\{#MyAppExeName}');
  end;
  if FileExists(Exe) then
    ShellExec('', Exe, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
end;

function VCRuntimeMissing: Boolean;
var
  Installed: Cardinal;
begin
  Result := True;
  if RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
                        'Installed', Installed) then
    Result := Installed <> 1;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  SettingsFile: string;
begin
  { The app owns the autostart registry sync via its settings; the installer
    only seeds the setting on a fresh install so the two never fight. }
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('autostart') then
  begin
    SettingsFile := ExpandConstant('{localappdata}\Talkative\settings.json');
    if not FileExists(SettingsFile) then
    begin
      ForceDirectories(ExpandConstant('{localappdata}\Talkative'));
      SaveStringToFile(SettingsFile, '{' + #13#10 +
        '  "start_with_windows": true' + #13#10 + '}' + #13#10, False);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    { Belt-and-suspenders backstop on top of CloseApplications=yes above --
      that relies on Restart Manager prompting interactively, which can't
      happen on a silent/unattended uninstall. /T kills the whole process
      tree (the onefile bootloader parent AND its child interpreter
      process, not just whichever PID happens to match first), so this
      doesn't depend on getting the parent/child relationship right by
      hand. Exit code ignored -- "no matching process" is the common,
      expected case, not a failure. }
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#MyAppExeName} /T',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    { SuppressibleMsgBox with IDNO default: a silent uninstall must never
      delete the user's models and settings. }
    if SuppressibleMsgBox('Also remove the downloaded voice and grammar '
              + 'models and your settings?' + #13#10
              + 'This frees up to 4 GB of disk space.',
              mbConfirmation, MB_YESNO, IDNO) = IDYES then
      DelTree(ExpandConstant('{localappdata}\Talkative'), True, True, True);
  end;
end;
