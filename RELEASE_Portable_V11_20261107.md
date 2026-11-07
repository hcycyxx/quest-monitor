# SideQuest V11 便携版交付

Jack 选择：便携文件夹＋启动EXE；目标电脑自行安装与原电脑相同的本地AI接口。

## 桌面产物

- `C:/Users/Blank/Desktop/SideQuest便携版_V11_20261107/SideQuest.exe`
- `C:/Users/Blank/Desktop/SideQuest便携版_V11_20261107.zip`
- 文件夹约615.7MiB，ZIP约448.9MiB。

必须复制整个文件夹或将ZIP完整解压，不能只拿走EXE。
适用Windows 10/11 x64；包含Python、当前V11界面、CPU OCR及必要Python包。
附带微软WebView2和.NET Framework4.8离线安装程序，已静态检查为Microsoft Corporation有效签名。
目标机缺少时，由用户确认后安装；本次没有在本机执行这些安装程序。

## 便携适配

- `portable_v11/entry.py`：首次将EXE和_internal准备到本机LocalAppData缓存，避免下载目录中的.NET组件加载限制；不是修改全局安全设置。
- 数据始终写原便携文件夹的data，运行组件缓存与原源码版环境分开。
- `portable_adapter.py`：冻结EXE的后台角色、身份核验、子进程启动、设置窗口、后台状态路径及监测自身窗口的排除。
- `portable_app_v11.py`：使用内嵌界面资源并将日志放入便携数据目录。
- 构建脚本为 `portable_v11/build_portable.spec`，使用现有PyInstaller6.20.0。

## 接口与数据

只预填原本地接口地址和模型名，api_key为空。
首次在目标电脑启动本地接口后，通过更多→外观与设置→模型与采样设置填入那台电脑要求的密钥并保存。
本包不附带本地模型服务、云端账户或本地模型权重。
没有复制真实任务、窗口日志、时间轴、日报、客户资料或原电脑密钥。
程序使用后的data会产生私人使用数据，后续是否随包迁移由用户决定。

## 完整性与版本

EXE/ZIP路径、大小及SHA256记录于 `portable_v11/BUILD_RESULT_20261107.json`。
微软组件的下载来源及SHA256在交付包“运行组件/组件来源与校验.json”。
源码、构建脚本、脱敏默认配置和交付清单提交Git；大型EXE和便携ZIP放在桌面，不塞入Git仓库。
现有源码版未替换或重启，旧打包产物未覆盖。

## 验收边界

已完成实际PyInstaller构建和交付文件整理，不是仅给出打包脚本。
按Jack要求，没有运行生成的EXE，没有运行程序测试、跨机测试或模型请求验证。
构建成功不能替代目标Windows环境验收；本地接口及正确密钥是AI识别工作的前提。

微软官方组件说明：

- https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution
- https://support.microsoft.com/en-us/servicing/dotnetframework/2019/10/microsoft-net-framework-4-8-offline-installer-for-windows
