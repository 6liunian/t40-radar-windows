# 致谢与第三方来源

感谢 leommxj 的 [dji-agras-radar](https://github.com/leommxj/dji-agras-radar) 项目。本项目参考其协议分析、CAN 控制、雷达数据读取与 Linux 驱动实现，并修改、复用了部分源码，在此基础上增加 Windows 原生传输、桌面控制与网页可视化。

| 部分 | 来源与处理 |
| --- | --- |
| 原客户端、Linux 驱动和配置基础 | https://github.com/leommxj/dji-agras-radar ，2026-11-15 查询 main 为 `45f38c1b5d0649c9d0f9f5d35ac556be0f49e8b8`；这是来源参考版本，不代表本地所有文件与之逐字相同 |
| ath6kl 派生实现 | 保留各文件 Atheros/Qualcomm 等版权与许可头，逐文件适用 |
| 新增 Windows、桌面、网页代码与修改 | 待项目所有者确定适用许可证，并核对上游衍生部分兼容性 |
| Python 依赖 | 按各自许可证；`desktop/assets/licenses/` 保留已有许可文本，不等于附带全部软件 |
| AR6004 固件 | 本机验证文件取自原先可运行的 Ubuntu 环境；版本、大小和哈希见 `native_windows/firmware/MANIFEST.md`。未确认最初下载来源，不将固件归为本项目或 leommxj 原创；不随本源码包分发 |
| 厂商 DLL、驱动和证书 | 不随本源码包分发 |

原文件中的版权与许可声明保持不变。上游仓库级许可证目前未确认，本包未设置统一许可证；上述署名用于记录来源，不代表已取得额外授权。

本包未包含路由器管理密码、VM 登录凭据、原始抓包、运行时状态和个人浏览器配置。源码中的雷达默认 `root/root` 是既有设备协议实现的一部分，不是电脑账户；使用时按自己的设备访问配置管理。
