; SideQuest 安装脚本（Inno Setup 6）
; 编译：ISCC.exe installer.iss
; 产物：dist\SideQuest-Setup-x.y.z.exe
;
; 装在用户目录，不需要管理员权限 —— 悬浮窗和托盘图标都在当前会话里，
; 装到 Program Files 反而会让配置写入撞权限。
; 打包用 onedir（dist\SideQuest\ 整个目录），安装器把它整个复制过去。

#define AppName "SideQuest"
#define AppVersion "1.1.0"
#define AppPublisher "hcycyxx"
#define AppUrl "https://github.com/hcycyxx/sidequest"
#define AppExe "SideQuest.exe"

[Setup]
AppId={{8F3A6C21-4B7E-4D2A-9E55-2C1A7F0D6B31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}
AppUpdatesURL={#AppUrl}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=SideQuest-Setup-{#AppVersion}
SetupIconFile=assets\sidequest.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start SideQuest when Windows starts"; GroupDescription: "Startup:"

[Files]
Source: "dist\SideQuest\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// 卸载时问一句要不要连配置和总结一起删。
// 默认不删：任务历史和每日总结是用户自己攒下来的东西，误删找不回来。
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\{#AppName}');
    if DirExists(DataDir) then
    begin
      if MsgBox('Also delete your tasks, settings and daily summaries?' + #13#10 +
                DataDir, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
