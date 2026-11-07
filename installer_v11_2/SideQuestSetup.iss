#define AppVersion "11.2.0"
[Setup]
AppId=SideQuest.Desktop.V11
AppName=SideQuest
AppVersion={#AppVersion}
AppPublisher=hcycyxx
AppPublisherURL=https://github.com/hcycyxx/sidequest
DefaultDirName={localappdata}\Programs\SideQuestDesktop
DefaultGroupName=SideQuest
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
WizardStyle=modern
WizardResizable=yes
OutputDir={#GetEnv('USERPROFILE')}\Desktop
OutputBaseFilename=SideQuest_V11_2_FullSetup_20261107
SetupIconFile=..\assets\sidequest.ico
UninstallDisplayIcon={app}\SideQuest.exe
Compression=lzma2/fast
SolidCompression=yes
LZMAUseSeparateProcess=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Files]
Source: "..\.installer_build_v11_2\dist\SideQuest\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\.portable_build_v11\prerequisites\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Flags: dontcopy
Source: "..\.portable_build_v11\prerequisites\NDP48-x86-x64-AllOS-ENU.exe"; Flags: dontcopy
Source: "使用说明.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\SideQuest V11.2"; Filename: "{app}\SideQuest.exe"; WorkingDir: "{app}"
Name: "{group}\SideQuest"; Filename: "{app}\SideQuest.exe"; WorkingDir: "{app}"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.txt"
Name: "{group}\卸载"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\SideQuest.exe"; Description: "启动 SideQuest"; Flags: nowait postinstall skipifsilent; Check: CanLaunch

[Code]
var
  ComponentRestart: Boolean;

function NeedFramework: Boolean;
var Release: Cardinal;
begin
  Result := not RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release);
  if not Result then Result := Release < 528040;
end;

function NeedWebView: Boolean;
var Version: String;
begin
  Result := not (RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
                 RegQueryStringValue(HKCU32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
                 RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
                 RegQueryStringValue(HKCU64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version));
  if not Result then Result := (Version = '') or (Version = '0.0.0.0');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer; Path: String;
begin
  Result := '';
  if NeedFramework then begin
    ExtractTemporaryFile('NDP48-x86-x64-AllOS-ENU.exe');
    Path := ExpandConstant('{tmp}\NDP48-x86-x64-AllOS-ENU.exe');
    if not ShellExec('runas', Path, '/passive /norestart', '', SW_SHOWNORMAL, ewWaitUntilTerminated, Code) then begin
      Result := '无法安装 .NET 4.8，请允许微软组件安装后重试。'; exit;
    end;
    if Code = 3010 then begin ComponentRestart := True; NeedsRestart := True; end
    else if (Code <> 0) and (Code <> 1638) then begin Result := '.NET 4.8 安装未完成，错误码：' + IntToStr(Code); exit; end;
  end;
  if NeedWebView then begin
    ExtractTemporaryFile('MicrosoftEdgeWebView2RuntimeInstallerX64.exe');
    Path := ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe');
    if not Exec(Path, '/silent /install', '', SW_SHOWNORMAL, ewWaitUntilTerminated, Code) then begin
      Result := '无法启动微软 WebView2 安装程序。'; exit;
    end;
    if (Code <> 0) and (Code <> 1638) then begin Result := 'WebView2 安装未完成，错误码：' + IntToStr(Code); exit; end;
    if NeedWebView then begin Result := 'WebView2 未就绪，请重启 Windows 后重新安装。'; exit; end;
  end;
end;

function NeedRestart: Boolean;
begin Result := ComponentRestart; end;

function CanLaunch: Boolean;
begin Result := not ComponentRestart; end;
