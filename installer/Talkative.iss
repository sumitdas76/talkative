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
#define MyAppVersion "1.3.25"
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
; force (2026-11-23): if Talkative survives PrepareToInstall's own close, Restart
; Manager terminates it instead of failing (a tray app never answers its
; polite close request). Uninstall uses this too.
CloseApplications=force
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
; The welcome page places its own controls (panel strip, location box,
; privacy link) at fixed spots; a resizable window would leave them behind.
WizardResizable=no
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
DiskSpaceMBLabel=Needs about [mb] MB of free space.
DiskSpaceGBLabel=Needs about [gb] GB of free space.
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

var
  { A copy running from the install folder was closed by PrepareToInstall
    (normal, non-update install); DeinitializeSetup reopens it unless
    ssDone already opened the new version. }
  KilledRunning: Boolean;
  Launched: Boolean;

{ Close Talkative.exe processes running from this install folder only
  (a portable or second copy elsewhere doesn't lock these files and is
  left alone). True when one was running. }
function CloseCopyInApp: Boolean;
var
  ResultCode: Integer;
  OutFile, Exe: String;
  Output: AnsiString;
begin
  Exe := ExpandConstant('{app}\{#MyAppExeName}');
  StringChangeEx(Exe, '''', '''''', True);
  OutFile := ExpandConstant('{tmp}\closed.txt');
  Exec(ExpandConstant('{cmd}'),
    '/C powershell.exe -NoProfile -NonInteractive -Command "Get-Process '
    + '{#MyAppName} -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq '''
    + Exe + ''' } | ForEach-Object { $_.Id; Stop-Process -Id $_.Id -Force }" > "'
    + OutFile + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := LoadStringFromFile(OutFile, Output) and (Trim(String(Output)) <> '');
  if Result then
    Sleep(800);
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
  end
  else if TalkativeRunning then
  begin
    { A normal install over a running copy (2026-11-23, user: choosing
      "Automatically close the applications" ended in "Setup was unable
      to automatically close all applications"). Windows' Restart Manager
      asks programs to close through their windows; Talkative is a tray
      app and never answers, so that always failed. Clicking Install is
      the consent: close it here, before Inno's own files-in-use check,
      so that page never shows; ssDone opens the new version. Called on
      the Install click (the ready page is off). }
    KilledRunning := CloseCopyInApp;
    if KilledRunning then
      Log('Talkative is running: closing it before installing');
  end;
end;

procedure DeinitializeSetup;
var
  ResultCode: Integer;
  Exe: String;
begin
  if not IsUpdateMode then
  begin
    { Closed for a silent install (winget upgrade) or a failed one: never
      leave the user without dictation. As the signed-in user, not the
      installer's possibly elevated account. }
    if KilledRunning and not Launched then
    begin
      Exe := ExpandConstant('{app}\{#MyAppExeName}');
      if FileExists(Exe) then
        ShellExecAsOriginalUser('open', Exe, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
    end;
    Exit;
  end;
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
  LocationHeading: TNewStaticText;
  BandStrip: TBitmapImage;

{ Install location (user, 2026-11-23: let people choose where it goes; a
  text line with a "Change" link was rejected as not good enough). An
  "Install location" section on the welcome page: Inno's own folder box,
  Browse button (its folder dialog adds "\Talkative" to the pick) and
  space note, moved there from the hidden folder page, so the install
  stays one page. Offered only on a first install: a reinstall or update
  keeps the folder it already has (Inno's UsePreviousAppDir), otherwise
  the updater and Start menu would point at a stale copy. }
function PreviouslyInstalled: Boolean;
begin
  Result := RegKeyExists(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7E1B3C52-9A44-4E0B-B7D1-52B4A46C1F0D}_is1');
end;

{ The installer never asks for admin rights, so a folder like Program
  Files can't be used: test by writing a file there first. }
function CanWriteTo(Dir: String): Boolean;
var
  Probe, Parent: String;
begin
  if DirExists(Dir) then
  begin
    Probe := AddBackslash(Dir) + '.talkative-write-test';
    Result := SaveStringToFile(Probe, '', False);
    if Result then
      DeleteFile(Probe);
    Exit;
  end;
  { Not there yet: Setup will create it inside the nearest folder that
    exists, so test making a folder there (and remove it again) instead
    of creating the whole path and leaving empty parents behind. }
  Parent := Dir;
  while not DirExists(Parent) and (ExtractFileDir(Parent) <> Parent) do
    Parent := ExtractFileDir(Parent);
  Probe := AddBackslash(Parent) + '.talkative-write-test';
  Result := CreateDir(Probe);
  if Result then
    RemoveDir(Probe);
end;

{ True when the folder has anything in it besides . and .. }
function HasFiles(Dir: String): Boolean;
var
  F: TFindRec;
begin
  Result := False;
  if FindFirst(AddBackslash(Dir) + '*', F) then
  try
    repeat
      if (F.Name <> '.') and (F.Name <> '..') then
      begin
        Result := True;
        Exit;
      end;
    until not FindNext(F);
  finally
    FindClose(F);
  end;
end;

{ The folder page (which normally checks the path) is never shown, so
  the Install click checks it: a full path, and one we can write to. }
function GetDriveType(lpRootPathName: String): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';

function UnderFolder(Dir, Parent: String): Boolean;
begin
  Result := (Parent <> '')
    and (Pos(Lowercase(AddBackslash(Parent)), Lowercase(AddBackslash(Dir))) = 1);
end;

{ A folder synced by OneDrive: it can hold the EXE while syncing and
  break an update, and "files on demand" can leave it offline. }
function InOneDrive(Dir: String): Boolean;
begin
  Result := UnderFolder(Dir, GetEnv('OneDrive'))
    or UnderFolder(Dir, GetEnv('OneDriveConsumer'))
    or UnderFolder(Dir, GetEnv('OneDriveCommercial'));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir: String;
  Kind: Cardinal;
begin
  Result := True;
  { Silent installs (winget, the app's updater, /DIR= from an admin) are
    not checked: Inno calls this even then, and a message box would wait
    for a click nobody can give (found in testing, 2026-11-23). }
  if (CurPageID <> wpWelcome) or PreviouslyInstalled or WizardSilent then
    Exit;
  Dir := RemoveBackslashUnlessRoot(Trim(WizardForm.DirEdit.Text));
  WizardForm.DirEdit.Text := Dir;
  Result := False;
  if Copy(Dir, 1, 2) = '\\' then
  begin
    MsgBox('{#MyAppName} can''t be installed in a network folder: it has to be there '
      + 'every time Windows starts.' + #13#10#13#10 + 'Pick a folder on this PC.',
      mbError, MB_OK);
    Exit;
  end;
  if (Length(Dir) < 3) or (Copy(Dir, 2, 2) <> ':\') then
  begin
    MsgBox('Enter a full folder path, for example C:\Apps\{#MyAppName}, or click Browse.',
      mbError, MB_OK);
    Exit;
  end;
  { A drive root, or a folder that already holds other files (typed by
    hand: Browse adds \Talkative itself), gets a Talkative folder of its
    own inside it. Otherwise the app would treat <folder>\models as its
    own, uninstall could delete it, and the folder lock would re-permission
    the user's files (neutral QA, 2026-11-23). }
  if (Length(Dir) = 3) or (DirExists(Dir) and HasFiles(Dir)
      and not FileExists(AddBackslash(Dir) + '{#MyAppExeName}')) then
  begin
    Dir := AddBackslash(Dir) + '{#MyAppName}';
    if DirExists(Dir) and HasFiles(Dir)
        and not FileExists(AddBackslash(Dir) + '{#MyAppExeName}') then
    begin
      MsgBox(Dir + ' already has other files in it.' + #13#10#13#10
        + 'Pick an empty folder, or click Browse.', mbError, MB_OK);
      Exit;
    end;
    WizardForm.DirEdit.Text := Dir;
    MsgBox('That folder already has other files in it, so {#MyAppName} gets a folder '
      + 'of its own inside it:' + #13#10#13#10 + Dir, mbInformation, MB_OK);
  end;
  { GetDriveType: 2 removable (USB stick, SD card), 4 network (mapped
    drive), 5 CD/DVD. }
  Kind := GetDriveType(Copy(Dir, 1, 3));
  if (Kind = 4) or (Kind = 5) then
  begin
    MsgBox('{#MyAppName} can''t be installed on a network or CD/DVD drive: it has to be '
      + 'there every time Windows starts.' + #13#10#13#10 + 'Pick a folder on this PC.',
      mbError, MB_OK);
    Exit;
  end;
  if (Kind = 2) and (MsgBox(Copy(Dir, 1, 2) + ' is a removable drive. When it isn''t '
      + 'plugged in, {#MyAppName} won''t start with Windows and dictation won''t work.'
      + #13#10#13#10 + 'Install there anyway?', mbConfirmation, MB_YESNO) <> IDYES) then
    Exit;
  if InOneDrive(Dir) and (MsgBox('That folder is synced by OneDrive. OneDrive can '
      + 'hold {#MyAppName}''s files while it syncs, which can stop updates from '
      + 'installing.' + #13#10#13#10 + 'Install there anyway?', mbConfirmation,
      MB_YESNO) <> IDYES) then
    Exit;
  Result := True;
  if not CanWriteTo(Dir) then
  begin
    MsgBox('Windows doesn''t let {#MyAppName} install in that folder without admin rights.'
      + #13#10#13#10 + 'Pick a folder in your user folder or on another drive.', mbError, MB_OK);
    Result := False;
  end;
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
  L, W, Y: Integer;
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

  L := WizardForm.WelcomeLabel2.Left;
  W := WizardForm.WelcomeLabel2.Width;
  Y := WizardForm.WelcomeLabel2.Top + WizardForm.WelcomeLabel2.Height + ScaleY(22);

  if not PreviouslyInstalled then
  begin
    LocationHeading := TNewStaticText.Create(WizardForm);
    LocationHeading.Parent := Page;
    LocationHeading.Caption := 'Install location';
    LocationHeading.Font.Style := [fsBold];
    LocationHeading.Left := L;
    LocationHeading.Top := Y;
    Y := Y + LocationHeading.Height + ScaleY(8);

    with WizardForm.DirBrowseButton do
    begin
      Parent := Page;
      Caption := 'Browse' + #$2026;
      Left := L + W - Width;
    end;
    with WizardForm.DirEdit do
    begin
      Parent := Page;
      Left := L;
      Top := Y;
      Width := W - WizardForm.DirBrowseButton.Width - ScaleX(8);
    end;
    WizardForm.DirBrowseButton.Top := Y
      + (WizardForm.DirEdit.Height - WizardForm.DirBrowseButton.Height) div 2;
    Y := Y + WizardForm.DirEdit.Height + ScaleY(8);

    with WizardForm.DiskSpaceLabel do
    begin
      Parent := Page;
      Left := L;
      Top := Y;
      Width := W;
    end;
    Y := Y + WizardForm.DiskSpaceLabel.Height + ScaleY(22);
  end;

  AutostartBox := TNewCheckBox.Create(WizardForm);
  AutostartBox.Parent := Page;
  AutostartBox.Caption := 'Start {#MyAppName} when Windows starts';
  AutostartBox.Checked := True;
  AutostartBox.Left := L;
  AutostartBox.Top := Y;
  AutostartBox.Width := W;
  AutostartBox.Height := ScaleY(22);
  { It only seeds a fresh install's settings; on a reinstall the app's own
    setting (Settings > General > Startup) is kept, so the box would do
    nothing (neutral QA, 2026-11-23). }
  if FileExists(ExpandConstant('{localappdata}\Talkative\settings.json')) then
    AutostartBox.Visible := False;

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

{ A folder outside the user's own profile (C:\Apps, D:\Tools...) usually
  inherits "Users: Modify" or even "Everyone: Full control" (this dev
  PC's D:\ root, 2026-11-23): any account on the PC could swap
  Talkative.exe, which starts at this user's login and sees their
  keyboard and clipboard. Lock it to this user, SYSTEM and Administrators
  (everyone else may still read and run it). The default folder, inside
  the profile, is private already and is left alone. Runs on every
  install, so an update also fixes a folder installed before this. }
{ "*S-1-5-21-..." for icacls: works for local, Microsoft and work
  (Entra) accounts alike, where DOMAIN\name may not resolve. '' if
  whoami fails. }
function CurrentUserSid: String;
var
  ResultCode, P: Integer;
  OutFile: String;
  Output: AnsiString;
begin
  Result := '';
  OutFile := ExpandConstant('{tmp}\whoami.txt');
  if Exec(ExpandConstant('{cmd}'), '/C whoami /user /fo csv /nh > "' + OutFile + '"',
          '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
     and (ResultCode = 0) and LoadStringFromFile(OutFile, Output) then
  begin
    Result := Trim(String(Output));
    P := Pos('"S-1-', Result);
    if P = 0 then
    begin
      Result := '';
      Exit;
    end;
    Result := Copy(Result, P + 1, Length(Result));
    P := Pos('"', Result);
    if P > 0 then
      Result := Copy(Result, 1, P - 1);
    Result := '*' + Result;
  end;
end;

procedure LockInstallFolder;
var
  App, User: String;
  ResultCode: Integer;
begin
  App := ExpandConstant('{app}');
  if UnderFolder(App, GetEnv('USERPROFILE')) then
    Exit;
  User := CurrentUserSid;
  if User = '' then
    User := GetEnv('USERDOMAIN') + '\' + GetEnv('USERNAME');
  { Grant this user first, so removing the inherited entries can never
    lock them out of their own install. On the folder ONLY, no /T: the
    files keep inheriting and pick up the new folder entries by
    themselves. With /T, icacls tried the (OI)(CI) grants on each file,
    which files can't take, then stripped the files' inherited entries,
    leaving Talkative.exe with no permissions at all -- "Access is denied"
    even for the user (found in testing, 2026-11-23). }
  if Exec(ExpandConstant('{sys}\icacls.exe'),
          '"' + App + '" /grant:r ' + AddQuotes(User + ':(OI)(CI)F') + ' /C /Q',
          '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
  begin
    Exec(ExpandConstant('{sys}\icacls.exe'),
      '"' + App + '" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F '
      + '*S-1-5-32-545:(OI)(CI)RX /C /Q', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Log(Format('install folder locked to %s (icacls %d)', [User, ResultCode]));
  end
  else
  begin
    Log(Format('install folder not locked: granting %s failed (%d)', [User, ResultCode]));
    SuppressibleMsgBox('{#MyAppName} is installed, but Windows didn''t let Setup make '
      + App + ' private to your account, so other accounts on this PC may be able to '
      + 'change its files.' + #13#10#13#10 + 'A folder inside your user folder is '
      + 'private already.', mbInformation, MB_OK, IDOK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  SettingsFile: string;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
    LockInstallFolder;
  { Open the app when an interactive install is done (no finished page).
    Silent installs (winget, the app's own /UPDATE) don't; update mode
    relaunches from DeinitializeSetup. }
  if (CurStep = ssDone) and not WizardSilent then
  begin
    { As the signed-in user: if Setup itself runs elevated, an elevated
      Talkative would be the copy the single-instance guard keeps. }
    ShellExecAsOriginalUser('open', ExpandConstant('{app}\{#MyAppExeName}'), '', '',
      SW_SHOWNORMAL, ewNoWait, ResultCode);
    Launched := True;
  end;
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
    { Belt-and-suspenders backstop on top of CloseApplications=force above --
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
    begin
      DelTree(ExpandConstant('{localappdata}\Talkative'), True, True, True);
      { Installed outside the profile, the models live in the install
        folder (model_manager.choose_models_dir, 2026-11-23). Inno already
        tried to remove the folder and left it because of them. }
      if FileExists(ExpandConstant('{app}\models\.talkative-models')) then
        DelTree(ExpandConstant('{app}\models'), True, True, True);
      RemoveDir(ExpandConstant('{app}'));
    end;
  end;
end;
