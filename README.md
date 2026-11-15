# T40 Radar for Windows

用于 DJI T40 雷达的 Windows 原生控制与点云可视化工具。通过 USB-CAN 控制旋转，通过 AR6004 USBWLAN 接收雷达数据，提供桌面控制台和本地网页点云视图，无需 Ubuntu 虚拟机参与运行。

## 功能

- CAN 电机启停、目标转速设置、实际转速显示。
- Windows 用户态 USBWLAN 固件加载、热点及 TAP 数据通道。
- 避障候选点与扇区回波数据源，点云累积、俯视/侧视/三维视角。
- 障碍轮廓显示与本地网页点云伴侣。
- Windows 桌面打包脚本、无硬件单元测试和传输诊断工具。

## 硬件与连接

| 部件 | 用途 |
| --- | --- |
| DJI T40 雷达及匹配电源 | 雷达本体；按设备要求选择电源和接线 |
| AR6004 / AR1021X USBWLAN，USB ID `0cf3:1022` | 与雷达无线通信 |
| PCAN-USB | CAN 控制；当前实现使用 PCAN API，不是任意 USB-CAN 通用接口 |
| Windows x64 电脑 | 运行控制台与 USB 用户态传输 |

```text
Windows ── USB-CAN ── 雷达电机控制
    └── USBWLAN ── radar_wifi ── 雷达数据
         └── WinUSB / TAP ── 桌面点云 / 网页点云
```

默认雷达网络为主机 `192.168.8.1`、雷达 `192.168.8.2`；CAN 为 1 Mbps。连接前核对自己的硬件、固件和网络配置。

**[引脚接线图与针脚表](docs/WIRING.md)**：包含雷达自定义 Type-C、PCAN-USB 和 USB 数据线连接关系。

## 从源码开始

需要 Python 3.12 x64。此源码包不附带硬件固件、驱动二进制和安装程序；先阅读 [依赖与构建](docs/BUILD.md) 准备外部资源。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# 完成驱动、固件及 TAP 配置后启动：
.\.venv\Scripts\python.exe desktop\app.py
```

在面板中选择目标转速，点击启动；调速时先停止，待实际转速为 0 后更改目标再启动。网页伴侣入口为 `web-radar/start-web-radar.cmd`，浏览器访问 `http://127.0.0.1:8768/`。网页不发送电机控制命令，但会读取雷达扇区数据；不要同时启用两个扇区读取端。

## 开发资料

| 目录 | 内容 |
| --- | --- |
| `desktop/` | 桌面入口、设备配置、PyInstaller 与 NSIS 打包 |
| `native_windows/` | WinUSB、固件引导、HTC/WMI、热点、TAP |
| `radar_client/` | CAN/DUML、UDP 客户端、点云与轮廓 |
| `web-radar/` | 本地网页视图及只读数据桥 |
| `windows/` | 启动、网络配置与面板测试 |
| `ar1021x_driver/`, `setup/` | Linux 参考实现与配置模板 |
| `experiments/`, `tools/` | 对照补丁、指标采集和只读负载工具 |
| `docs/` | 构建、数据说明、来源与发布步骤 |

运行测试：`.\.venv\Scripts\python.exe tools\run_tests.py`。测试只检查离线行为，不启动电机。

更多说明：[数据解释](docs/DATA.md) · [构建说明](docs/BUILD.md) · [来源和授权](THIRD_PARTY_NOTICES.md) · [发布步骤](docs/PUBLISH.md)。

## 致谢

参考了 [leommxj/dji-agras-radar](https://github.com/leommxj/dji-agras-radar) 的协议分析与实现，复用、修改了部分客户端和 Linux 驱动代码；Windows 原生传输、桌面控制台和网页界面在本项目中扩展实现。感谢原作者的工作。第三方声明见 [来源说明](THIRD_PARTY_NOTICES.md)；运行所需固件不随源码分发，见 [固件清单](native_windows/firmware/MANIFEST.md)。本项目非 DJI 官方软件。
