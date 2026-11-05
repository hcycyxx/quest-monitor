# SideQuest

一个常驻桌面的"游戏任务面板"：后台记录你在用什么窗口，本地大模型据此判断你正在做什么任务，把主线/支线任务挂在屏幕右上角的悬浮窗里。

做报价时突然接到客户订单、转去整理包材——面板会自动挂出一条支线「XX 客户包材整理中」，做完再回到主线。

## 为什么做这个

一个人干活时最容易丢的不是时间，是**方向**，中途被打断的工作，随时捡起来。

这个面板解决的是"我现在该干什么、我跑偏了没有"。

## 快速开始

需要 Windows 10/11、Python 3.10+（安装时勾上 `tcl/tk and IDLE`）。纯标准库，不用 pip 装任何东西。

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
├── install.ps1          # 一键安装：查环境、写配置、拉起服务
├── restart_all.ps1      # 面板卡住时整条重启，尊重暂停标记
├── engine/
│   ├── win_watch.py     # 窗口看门：前台窗口标题 + 进程名 + 空闲秒数，写 win_log.jsonl
│   ├── llm_engine.py    # 主循环：压缩轨迹 → 调模型 → 合并写状态
│   ├── state_store.py   # 状态层：文件锁、原子写、用户操作与 AI 结果合并
│   └── ctl.py           # 进程控制：pause / resume / panel / status
├── ui/
│   └── quest_window.py  # tkinter 悬浮窗（四皮肤、贴边把手、进度环、时间轴）
├── tools/
│   ├── backup.ps1       # 本地版本备份：裸仓库 + bundle + 任务状态快照
│   ├── post-commit      # 钩子本体，提交后自动跑 backup.ps1
│   └── install-hooks.ps1# 把钩子装进 .git/hooks（install.ps1 会自动调）
└── config/
    ├── llm.json         # 模型地址、模型名、分析间隔（安装时生成）
    └── quest_state.json # 任务状态（运行时生成）
```

一次循环：`win_watch` 每 2 秒采样前台窗口 → `llm_engine` 每 60 秒读最近轨迹、压成"专注段" → 请求 OpenAI 兼容接口 → 拿到 `{changed, state}` → 与磁盘状态合并 → `ui` 每 3 秒刷新。

## 三个设计取舍

**1. 先看窗口标题，再看屏幕**

窗口标题形如 `Offer 261029.xlsx - WPS Office`，纯文本就能推断任务，比截图省几个数量级的 token。当前版本不截图。

**2. 轨迹按"专注段"压缩**

40 条窗口记录直接发过去是 2043 字符；合并连续同窗口、丢弃 <5 秒抖动、给每段算停留时长之后是 438 字符、10 段。实测每轮输入从约 5000 token 降到约 840，每小时约 5 万 token。

**3. 用户的手动操作不可被 AI 覆盖**

点勾选、标完成都记进任务内的 `_user_state`（包含显式的 `false`）。AI 返回结果时先重读磁盘最新状态再合并——60 秒模型调用期间用户的操作不会丢，过期的 AI 响应也不会把用户刚取消的勾又勾回去。

## 界面

- 默认折叠：进度环 + 当前行动 + 主线名
- 点开：主线/支线任务、每项进度条、可展开的步骤、下一步建议、已完成时间轴、今日回顾
- 顶栏整条可拖动，五个按钮：皮肤（深蓝玻璃 / 轻透悬浮 / 杂志手账 / 夜航 HUD）、暂停、图钉、收起、关闭，悬停有说明
- 拖到边缘松手后鼠标移开自动缩成竖把手，移回展开，图钉可固定
- 任务左侧圆点 = 完成/恢复；标题区 = 展开步骤（分开是为了避免点标题时误标完成）

## 控制与开销

```powershell
python engine\ctl.py            # 状态
python engine\ctl.py pause      # 停掉采样与推断
python engine\ctl.py resume     # 恢复
python engine\ctl.py panel      # 只开面板
```

暂停会真的杀掉采样与 LLM 两个进程，只留面板本身——因为面板要继续刷新才能显示"已暂停"并让你点继续。暂停状态落盘到 `config\paused`，重启后不会自动恢复消耗。面板关闭时（`config/panel_alive` 心跳停止）引擎会在 20 秒内自动休眠。

`ctl.py` 只认命令行里同时出现脚本名和本项目根目录的进程，同一台机器上装两份不会互相误杀。

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

- 只靠窗口标题和停留时长推断，读不到文档内容，"这一页写到哪里了"这类进度猜不准
- 不估算工作量，进度条要么来自显式进度字段，要么来自勾选步骤比例，否则显示"待估算"
- 任务状态只有 `active` / `pending` / `done`，等待对方回复这类状态暂无
- 模型判断有主观性，任务被拆得不对时需要手动改
