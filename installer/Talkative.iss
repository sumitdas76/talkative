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
#define MyAppVersion "1.3.24"
#define MyAppExeName "Talkative.exe"

[Setup]
AppId={{7E1B3C52-9A44-4E0B-B7D1-52B4A46C1F0D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
; Plain name in Apps & features (Inno's default adds "version X.Y.Z"), so
; winget manifests can match it without a per-release edit.
UninstallDisplayName={#MyAppName}
AppPublisher=Sumit Das
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
; Look (2026-11-23, the user: "so like Windows XP ... people will run
; away from this window"): Inno 6.7's Windows 11 style, following the
; system light/dark setting, no divider lines; branded art from
; assets/generate_installer_art.py at every Windows scale. One page
; (welcome + Install), then progress, then the app opens by itself:
; no folder, tasks, ready or finished pages. Needs Inno Setup >= 6.7.
WizardStyle=modern dynamic windows11 hidebevels
WizardImageFile=art\welcome-100.png,art\welcome-125.png,art\welcome-150.png,art\welcome-175.png,art\welcome-200.png,art\welcome-250.png
WizardImageFileDynamicDark=art\welcome-100.png,art\welcome-125.png,art\welcome-150.png,art\welcome-175.png,art\welcome-200.png,art\welcome-250.png
WizardSmallImageFile=art\small-100.png,art\small-125.png,art\small-150.png,art\small-175.png,art\small-200.png,art\small-250.png
WizardSmallImageFileDynamicDark=art\small-100.png,art\small-125.png,art\small-150.png,art\small-175.png,art\small-200.png,art\small-250.png
DisableWelcomePage=no
DisableDirPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\assets\icon.ico
; The privacy policy is a link on the welcome page (was a full page of
; PRIVACY.md before 2026-11-23, for SignPath Foundation's terms; SignPath
; declined on 2026-11-13. If we reapply, check whether a link is enough).
; "Start when Windows starts" is a checkbox on the same page (was the
; [Tasks] page).

[Messages]
SetupWindowTitle=Install %1
WelcomeLabel1=Talk instead of type
WelcomeLabel2=Talkative turns your voice into text in any app. Hold the key, speak, let go, and your words appear where the cursor is.%n%nInstalls just for you, with no admin rights. It takes a few seconds.
WizardInstalling=Installing
; The welcome page's own "Click Next to continue" line: there is no Next.
ClickNext=
InstallingLabel=Setting up [name]. It opens by itself when it's ready.

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "redist\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; \
    StatusMsg: "Installing system components..."; Check: VCRuntimeMissing
; The app itself is opened from CurStepChanged(ssDone), after the
; autostart choice is written: with the finished page gone, a postinstall
; entry's timing relative to that write isn't something to rely on.

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

var
  AutostartBox: TNewCheckBox;
  PrivacyLink: TNewStaticText;
  LocationLabel: TNewStaticText;
  ChangeLink: TNewStaticText;
  BandStrip: TBitmapImage;

{ Install location (user, 2026-11-23: let people choose where it goes).
  A line on the welcome page, not a folder page, so the install stays one
  click. Offered only on a first install: a reinstall or update keeps the
  folder it already has (Inno's UsePreviousAppDir), otherwise the updater
  and Start menu would point at a stale copy. }
function PreviouslyInstalled: Boolean;
begin
  Result := RegKeyExists(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7E1B3C52-9A44-4E0B-B7D1-52B4A46C1F0D}_is1');
end;

{ The installer never asks for admin rights, so a folder like Program
  Files can't be used: test by writing a file there first. }
function CanWriteTo(Dir: String): Boolean;
var
  Existed: Boolean;
  Probe: String;
begin
  Existed := DirExists(Dir);
  Probe := AddBackslash(Dir) + '.talkative-write-test';
  Result := ForceDirectories(Dir) and SaveStringToFile(Probe, '', False);
  if Result then
    DeleteFile(Probe);
  if not Existed then
    RemoveDir(Dir);
end;

procedure ShowLocation;
begin
  LocationLabel.Caption := 'Installs to ' + MinimizePathName(WizardForm.DirEdit.Text,
    LocationLabel.Font, WizardForm.WelcomeLabel2.Width - ScaleX(90));
  ChangeLink.Left := LocationLabel.Left + LocationLabel.Width + ScaleX(8);
end;

procedure ChangeLocation(Sender: TObject);
var
  Dir: String;
begin
  Dir := WizardForm.DirEdit.Text;
  if not BrowseForFolder('Choose where to install {#MyAppName}. A {#MyAppName} folder is made inside the folder you pick.', Dir, True) then
    Exit;
  if CompareText(ExtractFileName(RemoveBackslashUnlessRoot(Dir)), '{#MyAppName}') <> 0 then
    Dir := AddBackslash(Dir) + '{#MyAppName}';
  if not CanWriteTo(Dir) then
  begin
    MsgBox('Windows doesn''t let {#MyAppName} install there without admin rights.' + #13#10
      + 'Pick a folder in your user folder or on another drive.', mbError, MB_OK);
    Exit;
  end;
  WizardForm.DirEdit.Text := Dir;
  ShowLocation;
end;

procedure OpenPrivacy(Sender: TObject);
var
  ResultCode: Integer;
begin
  ShellExecAsOriginalUser('open', 'https://github.com/sumitdas76/talkative/blob/main/PRIVACY.md',
    '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
end;

procedure InitializeWizard;
var
  Page: TNewNotebookPage;
  Panel: TBitmapImage;
  R: TRect;
begin
  Page := WizardForm.WelcomePage;

  { The brand panel runs the full height of the window, beside the
    buttons too (user, 2026-11-23: it should fill the entire left side).
    Inno's welcome image stops above the button band, and a picture on
    the form itself is always drawn under the page (a graphic control
    can't sit above a windowed one; tried). So the band beside the
    buttons gets its own strip in the art's bottom color (the gradient
    ends there), and the two read as one panel. }
  Panel := WizardForm.WizardBitmapImage;
  BandStrip := TBitmapImage.Create(WizardForm);
  BandStrip.Parent := WizardForm;
  BandStrip.Left := 0;
  BandStrip.Top := Panel.Height;
  BandStrip.Width := Panel.Width;
  BandStrip.Height := WizardForm.ClientHeight - Panel.Height;
  BandStrip.Bitmap.Width := 8;
  BandStrip.Bitmap.Height := 8;
  BandStrip.Bitmap.Canvas.Brush.Color := $644421; { #214464, BGR }
  R.Left := 0; R.Top := 0; R.Right := 8; R.Bottom := 8;
  BandStrip.Bitmap.Canvas.FillRect(R);
  BandStrip.Stretch := True;
  { Inno appends blank lines + ClickNext to this label; trim them so the
    checkbox sits right under the text. }
  WizardForm.WelcomeLabel2.Caption := Trim(WizardForm.WelcomeLabel2.Caption);
  WizardForm.WelcomeLabel2.AdjustHeight;

  AutostartBox := TNewCheckBox.Create(WizardForm);
  AutostartBox.Parent := Page;
  AutostartBox.Caption := 'Start {#MyAppName} when Windows starts';
  AutostartBox.Checked := True;
  AutostartBox.Left := WizardForm.WelcomeLabel2.Left;
  AutostartBox.Top := WizardForm.WelcomeLabel2.Top + WizardForm.WelcomeLabel2.Height + ScaleY(20);
  AutostartBox.Width := WizardForm.WelcomeLabel2.Width;
  AutostartBox.Height := ScaleY(22);

  LocationLabel := TNewStaticText.Create(WizardForm);
  LocationLabel.Parent := Page;
  LocationLabel.Left := WizardForm.WelcomeLabel2.Left;
  LocationLabel.Top := AutostartBox.Top + AutostartBox.Height + ScaleY(14);
  ChangeLink := TNewStaticText.Create(WizardForm);
  ChangeLink.Parent := Page;
  ChangeLink.Caption := 'Change';
  ChangeLink.Cursor := crHand;
  ChangeLink.Font.Style := [fsUnderline];
  ChangeLink.Font.Color := clHotLight;
  ChangeLink.OnClick := @ChangeLocation;
  ChangeLink.Top := LocationLabel.Top;
  ShowLocation;
  if PreviouslyInstalled then
  begin
    LocationLabel.Visible := False;
    ChangeLink.Visible := False;
  end;

  { The privacy link sits in the button band, lined up with the text above
    and centred on the buttons, so the band isn't an empty strip. }
  PrivacyLink := TNewStaticText.Create(WizardForm);
  PrivacyLink.Parent := WizardForm;
  PrivacyLink.Caption := 'Privacy policy';
  PrivacyLink.Cursor := crHand;
  PrivacyLink.Font.Style := [fsUnderline];
  PrivacyLink.Font.Color := clHotLight;
  PrivacyLink.OnClick := @OpenPrivacy;
  PrivacyLink.Left := WizardForm.WelcomeLabel2.Left;
  PrivacyLink.Top := WizardForm.NextButton.Top
    + (WizardForm.NextButton.Height - PrivacyLink.Height) div 2;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  { Panel and link belong to the welcome page only; the progress page
    uses the full width. }
  BandStrip.Visible := CurPageID = wpWelcome;
  PrivacyLink.Visible := CurPageID = wpWelcome;
  if CurPageID = wpWelcome then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  SettingsFile: string;
  ResultCode: Integer;
begin
  { Open the app when an interactive install is done (no finished page).
    Silent installs (winget, the app's own /UPDATE) don't; update mode
    relaunches from DeinitializeSetup. }
  if (CurStep = ssDone) and not WizardSilent then
    ShellExec('', ExpandConstant('{app}\{#MyAppExeName}'), '', '',
      SW_SHOWNORMAL, ewNoWait, ResultCode);
  { The app owns the autostart registry sync via its settings; the installer
    only seeds the setting on a fresh install so the two never fight. }
  if (CurStep = ssPostInstall) and AutostartBox.Checked then
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
