; Установщик Quiet Launcher (Inno Setup 6). Собирается из build.bat.
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppName "Quiet Launcher"
#define AppExe "QuietLauncher.exe"

[Setup]
AppId={{B6F1D0C2-5A3E-4C7B-9E21-7D4A1F0C9A55}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
; Ставим в профиль пользователя: права администратора не нужны, лаунчер может писать рядом с собой
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
MinVersion=6.1sp1
OutputDir=..\dist
OutputBaseFilename=QuietLauncher-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=..\assets\icon.ico

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\QuietLauncher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; после обновления из самого лаунчера (он запускает установщик с /relaunch=1) открываем его снова
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: WantRelaunch

[UninstallDelete]
Type: dirifempty; Name: "{app}"

[Code]
function WantRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;

// Сборки, миры и скачанные файлы лежат в {app}\data. По умолчанию их оставляем.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if DirExists(ExpandConstant('{app}\data')) then
      if MsgBox('Удалить также сборки, миры и скачанные файлы игры?' + #13#10 +
                'Если вы планируете переустановить лаунчер, нажмите «Нет».',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(ExpandConstant('{app}\data'), True, True, True);
end;
