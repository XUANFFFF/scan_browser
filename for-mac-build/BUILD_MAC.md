# macOS 版打包指南

> 内部版，IP 已硬编码在 `app_internal.py`，零配置双击即用。

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
pip install pyinstaller flask pysmb
```

> 💡 如果 Mac 没有 `brew`，先从 https://www.python.org/downloads/ 下载安装 Python 3，再执行上面的第 2、3 步。
>
> ⚠️ **为什么不直接 `pip3 install`**：新版 macOS 的系统 Python 受 SIP 保护、Homebrew 的 Python
> 标记为 externally-managed，直接安装常报权限错误或 `externally-managed-environment`；
> 即使成功也会污染系统环境。用虚拟环境最省事。
>
> 虚拟环境 `.buildenv/` 只用于打包，**不要**放进交付给同事的文件夹。

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

如果你们的 SMB 服务器 IP 不是 `192.168.1.115`，打包前先修改 `app_internal.py` 中的 `SMB_HOST` 变量：

```python
SMB_HOST = '你的IP'   # 修改这里
```

改完再执行打包。

> 或者直接用下方的 AI prompt 让 agent 帮你完成这些操作。

---

## 分发给同事

将以下 **两个文件** 一起发送：

```
📁 扫描文件浏览器/
   ├── 扫描文件浏览器.app     ← 双击即可运行
   └── 启动.command           ← 备用启动脚本
```

同事收到后：
1. 将两个文件放在**同一个文件夹**
2. 双击 `扫描文件浏览器.app`
3. 第一次运行需右键 →「打开」（macOS 安全提示，仅首次）
4. 浏览器自动弹出文件列表 ✔

> ⚠️ **安全提示**：macOS 可能会提示"无法验证开发者"。
> 右键点击 `.app` → 选择「打开」→ 点击「打开」即可。以后双击就能正常打开。
