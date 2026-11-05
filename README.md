# SideQuest

一个常驻桌面的"游戏任务面板"：后台记录你在用什么窗口，本地大模型据此判断你正在做什么任务，把主线/支线任务挂在屏幕右上角的悬浮窗里。


## 为什么做这个

一个人干活时最容易丢的不是时间，是**方向**，中途被打断的工作，随时捡起来。

这个面板解决的是"我现在该干什么、我跑偏了没有"。

## 快速开始

需要 Windows 10/11、Python 3.10+（安装时勾上 `tcl/tk and IDLE`）。面板本身只用标准库；要让它看见窗口里**具体**在做什么，还需要几个包（装不上也不影响启动，只是退回只看标题）：

```powershell
pip install comtypes winsdk rapidocr onnxruntime pystray
```

`comtypes` 用来读 UIA 控件树；`winsdk` 用来调 Windows 自带 OCR（兜底）；`rapidocr` + `onnxruntime` 是识别准确率高得多的 OCR（表格里的字基本不会认错，代价是慢十倍）；`pystray` 提供托盘图标（装不上就只是没有托盘，面板照常跑）。全部本地调用，不联网、不上传截图。

只想装最轻的一套：`pip install comtypes winsdk` 也能用，只是表格内容会认错几个字。

```powershell
git clone https://github.com/hcycyxx/sidequest D:\tools\sidequest
cd D:\tools\sidequest
.\install.ps1 -BaseUrl http://127.0.0.1:8899/v1 -ApiKey sk-xxx -Model deepseek-v4.1-flash
```

`install.ps1` 检查 Python 和 tkinter、生成 `config\llm.json`、播种示例任务状态、探一下模型接口，然后拉起面板和后台服务。不需要管理员权限，不写注册表。

不想一开始就启动就加 `-NoStart`，改完 `config\llm.json` 再手动起：

```powershell
python engine\ctl.py panel
python engine\ctl.py resume
```

模型接口只要能应答 `/v1/chat/completions` 就行：本机网关（Ollama、LM Studio、vLLM、one-api）、云厂商、任何兼容实现都可以。要求输出严格 JSON，小模型也能胜任。

### 装成 DeepSeek Harness 技能

让 DSH 自己管理安装和排障，把它放进共享技能目录：

```powershell
git clone https://github.com/hcycyxx/sidequest "$env:USERPROFILE\.agents\skills\sidequest"
```

之后在 DSH 里说"装一下任务面板"或"面板不刷新了"，它会读 `SKILL.md` 按里面的步骤处理。

## 结构

```
sidequest/
├── SKILL.md             # DSH 技能入口（装成技能时才用）
├── sidequest.py         # 打包入口：--panel / --worker / --summary
├── build.spec           # PyInstaller 打包描述
├── installer.iss        # Inno Setup 安装脚本（生成 Setup.exe）
├── install.ps1          # 一键安装：查环境、写配置、拉起服务
├── restart_all.ps1      # 面板卡住时整条重启，尊重暂停标记
├── engine/
│   ├── paths.py         # 路径分流：源码跑在项目里，打包后数据落 %LOCALAPPDATA%
│   ├── win_watch.py     # 窗口看门：前台窗口标题 + 进程名 + 空闲秒数，写 win_log.jsonl
│   ├── content_probe.py # 内容抓取：读文件 / UIA 控件树 / OCR，拿到窗口里正在看的字
│   ├── doc_reader.py    # 文档解析：标题里的文件名 → 定位磁盘文件 → xlsx/docx/pptx 原文
│   ├── llm_engine.py    # 主循环：压缩轨迹 → 调模型 → 合并写状态
│   ├── state_store.py   # 状态层：文件锁、原子写、用户操作与 AI 结果合并
│   ├── daily_summary.py # 每日总结：收集状态与轨迹 → 问模型明天做什么 → 写 HTML
│   ├── summary_html.py  # 手账风格 HTML 渲染（纯函数，只依赖标准库）
│   └── ctl.py           # 进程控制：pause / resume / panel / status
├── ui/
│   ├── quest_window.py  # tkinter 悬浮窗（四皮肤、贴边把手、进度环、时间轴、托盘接线）
│   ├── tray.py          # 托盘图标与右键菜单（pystray，动作走队列回主线程）
│   └── settings_window.py # 详细设置窗口：模型 API、字体大小、内容开关、总结时间
├── assets/
│   └── sidequest.ico    # 托盘与安装包图标（tools/make_icon.py 生成）
├── tools/
│   ├── make_icon.py     # 画图标，七个尺寸
│   ├── backup.ps1       # 本地版本备份：裸仓库 + bundle + 任务状态快照
│   ├── post-commit      # 钩子本体，提交后自动跑 backup.ps1
│   └── install-hooks.ps1# 把钩子装进 .git/hooks（install.ps1 会自动调）
└── config/
    ├── llm.json         # 模型地址、模型名、分析间隔、内容抓取开关（安装时生成）
    └── quest_state.json # 任务状态（运行时生成）
```

一次循环：`win_watch` 每 2 秒采样前台窗口 → 换窗口或每 45 秒调 `content_probe` 抓一次窗口里的文字 → `llm_engine` 每 60 秒读最近轨迹、压成"专注段" → 请求 OpenAI 兼容接口 → 拿到 `{changed, state}` → 与磁盘状态合并 → `ui` 每 3 秒刷新。

## 三个设计取舍

**1. 先看窗口标题，再看窗口里的字，最后才考虑截图**

窗口标题形如 `Offer 261029.xlsx - WPS Office`，纯文本就能推断任务，比截图省几个数量级的 token。光有标题只能知道"在 WPS 里"，所以加了一层**窗口内文字**，按可靠性从高到低取：

| 手段 | 覆盖 | 速度 | 准确度 | 依赖 |
|---|---|---|---|---|
| 读文件 | 标题里带文件名的 xlsx/xlsm/docx/pptx/xls/csv；资源管理器（标题就是路径） | 2ms | 一字不差 | 无（xls 需 `xlrd`） |
| UIA 控件树 | 浏览器、Electron、聊天工具 | 100~400ms | 准 | `comtypes` |
| RapidOCR | 其余一切（PDF、网页、WPS 私有格式、图片） | 3~5 秒 | 9/9 关键词正确 | `rapidocr` |
| 系统 OCR | 兜底 | 0.3~0.5 秒 | 0/9 关键词正确 | `winsdk` |

**为什么读文件排第一**：OCR 认表格必错字。同一张绩效表，系统 OCR 把「绩效」认成「缋效」、「报价」认成「报佾」，九个常用词一个都没对；RapidOCR 好一些，9 个全对。而 `.xlsx`/`.docx` 本身就是 zip 包，里面存的是原文，读出来一个字都不会错，还只要 2 毫秒 —— 快一千多倍。只有读不到文件时才退回 OCR。

RapidOCR 比系统 OCR 准得多但慢十倍（3~5 秒 vs 0.4 秒）。内容抓取本来就在后台线程、45 秒一轮，等得起，所以默认用它。

全部是**纯本地**的，不截图发给模型，也不联网。办公套件走 OCR 时会先切掉顶部 150~190px 的 ribbon 功能区——那一片全是"插入 页面布局 公式"这类固定按钮名，OCR 出来全是噪声。

**2. 轨迹按"专注段"压缩**

40 条窗口记录直接发过去是 2043 字符；合并连续同窗口、丢弃 <5 秒抖动、给每段算停留时长之后是 438 字符、10 段。加上内容行后实测三档：

| `content_level` | 每轮字符 | 说明 |
|---|---|---|
| `off` | 477 | 只有标题，最省 |
| `light`（默认） | 815 | 最近 2 段各带 160 字内容 |
| `full` | 1553 | 最近 5 段各带 260 字内容 |

**3. 用户的手动操作不可被 AI 覆盖**

点勾选、标完成都记进任务内的 `_user_state`（包含显式的 `false`）。AI 返回结果时先重读磁盘最新状态再合并——60 秒模型调用期间用户的操作不会丢，过期的 AI 响应也不会把用户刚取消的勾又勾回去。

## 界面

- 默认折叠：进度环 + 当前行动 + 主线名
- 点开：主线/支线任务、每项进度条、可展开的步骤、下一步建议、已完成时间轴、今日回顾
- 顶栏整条可拖动，六个按钮：皮肤（深蓝玻璃 / 轻透悬浮 / 杂志手账 / 夜航 HUD）、暂停、总在最前、图钉、收起、关闭，悬停有说明
- 拖到边缘松手后鼠标移开自动缩成竖把手，移回展开，图钉可固定
- 任务左侧圆点 = 完成/恢复；标题区 = 展开步骤（分开是为了避免点标题时误标完成）
- 进度条颜色跟紧急程度走：红 = 高（客户在等、有金额和交期）、琥珀 = 中、灰蓝 = 低、青色 = 等对方回话。颜色挑的是"红黄灰青"这条最符合直觉的语义，不用紫绿这类需要记住含义的色
- 顶部「当前行动」超过两行会折起来，点右边的箭头看完整描述
- 半透明时背景透、文字不透明（文字画在另一个点击穿透的窗口上）

## 托盘与每日总结

右下角托盘有个 SideQuest 图标，右键：

| 菜单项 | 作用 |
|---|---|
| 打开今日总结 | 打开 `summaries\YYYY-MM-DD.html`，今天还没生成就先生成 |
| 历史总结 | 子菜单列出最近 12 天，点哪天看哪天 |
| 显示 / 隐藏面板 | 隐藏只收起窗口，采样和 AI 分析继续跑 |
| 立即生成总结 | 手动生成今天的，生成完自动打开 |
| 详细设置… | 模型 API、字体大小、内容抓取开关、总结时间 |
| 退出 SideQuest | 面板 + 采样 + 引擎一起停 |

每天 18:00（可在详细设置里改）自动生成一份手账风格的 HTML，内容四块：**今日完成**（带完成时刻和步骤勾选情况）、**还在进行中**（按优先级排，带进度和下一步）、**明天优先做**（问一次模型，接口不通就按优先级兜底）、**今日时间轴**（完成/新建/重开按时间排）+ 专注时长统计。

「明天优先做」和正文的一句话建议都要调一次模型，所以生成会花几秒；接口不可用时整份总结照样出，只是这两块退化成规则排序。

## 打包成 exe 一键安装

不想装 Python，两种装法任选：

| 方式 | 文件 | 适合 |
| --- | --- | --- |
| 安装包 | [SideQuest-Setup-1.1.0.exe](https://github.com/hcycyxx/sidequest/releases/latest)（约 100 MB） | 装到本机、要开始菜单和开机启动 |
| 便携版 | [SideQuest-portable-1.1.0.zip](https://github.com/hcycyxx/sidequest/releases/latest)（约 140 MB） | 不想动系统、或安装包报"拒绝访问"时 |

便携版解压到任意目录，双击里面的 `start-portable.bat` 就能跑，配置和总结都留在旁边的 `data\` 里，删目录即卸载。

**安装包如果报 `Setup was unable to create the directory "...\Temp\is-XXXX.tmp" / Error 5: 拒绝访问`**，是 Inno Setup 在 `%TEMP%` 建受保护临时目录被拒（常见于 Temp 目录 ACL 被改过、或被安全软件锁住）。三个办法：用便携版；先把 `%TEMP%` 换到别处（`set TEMP=D:\temp`）再跑；或者用管理员身份运行安装包。

自己编译：

```powershell
python tools\make_icon.py                      # 图标（已生成可跳过）
python -m PyInstaller --noconfirm build.spec   # 产出 dist\SideQuest\ 目录
ISCC.exe installer.iss                         # 产出 dist\SideQuest-Setup-1.1.0.exe
```

`ISCC.exe` 在 Inno Setup 安装目录（`winget install --id JRSoftware.InnoSetup` 装，通常在 `%LOCALAPPDATA%\Programs\Inno Setup 6`）。

产物是**目录形式**（`dist\SideQuest\SideQuest.exe` + `_internal\`），不是单文件。原因很实在：整包 300 MB（RapidOCR 的模型和 onnxruntime 占大头），单文件模式每次启动都要把这 300 MB 解压到临时目录，冷启动要十几秒，而且临时目录不可写时会直接起不来。目录形式只在安装时解压一次。

装到 `%LOCALAPPDATA%\Programs\SideQuest`，**不需要管理员权限**。配置、任务状态、日志、每日总结都在 `%LOCALAPPDATA%\SideQuest\`（可用环境变量 `SIDEQUEST_HOME` 改到别处），首次启动会从安装包里播种一份默认配置。卸载时会问要不要连这些数据一起删，默认不删。

安装选项里可以勾"开机启动"，也可以自己把快捷方式丢进 `shell:startup`。**不能用 Windows 服务**——服务跑在 session 0，画不出悬浮窗也弹不出托盘图标。

打包版和源码版的差别只在路径：源码跑在项目目录里，打包版把数据写到用户目录（程序目录在安装位置，只读）。

## 控制与开销

```powershell
python engine\ctl.py            # 状态
python engine\ctl.py pause      # 停掉采样与推断
python engine\ctl.py resume     # 恢复
python engine\ctl.py panel      # 只开面板
```

暂停会真的杀掉采样与 LLM 两个进程，只留面板本身——因为面板要继续刷新才能显示"已暂停"并让你点继续。暂停状态落盘到 `config\paused`，重启后不会自动恢复消耗。面板关闭时（`config/panel_alive` 心跳停止）引擎会在 20 秒内自动休眠。

`ctl.py` 只认命令行里同时出现脚本名和本项目根目录的进程，同一台机器上装两份不会互相误杀。

### 内容抓取开关

`config\llm.json` 里四个字段：

```jsonc
{
  "content_capture": true,     // false = 完全不抓窗口内容，只记标题
  "content_level": "light",    // off / light / full，见上面的字符对照表
  "doc_read": true,            // false = 不读磁盘上的文档，只走 UIA/OCR
  "ocr_engine": "auto"         // auto / rapid / windows / off
}
```

`ocr_engine` 说明：`auto`（默认，装了 RapidOCR 就用它，否则用系统 OCR）、`rapid`（强制 RapidOCR，准但慢）、`windows`（强制系统 OCR，快但表格错字多）、`off`（完全不 OCR，只读文件和 UIA —— 最省 CPU）。

`doc_read` 关掉的话就回到"只靠认字"的老路子，表格里的客户名和金额会认错几个字。

改完重启生效：`python engine\ctl.py pause && python engine\ctl.py resume`。

抓取只在三种情况下发生：换了窗口、同一个窗口停留超过 45 秒、或者人刚回到电脑前。你人离开超过 90 秒就不抓了（抓了也是静态画面），离开超过 180 秒连心跳都不补——否则"打开文档去吃饭"会被算成专注三小时。

抓到的文字只在本地处理，写进 `config\win_log.jsonl`（4MB 轮转，保留最后 2000 行），发给模型的只有最后 2~5 段、每段 160~260 字。想彻底不留痕就设 `"content_capture": false`。

## 本地版本备份

代码在 GitHub 上有一份，但工作区可能被别的东西清掉（磁盘清理工具、自动更新都可能）。所以每次提交都会在工作区**之外**再留一份：

```
%USERPROFILE%\sidequest-archive.git     裸仓库，含全部分支与 tag
%USERPROFILE%\sidequest-backups\        sidequest-<rev>.bundle + state-<时间>-<rev>.json
```

bundle 是单文件，离线就能 `git clone` 出来；`state-*.json` 是任务状态快照——这个文件在 `.gitignore` 里，但它是整个项目最值钱的数据。

手动备份一次：

```powershell
powershell -ExecutionPolicy Bypass -File tools\backup.ps1
```

钩子装在 `.git/hooks/post-commit`，而那个目录不归 git 管，所以换了新克隆要重装一次（`install.ps1` 会自动装）：

```powershell
powershell -ExecutionPolicy Bypass -File tools\install-hooks.ps1
```

从备份恢复：

```powershell
git clone "$env:USERPROFILE\sidequest-backups\sidequest-<rev>.bundle" sidequest
```

## 已知限制

- 读文件读到的是**磁盘上的版本**：文档有未保存改动时（标题带 `*`）会比屏幕上的旧一点，"在改哪个客户的哪张表"是准的，具体某一格改成了多少不准
- 只有标题里带文件名的文档才读得到；PDF、网页、WPS 私有格式（`.et`/`.wps`/`.dps`）、图片只能靠 OCR，仍有错字风险
- 只知道"这个窗口里显示了这些字"，不知道你改了哪一格、翻到第几页，"这一页写到哪里了"这类进度仍然猜不准
- 不估算工作量，进度条要么来自显式进度字段，要么来自勾选步骤比例，否则显示"待估算"
- 模型判断有主观性，任务被拆得不对时需要手动改

## AI 自主判断的边界

面板不只是记录，它会自己决定三件事：

1. **重要程度**：每条任务带 `priority`（high / mid / low），列表按它排序，顶部进度环跟的是最该做的那条主线。客户下单、发货、交期、金额大的给 high，整理资料给 low。
2. **完成 / 重开**：轨迹里出现明确完成信号才标 done；之后你又打开同一个文件继续改，它会写 `"reopen": true` 把任务改回 active —— 前提是你没手动勾过它。
3. **支线收尾**：支线超过两小时没再碰、主线还开着，就自动标完成，不让列表越堆越长。

这三件事全部由模型在每轮分析里给出，本地只负责校验：**你手动勾过的任务，AI 永远覆盖不了**（存在任务内的 `_user_state` 里）。想让它更保守，就把 `engine\llm_engine.py` 的 `SYSTEM_PROMPT` 里第 9~11 条改严。

自动判定完成**不会问你**，所以判断早了任务会提前沉到历史，判断晚了会一直挂着；两种情况都点左边圆点手动纠正，手动改过的任务 AI 不再覆盖。
