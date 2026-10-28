import os

# 1. Update CellWatch.spec
with open('CellWatch.spec', 'r', encoding='utf-8') as f:
    spec = f.read()

target_spec = """    entitlements_file=None,
)"""
repl_spec = """    entitlements_file=None,
    icon='monitor_app/assets/app_icon.ico',
)"""

if target_spec in spec and 'icon=' not in spec:
    spec = spec.replace(target_spec, repl_spec, 1)
    with open('CellWatch.spec', 'w', encoding='utf-8') as f:
        f.write(spec)
    print("Updated CellWatch.spec with app_icon.ico")
else:
    print("CellWatch.spec already has icon or target not found")

# 2. Update installer/CellWatch.iss
with open('installer/CellWatch.iss', 'r', encoding='utf-8') as f:
    iss = f.read()

target_iss = """WizardStyle=modern
DisableWelcomePage=no"""

repl_iss = """WizardStyle=modern
WizardImageFile=wizard_banner.bmp
WizardSmallImageFile=wizard_small.bmp
SetupIconFile=..\\monitor_app\\assets\\app_icon.ico
UninstallIconFile=..\\monitor_app\\assets\\app_icon.ico
DisableWelcomePage=no"""

if target_iss in iss and 'WizardImageFile=' not in iss:
    iss = iss.replace(target_iss, repl_iss, 1)

target_icons = """[Icons]
Name: "{group}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"
Name: "{group}\\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"; Tasks: desktopicon"""

repl_icons = """[Icons]
Name: "{group}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"; IconFilename: "{app}\\{#MyAppExeName}"
Name: "{group}\\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\\{#MyAppExeName}" """

if target_icons in iss:
    iss = iss.replace(target_icons, repl_icons, 1)

with open('installer/CellWatch.iss', 'w', encoding='utf-8') as f:
    f.write(iss)
print("Updated installer/CellWatch.iss with WizardImageFile, WizardSmallImageFile, SetupIconFile, and shortcut icons")

# 3. Update monitor_app/main.py with Window iconbitmap
with open('monitor_app/main.py', 'r', encoding='utf-8') as f:
    main_code = f.read()

target_main = """        self.title(self.app_profile["system_name"])
        self.geometry(utils.WINDOW_SIZE)"""

repl_main = """        self.title(self.app_profile["system_name"])
        self.geometry(utils.WINDOW_SIZE)
        
        # Load Window & Taskbar Icon
        try:
            ico_candidates = [
                os.path.join(os.path.dirname(__file__), "assets", "app_icon.ico"),
                os.path.join(os.path.abspath("."), "monitor_app", "assets", "app_icon.ico"),
                os.path.join(os.path.abspath("."), "assets", "app_icon.ico"),
            ]
            for ico in ico_candidates:
                if os.path.exists(ico):
                    self.iconbitmap(ico)
                    break
        except Exception as e:
            print(f"Could not load window icon: {e}")"""

if target_main in main_code and 'iconbitmap' not in main_code:
    main_code = main_code.replace(target_main, repl_main, 1)
    with open('monitor_app/main.py', 'w', encoding='utf-8') as f:
        f.write(main_code)
    print("Updated monitor_app/main.py with iconbitmap loading")

# 4. Update monitor_app/auth.py logo size
with open('monitor_app/auth.py', 'r', encoding='utf-8') as f:
    auth_code = f.read()

target_auth = """            return ctk.CTkImage(light_image=image, dark_image=image, size=(56, 56))"""
repl_auth = """            return ctk.CTkImage(light_image=image, dark_image=image, size=(68, 68))"""

if target_auth in auth_code:
    auth_code = auth_code.replace(target_auth, repl_auth, 1)
    with open('monitor_app/auth.py', 'w', encoding='utf-8') as f:
        f.write(auth_code)
    print("Updated monitor_app/auth.py logo display size to (68, 68)")

