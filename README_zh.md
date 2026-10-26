# gtnh-save-inspector

[English](README.md)

只读查看 **GregTech: New Horizons**（Minecraft 1.7.10）存档和运行中客户端的工具。

> **兼容性说明：** 本工具基于 **GTNH 2.8.4** 开发和测试。GTNH 2.9.x 可能改动机器类名或 NBT 结构，
> 离线扫描和在线提取在 2.9.x 上只能尽力兼容，结果请自行核对。

主要用在：确认机器状态到底有没有写进存档、对比两个备份之间的变化、或者不打开存档直接看当前加载的机器。

**当前版本：v1.0**

离线解析不会修改存档；在线探针只读取已加载的区块和 TileEntity。

## 功能

- 直接解析 `level.dat`、维度目录和 Anvil region 文件，也支持 GTNH 的备份 zip。
- 按维度、机器类型、坐标、字段条件扫描机器，并支持排序。
- 把常见 GTNH 机器的原始 NBT 转成可读字段：
  - 鸿蒙之眼：进度、总运行时间、火箭等级、存储流体、停机/配方检查状态
  - 水线净化单元：进度和控制器坐标
  - 量子计算机 / 数据仓：算力与无线模式
  - 研究站：算力占用与机器类型
  - 通用 GT 多方块和单方块机器；所有带进度字段的多方块控制器都会自动提取，
  其余标量 NBT 字段会放进 `extra`
- 快照保存为 JSON / gzip，支持 diff、数值差值和忽略噪声字段。
- 扫描结果可导出 CSV。
- 有 Java 11+ 运行时时，可以 attach 到运行中的游戏，查看已加载的机器、区块和 TileEntity。
- 本地 GUI（浏览器或 pywebview 原生窗口）：世界浏览、机器详情、快照/diff、在线探针、chunk/TE 检查。
- GUI 支持中英文和黑白明暗主题。
- 后台扫描带进度和取消。

## 安装

```bash
git clone https://github.com/noitacude013/gtnh-save-inspector.git
cd gtnh-save-inspector
python -m pip install -e .
```

需要 Python 3.9+。CLI 和离线功能只用标准库。

Windows 原生窗口需要可选的 pywebview：

```bash
python -m pip install -e ".[gui]"
```

不装也可以使用浏览器模式。

## 打开 GUI

```bash
gtnh-inspect gui                 # 有 pywebview 时开原生窗口，否则用浏览器
gtnh-inspect gui --browser       # 强制浏览器
gtnh-inspect gui --port 8765     # 固定端口（默认随机空闲端口）
```

机器结果表里点击 `PROGRESS` 或 `TOTALRUN` 表头，可在升序、降序、不排序之间切换。
快照和 CSV 的保存路径可以在设置里单独指定，留空则使用默认 workspace。

GUI 默认只监听 `127.0.0.1`，每次启动生成随机 token，并自动记住上次的存档目录和世界。不会上传任何数据。

Windows 下也可以双击 `gtnh-inspector-launcher.pyw`，或运行 `launch-gui.cmd` 查看控制台日志。
启动器会显示 GUI 日志，并提供干净的停止按钮。

## Windows 单文件 exe

仓库不直接附带 exe，可以用项目 `.venv` 自行打包：

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build-exe.ps1
```

有两种构建：

- **标准版**：`dist\GTNH-Save-Inspector.exe`（约 13 MB）。在线探针需要系统已安装 Java 11+ JDK。
- **全依赖版**：`dist\GTNH-Save-Inspector-Full.exe`（约 29 MB）。内置 jlink OpenJDK 17 运行时，
  在线探针不依赖系统 Java。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build-exe-full.ps1
```

两个版本的原生窗口仍然使用 Windows 的 WebView2 运行时（Win11 自带；缺失时回退浏览器）。
详见 [packaging/README.md](packaging/README.md)。

## CLI 快速开始

```bash
# 列出一个 saves 目录下的世界
gtnh-inspect worlds --dir "/path/to/instance/saves"

# 扫描一个维度，只保留鸿蒙之眼，并输出快照
gtnh-inspect scan --world "/path/to/saves/Horizon" --dim 180 \
    --mte MTEEyeOfHarmony --out current.json

# 按方块坐标查看一台机器
gtnh-inspect show --world "/path/to/saves/Horizon" \
    --dim PERSONAL_DIM_180 --pos 104,49,104

# 对比备份快照和当前扫描
gtnh-inspect diff --a backup.json --b current.json --ignore mUpdate,mTotalRunTime

# 在线探针（需要 JDK 11+）
gtnh-inspect probe dump --pid 12345 --machine MTEEyeOfHarmony
gtnh-inspect probe watch --pid 12345 --machine MTEEyeOfHarmony --changes

# 保存当前在线状态，再和存档对比
gtnh-inspect probe dump --pid 12345 --world "/path/to/saves/Horizon" --save live.json
gtnh-inspect diff --a current.json --b live.json
```

`gtnh-inspect <命令> --help` 可以查看完整参数；脚本化可以使用 `--json` / `--jsonl`。

## 命令

| 命令 | 作用 |
| --- | --- |
| `worlds` | 列出 saves 目录下的世界和备份 zip |
| `show` | 按方块坐标查看一台机器 |
| `scan` | 扫描机器，支持过滤、排序、CSV 和快照 |
| `diff` | 对比两个快照 |
| `dump` | 输出单个 TileEntity 的原始（已清洗）NBT |
| `extractors` | 列出已注册的机器提取器 |
| `probe dump` | 从运行中的游戏取一次在线样本 |
| `probe watch` | 持续采样，支持 change/until 过滤 |
| `probe chunk` / `probe te` | 检查已加载区块或单个 TileEntity |
| `probe worlds` / `probe find` | 列出在线维度或查找运行中的 GTNH JVM |
| `probe stop` | 停止在线探针会话 |
| `gui` | 打开本地 Web GUI |
| `config` | 查看/设置默认 world、pid、java、saves |
| `capabilities` | 输出机器可读的命令和退出码信息 |

## 快照格式

快照包含一个头部和每台机器一条记录：

```json
{
  "format": 1,
  "tool": "gtnh-save-inspector",
  "tool_version": "1.0",
  "snapshot": { "captured": "...", "source": "...", "world": "Horizon" },
  "entries": [
    {
      "dim": "PERSONAL_DIM_180",
      "chunk": [6, 6],
      "pos": [104, 49, 104],
      "machine": "MTEEyeOfHarmony",
      "fields": { "progress": 29178, "max": 39850, "totalRun": 9256780 }
    }
  ]
}
```

## 测试

```bash
# 单元测试，不需要游戏或存档
python -m unittest discover -v

# 匿名测试夹具的离线检查
python scripts/ci_offline.py

# GUI / 前端检查
python scripts/gui_smoke.py
python scripts/check_gui_static.py
npm ci
node tests/frontend_smoke.mjs

# 真实存档 + 可选运行中游戏的完整 e2e
python scripts/e2e_check.py --world "/path/to/saves/Horizon" \
    --backup "/path/to/backups/latest.zip" --pid <游戏PID>
```

CI 会在 Python 3.9 和 3.12 上运行单元、离线、GUI 和前端检查。

## 限制

- 基于 GTNH 2.8.4 开发；不保证 GTNH 2.9.x 完全兼容。
- 只支持 1.7.10 Anvil 存档。
- 提取器字段取决于 GTNH 版本；不存在的字段显示为 `null`，不会让扫描失败。
- 大维度扫描比较吃 CPU/IO，可以用 `--dim`、`--mte`、`--limit`、`--top`、`--fast` 缩小范围。
- 在线探针需要 JDK 11+ 的 `java` 和运行中的游戏；标题界面会报告 `no-server`。
- 没有提供存档目录时，在线维度只显示 `DIM_180` 这类数字名称。

## 隐私

工具不会向任何外部服务发送数据。快照可能包含坐标、库存和玩家 UUID，分享前请自行检查。
详见 [docs/privacy.md](docs/privacy.md)。

## 参与开发

机器提取器都很小，见 [docs/extractors.md](docs/extractors.md)。
不想 fork 也可以写插件：[docs/plugins.md](docs/plugins.md)。

## 许可证

MIT，见 [LICENSE](LICENSE)。
