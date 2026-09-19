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
#define MyAppVersion "1.3.1"
#define MyAppExeName "Talkative.exe"

[Setup]
AppId={{7E1B3C52-9A44-4E0B-B7D1-52B4A46C1F0D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Sumit Chatterjee
DefaultDirName={userpf}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
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
begin
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
