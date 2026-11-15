# GitHub 发布步骤

建议仓库名：`t40-radar-windows`。

建议描述：DJI T40 radar Windows control panel, USBWLAN transport and point-cloud visualization.

源码仓库不附带原安装包、固件与厂商驱动二进制。来源与许可范围见 THIRD_PARTY_NOTICES.md。

向自己的空 GitHub 仓库上传时，可在仓库根目录执行：

```powershell
git init -b main
git add .
git diff --cached --stat
git commit -m "Initial Windows radar source import"
git remote add origin https://github.com/YOUR_ACCOUNT/t40-radar-windows.git
git push -u origin main
```

二进制安装程序应在资源授权核对、构建与验证后单独放入 GitHub Releases，不放进源码历史。代码提交不附本机测试日志、硬件序列号和运行配置。

GitHub Actions 离线测试模板位于 `.github/tests.yml.example`。使用具备 workflow 权限的凭据，将其放入 `.github/workflows/tests.yml` 即可启用；其运行结果不替代实机验收。
