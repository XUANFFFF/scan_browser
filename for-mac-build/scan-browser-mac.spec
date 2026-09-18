# -*- mode: python ; coding: utf-8 -*-
#
# 扫描文件浏览器 - macOS PyInstaller 打包配置
# 【内部版】IP 已硬编码在 launcher.py，零配置，双击即用
#
# 使用方式（在 macOS 上执行）：
#   python3 -m venv .buildenv && source .buildenv/bin/activate
#   pip install --upgrade pip && pip install -r requirements.txt pyinstaller
#   pyinstaller scan-browser-mac.spec
#
# 说明：务必用虚拟环境，不要直接 pip3 install
# （新版 macOS 系统 Python 受保护，直接安装常报权限错误）
#
# 生成文件：dist/扫描文件浏览器.app
#
# 打包后默认以「独立桌面窗口」（pywebview + 系统 WKWebView）打开，
# 不依赖浏览器；如需回退到浏览器模式，运行
#   dist/扫描文件浏览器.app/Contents/MacOS/扫描文件浏览器 --browser

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
        'werkzeug.serving',
        # pywebview：平台后端是靠 guilib 里的 import 动态选中的，
        # 显式声明才不会在打包后丢失
        'webview',
        'webview.guilib',
        'webview.http',
        'webview.util',
        'webview.platforms.cocoa',
        # cocoa 后端直接依赖的 PyObjC 框架
        'objc',
        'Foundation',
        'AppKit',
        'WebKit',
        'PyObjCTools',
        'bottle',
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
    upx=False,              # macOS 上不用 UPX（体积收益小，且可能触发签名问题）
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
    icon='icon.icns',       # 应用图标（由 图标.png 生成）
    bundle_identifier='com.scanbrowser.app',
    info_plist={
        'CFBundleName': app_name,
        'CFBundleDisplayName': app_name,
        'CFBundleVersion': '2.0',
        'CFBundleShortVersionString': '2.0',
        'CFBundleDevelopmentRegion': 'zh_CN',
        'NSHighResolutionCapable': True,
        'NSHumanReadableCopyright': 'Copyright © 2024',
    },
)
