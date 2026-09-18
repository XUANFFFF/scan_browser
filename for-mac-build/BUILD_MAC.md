# macOS 版打包指南

> 内部版，IP 已硬编码在 `launcher.py`，零配置双击即用。
> 打包后是一个**独立桌面窗口**（不依赖浏览器）。

macOS 包只能在 macOS 上打，但**不需要你有一台 Mac** —— 用 GitHub Actions
的 macOS runner 就够了。下面两条路，优先走第一条。

| 方式 | 需要 Mac 吗 | 适合 |
|---|---|---|
| **① GitHub Actions 云端构建（推荐）** | 不需要 | 日常出包、发给同事测试 |
| ② 本地 Mac 打包 | 需要 | 改代码时本地快速验证 |

---

# ① GitHub Actions 云端构建（推荐）

## 怎么点

1. 打开仓库 → **Actions** 标签页
2. 左侧选 **Build macOS**
3. 右侧点 **Run workflow**，选择架构
   - `arm64` —— Apple Silicon（M 系列），**默认**
   - `x64` —— Intel Mac
   - `both` —— 两个都构建（会跑两个 runner）
4. 点绿色的 **Run workflow**，等约 5～10 分钟

## 去哪里拿产物

构建完成后，进入这次 run 的页面，拉到最底部 **Artifacts** 区域，下载：

```
扫描文件浏览器-macOS-arm64      ← 默认，Apple Silicon
扫描文件浏览器-macOS-x64        ← 选了 x64/both 才有
```

Artifact 默认保留 **30 天**，过期就重新跑一次。

### ⚠️ 下载的是「外层 ZIP」，需要先解一层

GitHub Actions 的 Artifact **本身就是一个 ZIP**。所以从网页下载后你会得到一个
外层包，解开它才会看到真正要发给同事的东西：

```
下载 → 扫描文件浏览器-macOS-arm64.zip            ← ① 外层（Actions 自动打的）
        └── 解开后得到 ↓
            扫描文件浏览器-macOS-arm64.zip       ← ② 内层：真正的分发 ZIP ← 发这个
            扫描文件浏览器-macOS-arm64.zip.sha256
```

**①②两层名字一样、别搞混**：外层是 GitHub 打包的，内层才是我们构建出来的。
把 **②（内层）** 连同 `.sha256` 发给同事；同事直接解压 ② 就能用。

> 命令行下载的话，`gh run download <run-id> -n 扫描文件浏览器-macOS-arm64`
> 会直接把**内层**的两个文件（分发 ZIP + `.sha256`）铺到你指定的目录，
> 不用手动解外层。

## 内层分发 ZIP 里有什么

```
扫描文件浏览器-macOS-arm64/
├── 扫描文件浏览器.app      ← 双击即可运行
├── 启动.command            ← 备用启动脚本（.app 打不开时用）
└── 使用说明.txt            ← 给同事看的简短说明
```

校验完整性（在 mac 终端，进到文件所在目录）：

```bash
shasum -a 256 -c 扫描文件浏览器-macOS-arm64.zip.sha256
```

## 架构怎么选

| 你的 Mac | 选 |
|---|---|
| M1 / M2 / M3 / M4（2020 年后的基本都是） | `arm64` |
| Intel（2020 年前的 Mac） | `x64` |
| 不确定 | 菜单栏  →「关于本机」，看「芯片」一行 |

> 怎么看某台机器该用哪个：终端执行 `uname -m`，`arm64` → arm64，`x86_64` → x64。
>
> 目前**不做 Universal Binary**（双架构合并）。真遇到 Intel 用户再补 `x64` 就行，
> 避免为了合并架构引入 `lipo`、双份 Python runtime 这些额外复杂度。

## CI 都检查了什么

云端 runner **访问不到公司内网 SMB**（`192.168.1.115`），所以 CI 不会、也不该
假装完成了端到端功能测试。它只做「构建与分发是否完整」的检查，分两轮：

**第一轮 —— 验 PyInstaller 刚生成的 `.app`**

- `扫描文件浏览器.app` 生成了
- `Contents/MacOS/扫描文件浏览器` 存在且有可执行位
- `Contents/Info.plist` 存在，且 `CFBundleName` / `CFBundleDisplayName` /
  `CFBundleIdentifier` 与 spec 一致
- 图标 `.icns` 进了 bundle
- onefile 归档里确实打进了 `templates/index.html`
- 用 `lipo -archs` 打印**真实产物架构**，并和选择的架构比对（不一致直接失败）
- **启动探针**：真的启动一次程序，请求 `GET /` 与 `GET /api/config`，
  确认页面能返回、模板能渲染 —— 缺模块会在这里立刻暴露
- 打印 ZIP 大小与 SHA256

**第二轮 —— 验「我们自己打的分发 ZIP」（闭环）**

第一轮验的是「我们以为要发的东西」，而用户实际下载的是打好的 ZIP，中间还隔着
一次打包。所以打包之后会把 ZIP **解开**，在解出来的东西上再验一遍：

- 解开后中文路径 `.../扫描文件浏览器.app` 存在（顺带验证 ZIP 里非 ASCII
  文件名都带了 UTF-8 标志位 —— 这正是早期 `ditto` 压包导致中文名乱码的那个坑）
- 主程序与 `启动.command` 在 ZIP 里**记录了**可执行位，解压后仍然可执行
- `codesign --verify --deep --strict` 校验解压后 `.app` 的**签名**
  （PyInstaller 默认做 ad-hoc 签名，bundle 里有
  `Contents/_CodeSignature/CodeResources`；签名嵌在 Mach-O 里，解压不影响）
- 把解压出来的 `.app` 再交给第一轮的校验脚本跑一遍：结构 / Info.plist / 图标 /
  内嵌资源 / 架构 / 启动探针

**只有两轮都全绿，才会上传 Artifact。**

> 探针只访问 `/` 和 `/api/config`（都只读内存配置）。
> `/api/health`、`/api/files` 会真的去连 SMB，**CI 里一律不调**。
>
> 这些检查都在 macOS runner 上真实执行，日志能在 run 页面直接看；
> ZIP 的逐条清单（权限位 / 大小 / 路径）也会打进日志，不必先下载就能核对。

## 首次打开的提示

包是**内部测试版**：不做 Developer ID 签名，也不做公证。所以同事第一次打开
大概率会看到「无法验证开发者」，处理方式：

```
右键点「扫描文件浏览器.app」
  → 选「打开」
  → 再点一次「打开」
```

之后双击就能正常用。

## 重新打包

配置（IP、共享名、图标）都在仓库里。要改就改源码，push 之后**重新点一次
Run workflow** —— Artifact 不会自动更新。

---

# ② 本地 Mac 打包（备用）

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

## 打包命令

```bash
# 确保在项目目录下
cd /路径/到/for-mac-build/

# 执行打包
pyinstaller scan-browser-mac.spec
```

打包完成后，`dist/` 目录下会生成 **`扫描文件浏览器.app`**。

> ⚠️ 产物是**当前机器架构**的（`target_arch=None`）。在 M 系列 Mac 上打出来的
> 是 arm64，Intel Mac 上是 x86_64，不会自动出双架构。想要另一个架构，
> 用上面的方式 ① 选 `both`。

## 手动分发给同事

打包好的 `dist/扫描文件浏览器.app` 本身不建议直接发（.app 是「文件夹」，
跨机器传输容易丢权限）。**按和云端完全一样的布局**打成一个分发 ZIP 再发：

```bash
# 仍在 for-mac-build/ 目录下

# 1) 建暂存目录（目录名 = ZIP 里的顶级目录名）
STAGE="/tmp/扫描文件浏览器-macOS-arm64"
rm -rf "$STAGE" && mkdir -p "$STAGE"

# 2) 用 ditto 复制 .app —— 它能保住元数据与签名封条
ditto dist/扫描文件浏览器.app "$STAGE/扫描文件浏览器.app"

# 3) 带上备用启动脚本
chmod +x 启动.command
cp -p 启动.command "$STAGE/启动.command"

# 4) 打 ZIP —— 必须用仓库里的 make_macos_zip.py，不要用 ditto -c -k / zip -r
python3 ../.github/scripts/make_macos_zip.py "$STAGE" 扫描文件浏览器-macOS-arm64.zip
```

> ⚠️ **为什么不能直接 `ditto -c -k` / `zip -r` 压包**：ZIP 规范要求非 ASCII
> 文件名设置「UTF-8 标志位」，而 `ditto` 写进去的是 UTF-8 字节却**不设这个标志**。
> 结果：Finder 会猜成 UTF-8 看着正常，但终端 `unzip` 按规范默认 cp437 解码 →
> 中文名全乱（`启动.command` 变乱码，同事拿到直接懵）。
> `make_macos_zip.py` 会显式设标志位 + 保留可执行位，谁解压都对。
> **云端与本地共用这一个脚本**，避免两套逻辑跑偏。
>
> `ditto` 在这里只负责**复制 .app**（不是压 ZIP），它保住元数据与签名封条，
> 这一步仍然需要。

得到的 `扫描文件浏览器-macOS-arm64.zip` 就是最终分发包，连同
`shasum -a 256` 的结果一起发给同事即可。

---

# 公共部分

## 修改 IP

如果你们的 SMB 服务器 IP 不是 `192.168.1.115`，改 `launcher.py` 顶部的常量：

```python
INTERNAL_SMB_HOST = "192.168.1.115"      # 改这里
INTERNAL_SMB_SHARE = "扫描共享文件"        # 共享名（一般不用改）
```

改完再重新构建（走 ① 的话记得 push 后再点一次 Run workflow）。

## 修改图标

图标文件是 `icon.icns`，已经由源图 `图标.png` 生成好，spec 里通过 `icon='icon.icns'` 引用，
**不用做任何事**即可生效。

换图标有两种做法：

**A. 在 Windows / 任意平台**（用 Pillow 直接生成，最省事）：

```bash
pip install pillow
python make_icons.py        # 会同时更新 icon.ico 与 for-mac-build/icon.icns
```

**B. 在 Mac 上**用系统自带工具：

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
- **CI 构建失败**：先看 run 页面里「校验产物」与「分发 ZIP 闭环验证」这两步的
  输出，脚本会把每一条校验结果打出来（`✅` / `❌`），失败项集中列在末尾；
  签名相关的问题会直接打印 `codesign` 的原始输出，便于定位。
- **本地想复现 ZIP 闭环校验**（在 Mac 上、有 .app 时）：
  ```bash
  python3 ../.github/scripts/verify_macos_zip.py \
    --zip 扫描文件浏览器-macOS-arm64.zip \
    --dest /tmp/roundtrip --expect-arch arm64
  ```
  它会解开 ZIP、验证中文路径与权限位、跑 `codesign`，再调
  `verify_macos_bundle.py` 完整验一遍（含启动探针）。
- **双击 .command 报 `bad interpreter` 或提示权限不足**：
  ```bash
  chmod +x 启动.command
  ```
  仓库里已把该文件标记为可执行（`100755`），正常 clone 不会遇到。
- **打开后提示「已损坏，无法打开」**：说明文件在传输中被破坏了。
  终端执行 `xattr -dr com.apple.quarantine 扫描文件浏览器.app` 后再打开。

## 后续（暂未做）

以下几项都不在本阶段的范围内，等真要对外分发时再单独开 Issue：

- Developer ID Application 签名
- Apple notarization 与 staple
- `v*` tag 自动构建并作为 Release asset 上传
- 证书与凭据一律走 GitHub Secrets，**不进仓库、不写进 workflow**

### 想加「tag 自动发 Release」时

在 `.github/workflows/build-macos.yml` 的 `on:` 下补上：

```yaml
on:
  workflow_dispatch:
  push:
    tags:
      - "v*"
```

再给 build 步骤加一个 `softprops/action-gh-release` 之类的上传步骤即可。
注意 `workflow_dispatch` 的 `inputs` 在 tag 触发时是空的，需要给
`inputs.arch` / `inputs.python_version` 各自补一个 `|| 'arm64'` / `|| '3.12'` 兜底。
