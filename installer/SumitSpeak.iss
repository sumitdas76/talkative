; Sumit Speak installer (product spec section 8).
; Build:  ISCC.exe installer\SumitSpeak.iss   (from the project root, after
; a fresh PyInstaller build in dist\).
;
; Decisions from the spec, deliberately:
; - Per-user install: no admin prompt, no UAC. Installs under
;   %LOCALAPPDATA%\Programs\Sumit Speak.
; - The grammar engine (~1.5 GB, invisible in the UI) is bundled so
;   "Cleaned up" works from the very first dictation. The speech model is
;   NOT bundled -- the app downloads it on first run (the app owns
;   download/retry machinery; a dead installer download would leave a
;   broken install).
; - The installer never touches the network. The VC++ runtime is bundled
;   and installed silently only when absent.
; - Uninstall asks whether to also remove models and settings (no
;   half-gigabyte left behind).

#define MyAppName "Sumit Speak"
#define MyAppVersion "1.1.1"
#define MyAppExeName "SumitSpeak.exe"
; The bundled grammar engine is packed in at COMPILE time from the build
; machine's installed copy (a plain path, not an install-time constant).
#define GrammarSource GetEnv("LOCALAPPDATA") + "\SumitSpeak\models\grammar"

[Setup]
AppId={{7E1B3C52-9A44-4E0B-B7D1-52B4A46C1F0D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Sumit Chatterjee
DefaultDirName={userpf}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=SumitSpeakSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\assets\icon.ico

[Tasks]
Name: "autostart"; Description: "Start {#MyAppName} when Windows starts"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Grammar engine into the app-owned model folder; never overwrite one the
; user already has (it may be newer via the update system).
Source: "{#GrammarSource}\*"; DestDir: "{localappdata}\SumitSpeak\models\grammar"; \
    Flags: recursesubdirs onlyifdoesntexist nocompression
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
    SettingsFile := ExpandConstant('{localappdata}\SumitSpeak\settings.json');
    if not FileExists(SettingsFile) then
    begin
      ForceDirectories(ExpandConstant('{localappdata}\SumitSpeak'));
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
    if SuppressibleMsgBox('Also remove the downloaded speech models and your '
              + 'settings?' + #13#10 + 'This frees up to 4 GB of disk space.',
              mbConfirmation, MB_YESNO, IDNO) = IDYES then
      DelTree(ExpandConstant('{localappdata}\SumitSpeak'), True, True, True);
  end;
end;
