; Установщик Inno Setup 6. Собирать после PyInstaller: ISCC installer.iss
; Версию можно передать снаружи: ISCC /DMyAppVersion=0.3.0 installer.iss (так делает release.yml).
; Файл сохранён в UTF-8 с BOM: без него Inno Setup не прочитает русские строки.
#ifndef MyAppVersion
  #define MyAppVersion "0.3.0"
#endif
#define MyAppName "FilePilot"
#define MyAppPublisher "dyrty11"
#define MyAppURL "https://github.com/dyrty11/filepilot"
#define MyAppExeName "FilePilot.exe"

[Setup]
; AppId совпадает с версией 0.1: новая версия устанавливается поверх старой
AppId={{B6D4E9F2-5C1A-4A8E-9C1F-1F2C3D4E5F60}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE
OutputDir=dist\installer
OutputBaseFilename=FilePilotSetup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
SetupIconFile=assets\icon.ico
; Внешний вид: современное окно с картинкой слева (три размера под разный масштаб экрана)
WizardStyle=modern
DisableWelcomePage=no
WizardImageFile=assets\wizard-100.bmp,assets\wizard-150.bmp,assets\wizard-200.bmp
WizardSmallImageFile=assets\wizard-small-100.bmp,assets\wizard-small-150.bmp,assets\wizard-small-200.bmp
; Язык: по языку системы, диалог выбора показывается, только если язык не определился
ShowLanguageDialog=auto
LanguageDetectionMethod=uilanguage
; Обновление: закрыть запущенную программу и поставить новую поверх
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
russian.DeleteDataQuestion=Удалить также индекс и настройки FilePilot?%n%nПапка: %1%n%nВаши файлы это не затронет. Если собираетесь поставить программу снова, нажмите «Нет».
english.DeleteDataQuestion=Also delete the FilePilot index and settings?%n%nFolder: %1%n%nYour own files are not affected. If you plan to reinstall, choose No.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Чистая замена при обновлении: старые библиотеки не должны смешиваться с новыми
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\FilePilot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Обычная установка: галочка «Запустить» на последней странице
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
; Обновление из программы (тихий режим с /RELAUNCH=1): сразу открыть новую версию
Filename: "{app}\{#MyAppExeName}"; Flags: nowait runasoriginaluser; Check: IsRelaunch

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function IsRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

{ Индекс и настройки лежат в %APPDATA%\FilePilot. Спрашиваем, удалять ли их, и по умолчанию оставляем. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\FilePilot');
    if DirExists(DataDir) and (not UninstallSilent) then
      if MsgBox(FmtMessage(CustomMessage('DeleteDataQuestion'), [DataDir]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
