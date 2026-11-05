---
name: sidequest
description: 在 Windows 桌面上装一个常驻的游戏式任务面板：后台采样前台窗口，本地 OpenAI 兼容模型每 60 秒推断你正在做的任务，把主线/支线和下一步建议挂到屏幕右上角。用户说"装任务面板/任务追踪/我老是做着做着就乱了/想要游戏任务列表挂在屏幕边上"时使用。
whenToUse: 用户想在自己的 Windows 机器上运行或重装这个任务面板，或者要求排查面板不显示、不刷新、暂停没生效这类运行问题。
---

# SideQuest

这是一个可直接运行的 Windows 桌面程序，不是纯文档技能。装完之后 `ui/quest_window.py`
会把一个悬浮窗挂在屏幕右上角，`engine/` 下两个后台进程负责采样与推断。

## 装之前确认三件事

1. **Windows 10/11**，`python --version` 是 3.10 以上，安装时勾了 `tcl/tk and IDLE`。
   面板本身纯标准库；要让它看见窗口里**具体**在做什么，再装几个包：

   ```powershell
   pip install comtypes winsdk rapidocr onnxruntime pystray
   ```

   `comtypes` 读 UIA 控件树；`winsdk` 调 Windows 自带 OCR（兜底）；`rapidocr` 是准确率高
   得多的 OCR —— 系统 OCR 会把「绩效」认成「缋效」，RapidOCR 不会；`pystray` 给托盘图标
   （缺了只是没托盘，面板照常跑）。装不上也能跑，只是退回只看窗口标题。只装
   `comtypes winsdk` 也够用，表格内容会错几个字。
2. **一个 OpenAI 兼容的 `/v1/chat/completions` 地址**。可以是本机网关（Ollama、LM Studio、
   vLLM、one-api 之类跑在 `http://127.0.0.1:8899/v1`），也可以是云端。
   `install.ps1` 会去探 `/v1/models`，探不通只警告不中断。
3. **愿意让它记录前台窗口标题和窗口里显示的文字**。它写窗口标题、进程名、空闲秒数、
   以及窗口内文字到 `config/win_log.jsonl`。**不截全屏、不上传任何图片**，
   抓到的文字只在本地存，发给模型的只有最后 2~5 段、每段 160~260 字。
   办公文档是**直接读磁盘上的文件**（xlsx/docx 里存的就是原文），比认字准得多。
   不想抓内容就把 `config\llm.json` 的 `content_capture` 设成 `false`。

## 安装

把仓库放进 DSH 的 skills 目录，或者任意位置单独跑：

```powershell
# 方式一：作为 DSH 技能装（之后可直接说"启动任务面板"）
git clone https://github.com/hcycyxx/sidequest "$env:USERPROFILE\.agents\skills\sidequest"

# 方式二：随便放一个目录当普通程序用
git clone https://github.com/hcycyxx/sidequest D:\tools\sidequest
```

然后跑安装器，把模型地址传进去：

```powershell
cd "$env:USERPROFILE\.agents\skills\sidequest"
.\install.ps1 -BaseUrl http://127.0.0.1:8899/v1 -ApiKey sk-xxx -Model deepseek-v4.1-flash
```

不想传参数就先跑 `.\install.ps1 -NoStart`，再手动改 `config\llm.json`。

`install.ps1` 做四件事：查 Python 和 tkinter、生成 `config\llm.json`（已有就不动）、
从示例播种 `config\quest_state.json`、探一下模型接口然后拉起面板和后台服务。
**全程不需要管理员权限，也不写注册表。**

## 手动控制

```powershell
python engine\ctl.py            # 看状态
python engine\ctl.py pause      # 停掉采样与推断（真杀进程，不再花 token）
python engine\ctl.py resume     # 恢复
python engine\ctl.py panel      # 只开面板
.\restart_all.ps1               # 面板卡住时整条重启，会尊重暂停标记
```

`ctl.py` 只认命令行里同时出现脚本名和**本项目根目录**的进程。同一台机器上装两份不会互相误杀。

## 面板怎么用

- 顶栏整条都能拖（不只是标题文字）
- 顶栏六个按钮：换皮肤 / 暂停 / 总在最前 / 图钉 / 收起 / 关闭，鼠标停在上面有说明
- 任务左边圆点 = 标记完成或恢复；点标题 = 展开步骤。分开是为了避免点标题时误标完成
- 拖到屏幕边缘松手，鼠标移开 0.75 秒会缩成竖把手，图钉可固定成常驻展开
- 暂停时标题变金色、进度环变暗，显示的是冻结快照，直到点 ▶
- 进度条颜色 = 紧急程度：红 high / 琥珀 mid / 灰蓝 low / 青 waiting

## 托盘与每日总结

右下角托盘图标，右键六个入口：打开今日总结、历史总结（最近 12 天）、显示/隐藏面板、
立即生成总结、详细设置…、退出 SideQuest。

每天 18:00（详细设置里可改）自动生成 `summaries\YYYY-MM-DD.html`，手账风格：
今日完成、还在进行中、明天优先做、今日时间轴，加专注时长统计。
「明天优先做」要调一次模型，接口不通就按优先级兜底，总结照样出。

详细设置窗口能改：模型接口地址 / API Key / 模型名 / 分析间隔、内容抓取开关
（`content_capture` / `doc_read` / `content_level` / `ocr_engine`）、悬浮窗字体大小、
每日总结生成时间。改完立即生效，不用重启。

## 装成 exe（不想装 Python 的机器）

不想装 Python 就直接下安装包：
<https://github.com/hcycyxx/sidequest/releases/latest>（约 100 MB，含 OCR 模型）。

自己编译：

```powershell
python -m PyInstaller --noconfirm build.spec   # → dist\SideQuest\ 目录
ISCC.exe installer.iss                         # → dist\SideQuest-Setup-1.1.0.exe
```

产物是目录形式（`SideQuest.exe` + `_internal\`），不是单文件：整包 300 MB，
单文件模式每次启动都要解压到临时目录，冷启动十几秒，临时目录不可写时直接起不来。

安装包不需要管理员权限，装到 `%LOCALAPPDATA%\Programs\SideQuest`；
配置、任务、日志、总结都在 `%LOCALAPPDATA%\SideQuest\`（`SIDEQUEST_HOME` 可改）。
卸载时会问要不要连数据一起删，默认不删。**不要试图装成 Windows 服务**——
服务在 session 0，画不出悬浮窗、也弹不出托盘图标。

## 排障

**窗口不出现** — `python engine\ctl.py panel` 看有没有报错；tkinter 缺失时 Python
安装包需要重装并勾上 tcl/tk。

**显示"待估算"且一直不更新** — 后台没起来，或模型接口不通。
看 `engine\engine_run.log`，正常应每 60 秒一行 `状态已更新` 或 `无变化`。

**耗 token 太多** — 把 `config\llm.json` 的 `interval_seconds` 调大（下限 30 秒），
或者把 `content_level` 从 `light` 降到 `off`。单轮输入：`off` 约 480 字、
`light` 约 815 字、`full` 约 1550 字。关掉面板后引擎会在 20 秒内自己休眠。

**任务名乱** — 模型只看到窗口标题和窗口里显示的字，看不到你改了哪一格、翻到第几页。
WPS 私有格式（`.et`/`.wps`）和 PDF 只能靠 OCR，仍有错字（`缋效` `报佾`），
提示词里已让它别把乱码当客户名，但命名还是需要手动修。

**抓不到窗口内容** — 先 `pip install comtypes winsdk rapidocr onnxruntime` 看是否缺包。
办公文档（xlsx/docx/pptx）是直接读磁盘文件的，不需要 OCR —— 读不到通常是标题里没有
完整文件名，或者文件不在 `%USERPROFILE%\Microsoft\Windows\Recent` 记录里、也不在
`doc_reader.SCAN_ROOTS` 列的目录下。UIA 对 WPS/Office 基本无效（只回固定的
"文档内按F1"提示），这些程序走 OCR。OCR 若连续 25 秒不返回会被永久关闭（防止拖死
采样进程），重启引擎可恢复。`config\win_log.jsonl` 里 `src` 字段会写
`file`（读的文档原文，最准）/ `uia` / `ocr` / `uia+ocr`，为空说明这次没抓到。

**表格里的字认错了** — 换 OCR 引擎：`config\llm.json` 的 `ocr_engine` 设成 `rapid`
（RapidOCR，准但慢 3~5 秒）或 `windows`（系统 OCR，快但表格错字多）。
更好的办法是让 `doc_read` 保持 `true` —— 能读到文件就完全不经过 OCR。

**任务被 AI 提前标完成了 / 该完成的一直挂着** — 模型每轮自己判断 status，
证据是轨迹里的完成信号。判断错了点任务左边的圆点手动纠正：手动改过的任务
存进 `_user_state`，之后 AI 再也覆盖不了它（包括 reopen）。
如果整体偏早或偏晚，改 `engine\llm_engine.py` 的 `SYSTEM_PROMPT` 第 9~11 条。

**列表顺序看不懂** — 按 `priority`（high/mid/low）排，同优先级保持模型给的顺序，
`waiting` 沉到最后。优先级在任务 ⓘ 气泡第一行显示。模型没给 priority 的按 mid 排。

**顶部「当前行动」被截断成「中途…」** — 默认两行，超过两行时右侧出现小箭头，
点一下展开完整描述，再点收起。

**托盘图标不见了** — 先确认 `pip install pystray` 装上了（缺了面板照常跑，只是没托盘）；
Windows 的托盘会把不常用的图标收进「^」里，点开看看。面板关掉后图标还在，
右键可以重新打开面板或者退出整个程序。

**今天没有自动生成总结** — 到点那一刻面板必须在跑（它负责触发），
且当天没生成过。手动补：托盘右键「立即生成总结」。
生成失败看 `logs\panel_error.log`（打包版）或 `engine\engine_run.log`（源码版）。

**总结里「明天优先做」是空的或者很敷衍** — 那块要调一次模型，
接口不通就退化成按 priority 排序。检查 `config\llm.json` 的接口地址和模型名。

## 改它

- `engine/win_watch.py` 采样频率、心跳间隔、自身窗口过滤（`SELF_PREFIXES`）、
  内容抓取节奏（`CONTENT_EVERY` / `CONTENT_IDLE_LIMIT`）
- `engine/content_probe.py` 抓内容：`OCR_ONLY_EXES`（哪些程序强制走 OCR）、
  `OCR_CROP_TOP`（切掉顶部 ribbon 的高度）、`NOISE` 词表、`OCR_ENGINE`（引擎选择）
- `engine/doc_reader.py` 读文件：`PARSE_EXTS`（哪些格式能直接解析）、
  `SCAN_ROOTS`（按文件名找文件时扫哪些目录）、`INDEX_TTL`（索引多久重建）
- `engine/llm_engine.py` 提示词（`SYSTEM_PROMPT`）、轨迹压缩（`read_log_tail`）、
  内容档位（`CONTENT_LEVELS`）
- `engine/state_store.py` 合并规则：用户操作优先于 AI，`_user_state` 不会被覆盖；
  `merge_ai_state` 里 `reopen` 分支控制模型能否把已完成的任务改回 active
- `engine/daily_summary.py` 总结内容：`FOCUS_IDLE` / `FOCUS_CAP`（专注时长怎么算）、
  `MAX_TOMORROW`（明天列几条）、`auto_due`（几点触发）
- `engine/summary_html.py` 手账样式：配色在 CSS 变量里，纸底 `#f6f0e2`
- `engine/paths.py` 数据放哪：`SIDEQUEST_HOME` 环境变量优先，打包后默认 `%LOCALAPPDATA%\SideQuest`
- `ui/quest_window.py` 四套皮肤在 `SKINS` 字典（含 `prio_*` 四色），窗口宽 `W=336`
  是布局基准；排序在 `_priority_rank`，头部高度在 `_header_height`，字体在 `_font_size`
- `ui/tray.py` 菜单项、`ui/settings_window.py` 设置项字段

改完 `python engine\ctl.py pause` 再 `resume` 让引擎重载，界面改动要 `.\restart_all.ps1`。
