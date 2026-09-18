# macOS 版打包指南

> 内部版，IP 已硬编码在 `launcher.py`，零配置双击即用。
> 打包后是一个**独立桌面窗口**（不依赖浏览器）。

---

## 前置条件（只需做一次）

在 **Mac 电脑** 上执行：

```bash
# 1. 安装 Python 3（如已安装可跳过）
brew install python3

# 2. 建独立虚拟环境（强烈建议）
cd /路径/到/for-mac-build/
python3 -m venv .buildenv
source .buildenv/bin/activate

# 3. 安装打包工具和项目依赖
pip install --upgrade pip
pip install -r requirements.txt pyinstaller
```

> 💡 如果 Mac 没有 `brew`，先从 https://www.python.org/downloads/ 下载安装 Python 3，再执行上面的第 2、3 步。
>
> ⚠️ **为什么不直接 `pip3 install`**：新版 macOS 的系统 Python 受 SIP 保护、Homebrew 的 Python
> 标记为 externally-managed，直接安装常报权限错误或 `externally-managed-environment`；
> 即使成功也会污染系统环境。用虚拟环境最省事。
>
> 虚拟环境 `.buildenv/` 只用于打包，**不要**放进交付给同事的文件夹。

> ℹ️ `pywebview` 在 macOS 上会自动带上 `pyobjc-*` 系列依赖（系统 WebKit 的 Python 绑定），
> 由 `requirements.txt` 里的 `pywebview>=6.0` 自动拉取，不用单独装。

---

## 打包命令

```bash
# 确保在项目目录下
cd /路径/到/for-mac-build/

# 执行打包
pyinstaller scan-browser-mac.spec
```

打包完成后，`dist/` 目录下会生成 **`扫描文件浏览器.app`**。

---

## 修改 IP

如果你们的 SMB 服务器 IP 不是 `192.168.1.115`，打包前先修改 `launcher.py` 顶部的常量：

```python
INTERNAL_SMB_HOST = "192.168.1.115"      # 改这里
INTERNAL_SMB_SHARE = "扫描共享文件"        # 共享名（一般不用改）
```

改完再执行打包。

> 或者直接用下方的 AI prompt 让 agent 帮你完成这些操作。

---

## 修改图标

图标文件是 `icon.icns`，已经由源图 `图标.png` 生成好，spec 里通过 `icon='icon.icns'` 引用，
**不用做任何事**即可生效。

如果之后想换图标，在 Mac 上用系统自带工具重新生成即可：

```bash
# 1. 准备一个 1024x1024 的 PNG，命名为 icon-source.png
# 2. 建 iconset 目录并生成各尺寸
mkdir icon.iconset
for s in 16 32 64 128 256 512; do
  sips -z $s $s icon-source.png --out icon.iconset/icon_${s}x${s}.png
  sips -z $((s*2)) $((s*2)) icon-source.png --out icon.iconset/icon_${s}x${s}@2x.png
done
# 3. 打包成 .icns
iconutil -c icns icon.iconset -o icon.icns
```

---

## 分发给同事

将以下 **两个文件** 一起发送：

```
📁 扫描文件浏览器/
   ├── 扫描文件浏览器.app     ← 双击即可运行，打开独立窗口
   └── 启动.command           ← 备用启动脚本（.app 打不开时用）
```

同事收到后：
1. 将两个文件放在**同一个文件夹**
2. 双击 `扫描文件浏览器.app`
3. 第一次运行需右键 →「打开」（macOS 安全提示，仅首次）
4. 直接弹出「扫描文件浏览器」独立窗口 ✔

> ⚠️ **安全提示**：macOS 可能会提示"无法验证开发者"。
> 右键点击 `.app` → 选择「打开」→ 点击「打开」即可。以后双击就能正常打开。

---

## 排障

- 窗口起不来时，用命令行走一次可以看到日志：
  ```bash
  dist/扫描文件浏览器.app/Contents/MacOS/扫描文件浏览器
  ```
- 运行日志写在 `.app` 同级的 `扫描文件浏览器.log`（写不进去时落到用户目录）。
- 想临时回退到浏览器模式（不开窗口）：
  ```bash
  dist/扫描文件浏览器.app/Contents/MacOS/扫描文件浏览器 --browser
  ```
