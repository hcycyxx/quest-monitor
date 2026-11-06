# SideQuest UI V10 · 已确认界面接入

Jack 已确认的界面基准为本聊天的 `sidequest-layout-v10.html`。完整参考保存于
`ui/web_v10/approved_v10_reference.html`，SHA256 记录于 `approved-source.json`。

## 本次范围

- 新增独立入口 `sidequest_v10.py`，不覆盖原 `sidequest.py`、`ui/quest_window.py` 或引擎文件。
- 采用 pywebview 6.2.1 + 本机 WebView2，保持已确认的文字层级、皮肤、间距和进度表现。
- 每个任务有进度条；估算区间保持区间，未知显示待估算；等待状态不伪造进展。
- 主线标题可收起/展开其他任务；任务步骤用测量高度的临界阻尼过渡，反向点击接续当前位置。
- 顶栏拖动移动、右下角调宽高、固定顶栏及滚动正文、细滚动条、滚轮平滑过渡。
- 左右贴边、750ms 延迟隐藏、鼠标靠边恢复、触屏把手、关闭自动隐藏。
- 窗口置顶、收成窄条、隐藏到托盘、退出；退出按 V9 既有行为停止后台。
- 完成历史、恢复任务、下一步建议、当前活动、暂停/继续、详细设置和日报入口保留。
- 新界面设置单独存 `config/ui_v10.json`；原 `ui.json` 和已生成预览均保留。

## 真实数据接入

`ui/v10_bridge.py` 使用现有 `state_store` 文件锁、原子写入和 `_user_state` 人工状态格式。
任务操作在锁内核对分组、ID、标题、步骤位置与文字；提交显式目标状态并去重请求。
只有保存成功才刷新完成反馈。失败保留界面原状态并提示，撤销会核对后续变化，避免覆盖新数据。
手动勾完全部步骤仍按原 V9 的人工完成规则处理，未变更任务识别或 AI 完成判定。

界面只接收所需任务字段，API 密钥不传给页面。标题、说明、步骤均按文字插入。
图标在本地附带固定版本 Lucide 和许可证，页面不加载远程脚本或样式。

## 运行环境

桌面依赖安装于 `%LOCALAPPDATA%\SideQuestV10Runtime`；锁定清单为 `requirements-ui-v10-lock.txt`。
本机将项目路径中的 .NET 组件判为 Internet 区域，放入标准本地运行目录后已通过加载检查；
未修改系统安全设置。项目 `.venv` 保留安装与离线检查证据，不用它启动正式桌面窗口。
pywebview 使用 6.2.1；Windows .NET 适配固定为已验证的 pythonnet 3.0.5 / clr_loader 0.2.7.post0。
后台继续用原 Python 安装，保留原 OCR 依赖。启动新版面板不自动重启、恢复或重复启动后台。
日常暂停/继续仍调用既有控制模块；继续前先核对已存在的后台进程。

本机已存在 Microsoft Edge WebView2 Runtime。这里使用其嵌入式渲染组件，不打开 Edge 浏览器。
Windows 上 pywebview 不提供原生背景透明功能；四套皮肤保留，当前窗口以不透明背景呈现。
未把 Tk 的透明文字叠层移植为虚假的 WebView 透明效果。

如需在其他电脑重建（本机已经安装，不必重复）：

```powershell
$desktopRuntime = Join-Path $env:LOCALAPPDATA 'SideQuestV10Runtime'
python -m venv $desktopRuntime
& (Join-Path $desktopRuntime 'Scripts\python.exe') -I -m pip --isolated --disable-pip-version-check --no-cache-dir --keyring-provider disabled install --index-url https://pypi.org/simple --no-build-isolation -r requirements-ui-v10-lock.txt
```

## 切换与回退

旧面板未运行时：

```powershell
.\launch_sidequest_v10.ps1
```

Jack 确认替换当前旧面板后：

```powershell
.\launch_sidequest_v10.ps1 -ReplacePanel
```

替换参数仅匹配本项目 `ui/quest_window.py` 的 Python 进程，不停止现有采样与模型引擎。
新版使用稳定命名的进程互斥锁防止重复面板。启动失败显示原因并记录于 `engine/panel_v10_error.log`。
隐藏到托盘仅在托盘成功建立后开放，避免面板无法找回。

回退：退出 V10 后，用原入口 `python sidequest.py` 或原启动方式打开 V9。
退出 V10 会暂停后台，原默认入口尊重暂停标记；需要继续观察时手动点击继续。
原 `engine/ctl.py panel`、`sidequest.py` 和 DSH 旧技能入口仍指向 V9；要启动 V10，请使用新版入口。
本次未重打包旧 EXE、未改桌面快捷方式或开机启动。

## 已完成检查

- 10 项临时虚拟数据检查：估算范围、完成/撤销、防重复、过期身份和步骤拒绝、人工完成、读取失败保留、设置隔离、阻尼收敛/反向、窗口边界和缩放约束。
- 14 项离线渲染交互检查：本地临时 Chrome 隔离配置、虚拟桥接，无真实任务或模型调用。
- 离线渲染截图核对，字体层级、任务标题换行、进度条、展开箭头与细滚动条符合确认风格。
- 新 Python/JavaScript 语法、HTML 控件引用、Windows 桌面程序集导入及 WebView2 可用检查。

可重复运行：

```powershell
python tools/check_ui_v10.py
python tools/check_renderer_v10.py
```

离线检查在临时目录或忽略的 `.venv/v10-render-check-*` 内生成证据，不改真实任务、不启动正式窗口。
这些检查不等于 Windows 真实桌面验收：实际拖动缩放、贴边滑出、托盘、跨屏 DPI、窗口关闭及滚轮还需 Jack 启动新版后确认。
日报生成没有做额外模型调用测试，仍沿用原业务流程。

## 资料

- pywebview 官方 API：https://pywebview.flowrl.com/api/
- 版本依赖：https://pypi.org/project/pywebview/6.2.1/
- 离线图标来源及校验：`ui/web_v10/vendor/manifest_v10.json`

本版本为现有项目的增量源码接入包，不能当作独立 EXE 安装包。
