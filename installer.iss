; ColdMail Sender 설치 프로그램 (Inno Setup). build.bat 이 PyInstaller 결과 폴더를 /DDist= 로 넘겨 컴파일한다.
; 관리자 권한 없이 사용자 계정에만 설치한다. 데이터(%LOCALAPPDATA%\ColdMailSender\data)는 제거해도 남는다.

#define AppVersion "1.0.0"

[Setup]
AppId={{DD3D311C-5066-4239-BBE5-550BCFB90AAE}
AppName=ColdMail Sender
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\ColdMail Sender
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputBaseFilename=ColdMailSender_Setup_{#AppVersion}
SetupIconFile=static\app.ico
UninstallDisplayIcon={app}\ColdMailSender.exe
UninstallDisplayName=ColdMail Sender
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[InstallDelete]
; 이전 버전의 라이브러리 파일이 남아 섞이지 않게
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Dist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\ColdMail Sender"; Filename: "{app}\ColdMailSender.exe"
Name: "{autoprograms}\ColdMail Sender"; Filename: "{app}\ColdMailSender.exe"
Name: "{autoprograms}\ColdMail Sender Claude 연결"; Filename: "{app}\ColdMailSender.exe"; Parameters: "--register-mcp"

[Run]
Filename: "{app}\ColdMailSender.exe"; Parameters: "--register-mcp"; StatusMsg: "Claude 연동을 설정하는 중..."
Filename: "{app}\ColdMailSender.exe"; Description: "ColdMail Sender 실행"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\ColdMailSender.exe"; Parameters: "--unregister-mcp"; RunOnceId: "UnregisterMcp"
; 백그라운드 앱 서버가 파일을 잡고 있으면 지워지지 않는다
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ColdMailSender.exe"; Flags: runhidden; RunOnceId: "StopServer"
