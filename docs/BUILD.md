# 依赖、构建与验证

源码整理基线：桌面 0.5.2，加独立网页伴侣；整理日期 2026-11-15。主源码与两份实验补丁分别保存，没有自动合并实验传输配置。

## Python 环境

Windows x64、Python 3.12（含 Tk）；仓库根目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\run_tests.py
```

`desktop/requirements-build.txt` 是原本机打包环境的版本清单；安装包构建还需安装该文件中的依赖与 NSIS。离线测试无需 USB/CAN 硬件；硬件运行依赖下述资源，不能直接把源码 ZIP 当安装程序使用。

## 外部资源

| 资源 | 放置位置 / 配置 |
| --- | --- |
| AR6004 hw3.0 `fw.ram.bin` 和 `bdata.bin` | `native_windows/firmware/`，哈希见该目录 MANIFEST.md |
| PEAK PCAN-Basic x64 DLL | `windows/pcan-basic-x64/x64/PCANBasic.dll` |
| PCAN 驱动 | 从 PEAK 官方获取匹配驱动并安装 |
| WinUSB | 用 Zadig 为实际的 `0cf3:1022` 设备绑定；勿选择 CAN 或其他 USB 设备 |
| OpenVPN TAP-Windows6 | 专用 TAP 网卡，使用项目配置脚本设置雷达地址与路由 |

固件需自行从有权使用的来源取得，加载器会校验哈希。厂家 SDK 和驱动下载入口：[PEAK](https://www.peak-system.com/)、[Zadig](https://zadig.akeo.ie/)、[TAP-Windows6](https://github.com/OpenVPN/tap-windows6)。

桌面安装器还使用 `desktop/assets/drivers/{pcan,tap,winusb}` 下的离线资源。准确文件名见 `desktop/device_setup.ps1`；发布者需自行准备匹配版本并确认分发条款。此包没有签名证书、厂商二进制和固件，也没有声称打包环境已经在另一台电脑复现。

配置脚本可能需要管理员权限，会安装驱动、创建专用 TAP、配置地址/路由与防火墙规则；先阅读脚本参数，不要将 `Install` 用于普通单元测试。

## 构建桌面安装器

在上述资源齐备后：

```powershell
.\.venv\Scripts\python.exe -m pip install -r desktop\requirements-build.txt
.\desktop\build.ps1 -Nsis 'C:\tools\nsis\makensis.exe'
.\dist\T40Radar\T40Radar.exe --self-test "$env:TEMP\t40-selftest.json"
```

PyInstaller 生成目录版，NSIS 生成安装包及 SHA-256。`--self-test` 检查固件、动态库和绘图，不连接真实 USB/CAN。此整理包只执行离线源码测试，未重新生成安装包。

## 实验与诊断

`experiments/comparison-2129.patch` 与 `experiments/queue-audit.patch` 均以本包主源码为起点，分别应用，不能连续叠加。使用独立副本：`git apply --check experiments/queue-audit.patch`，再执行 `git apply`。

指标版运行后，`tools/capture_metrics.py` 采集约 180 秒；`tools/read_only_load.py` 仅在新鲜遥测显示停转时读取雷达 `/dev/zero`。工具会产生本机日志，提交前需自行脱敏。

旧 Linux 与 VM 脚本仅作参考，网卡名、允许接入的 MAC、子网与用户目录须按本机修改；它们不是 Windows 桌面入口。
