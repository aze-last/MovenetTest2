; Inno Setup 6 Script for CellWatch AI
; Philippine BJMP Jail Cell Monitoring System
; Target Deployment: Windows 11 x64

#ifndef MyAppVersion
#define MyAppVersion "1.0.0"
#endif

#define MyAppName "CellWatch AI"
#define MyAppPublisher "CellWatch AI Team"
#define MyAppURL "https://github.com/CellWatchAI/CellWatch"
#define MyAppExeName "CellWatch.exe"

[Setup]
AppId={{E681A78B-5CD3-49F8-B05F-53C623C83A21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\CellWatch
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
OutputDir=..\artifacts\installer
OutputBaseFilename=CellWatch-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardImageFile=wizard_banner.bmp
WizardSmallImageFile=wizard_small.bmp
SetupIconFile=..\monitor_app\assets\app_icon.ico
DisableWelcomePage=no
ExtraDiskSpaceRequired=2147483648
CloseApplications=force

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Primary application payload from PyInstaller one-dir build
; Exclude runtime databases, logs, recordings, and python caches so clean installation is guaranteed
Source: "..\dist\CellWatch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.db,*.log,*.sqlite,*.pyc,__pycache__,recordings\*,runs\*,exports\*"

; Bundled Visual C++ 2015-2022 x64 Redistributable
Source: "redist\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsVCRedist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}" 

[Run]
; Install VC++ Redistributable if needed before launching app
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/quiet /norestart"; StatusMsg: "Installing Microsoft Visual C++ 2015-2022 Redistributable (x64)..."; Flags: waituntilterminated; Check: NeedsVCRedist

; Option to launch CellWatch AI upon setup completion
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_tcl_data"

[Code]
// --- Check if VC++ 2015-2022 x64 Redistributable is installed ---
function NeedsVCRedist(): Boolean;
var
  Installed: Cardinal;
begin
  Result := True;
  // Check standard Visual Studio 2015-2022 runtime key
  if RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64', 'Installed', Installed) then
  begin
    if Installed = 1 then
      Result := False;
  end;
  
  // Also check WOW6432Node if needed
  if Result and RegQueryDWordValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\X64', 'Installed', Installed) then
  begin
    if Installed = 1 then
      Result := False;
  end;
end;

// --- GPU and Driver Pre-check during Setup Wizard initialization ---
function CheckNvidiaGPU(): Boolean;
var
  WbemLocator, WbemServices, WbemObjectSet, WbemObject: Variant;
  EnumObj: Variant;
  GpuName, DriverVer: String;
  FoundNvidia, DriverOk: Boolean;
  CmdTail: String;
  P3, P4, Dot1, Dot2, Dot3: Integer;
  VerPart3, VerPart4: String;
begin
  Result := True;
  
  // Allow bypassing GPU check for headless VM testing or developer debugging
  CmdTail := Uppercase(GetCmdTail);
  if (Pos('/SKIPGPU', CmdTail) > 0) or (ExpandConstant('{param:skipgpu|0}') = '1') then
  begin
    Exit;
  end;

  FoundNvidia := False;
  DriverVer := '';
  try
    WbemLocator := CreateOleObject('WbemScripting.SWbemLocator');
    WbemServices := WbemLocator.ConnectServer('.', 'root\CIMV2');
    WbemObjectSet := WbemServices.ExecQuery('SELECT Name, DriverVersion FROM Win32_VideoController');
    EnumObj := WbemObjectSet._NewEnum;
    while EnumObj.MoveNext do
    begin
      WbemObject := EnumObj.Current;
      GpuName := Uppercase(String(WbemObject.Name));
      if Pos('NVIDIA', GpuName) > 0 then
      begin
        FoundNvidia := True;
        DriverVer := String(WbemObject.DriverVersion);
        Break;
      end;
    end;
  except
    // If WMI query fails completely, do not hard-block install
    FoundNvidia := True;
  end;

  if not FoundNvidia then
  begin
    MsgBox('CellWatch AI Setup - Hardware Requirement Blocked' + #13#10 + #13#10 +
           'CellWatch AI requires an NVIDIA GPU (RTX 2050 or higher) for real-time video surveillance and TensorRT inference.' + #13#10 + #13#10 +
           'No NVIDIA GPU was detected on this machine.' + #13#10 + #13#10 +
           'Please verify hardware specifications before installing.' + #13#10 +
           'Driver & Hardware Info: https://www.nvidia.com/Download/index.aspx' + #13#10 + #13#10 +
           'Setup will now terminate.',
           mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end;

  // Validate NVIDIA Driver Version >= 545.00 (R545)
  // Format in WMI: Part1.Part2.Part3.Part4 (e.g. 32.0.16.1692 or 31.0.15.4601 where 15.4601 is 546.01)
  DriverOk := True;
  if DriverVer <> '' then
  begin
    Dot1 := Pos('.', DriverVer);
    if Dot1 > 0 then
    begin
      VerPart3 := Copy(DriverVer, Dot1 + 1, Length(DriverVer));
      Dot2 := Pos('.', VerPart3);
      if Dot2 > 0 then
      begin
        VerPart3 := Copy(VerPart3, Dot2 + 1, Length(VerPart3));
        Dot3 := Pos('.', VerPart3);
        if Dot3 > 0 then
        begin
          VerPart4 := Copy(VerPart3, Dot3 + 1, Length(VerPart3));
          VerPart3 := Copy(VerPart3, 1, Dot3 - 1);
          P3 := StrToIntDef(VerPart3, 0);
          P4 := StrToIntDef(VerPart4, 0);
          
          // Part 3 represents major era (14 = 400 series, 15 = 500 series, 16 = 600 series)
          // For Part 3 = 15, Part 4 < 4500 represents driver < 545.00 (e.g. 15.3758 = 537.58)
          if (P3 < 15) or ((P3 = 15) and (P4 < 4500)) then
          begin
            DriverOk := False;
          end;
        end;
      end;
    end;
  end;

  if not DriverOk then
  begin
    MsgBox('CellWatch AI Setup - Driver Requirement Blocked' + #13#10 + #13#10 +
           'CellWatch AI requires NVIDIA Graphics Driver version 545.00 (R545) or higher.' + #13#10 +
           'Detected Driver Version: ' + DriverVer + #13#10 + #13#10 +
           'Please update your NVIDIA driver before installing:' + #13#10 +
           'https://www.nvidia.com/Download/index.aspx' + #13#10 + #13#10 +
           'Setup will now terminate.',
           mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := CheckNvidiaGPU();
end;
