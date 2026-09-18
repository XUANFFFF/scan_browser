# -*- mode: python ; coding: utf-8 -*-
#
# 扫描文件浏览器 - macOS PyInstaller 打包配置
# 【内部版】IP 已硬编码，零配置，双击即用
#
# 使用方式（在 macOS 上执行）：
#   python3 -m venv .buildenv && source .buildenv/bin/activate
#   pip install --upgrade pip && pip install pyinstaller flask pysmb
#   pyinstaller scan-browser-mac.spec
#
# 说明：务必用虚拟环境，不要直接 pip3 install
# （新版 macOS 系统 Python 受保护，直接安装常报权限错误）
#
# 生成文件：dist/扫描文件浏览器.app

block_cipher = None
entry_point = 'app_internal.py'
app_name = '扫描文件浏览器'

a = Analysis(
    [entry_point],
    pathex=[],
    binaries=[],
    datas=[('templates', 'templates')],
    hiddenimports=[
        'smb',
        'smb.SMBConnection',
        'flask',
        'flask.json',
        'flask.templating',
        'flask.cli',
        'werkzeug',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的模块，减小包体积
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'PIL',
        'cv2',
        'scipy',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        'notebook',
        'jupyter',
        'jupyter_client',
        'unittest',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # macOS: True=显示终端, False=隐藏终端(GUI模式)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ── macOS .app 捆绑包配置 ──
app = BUNDLE(
    exe,
    name=f'{app_name}.app',
    icon=None,              # 如需要图标，将 .icns 文件放此目录后改为 icon='app_icon.icns'
    bundle_identifier='com.scanbrowser.app',
    info_plist={
        'CFBundleName': app_name,
        'CFBundleDisplayName': app_name,
        'CFBundleVersion': '1.1',
        'CFBundleShortVersionString': '1.1',
        'CFBundleDevelopmentRegion': 'zh_CN',
        'NSHighResolutionCapable': True,
        'NSHumanReadableCopyright': 'Copyright © 2024',
    },
)
