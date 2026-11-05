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
   面板本身纯标准库；要让它看见窗口里**具体**在做什么，再装两个包：

   ```powershell
   pip install comtypes winsdk
   ```

   `comtypes` 读 UIA 控件树，`winsdk` 调 Windows 自带 OCR。装不上也能跑，只是退回只看窗口标题。
2. **一个 OpenAI 兼容的 `/v1/chat/completions` 地址**。可以是本机网关（Ollama、LM Studio、
   vLLM、one-api 之类跑在 `http://127.0.0.1:8899/v1`），也可以是云端。
   `install.ps1` 会去探 `/v1/models`，探不通只警告不中断。
3. **愿意让它记录前台窗口标题和窗口里显示的文字**。它写窗口标题、进程名、空闲秒数、
   以及 UIA/OCR 抓到的窗口内文字到 `config/win_log.jsonl`。**不截全屏、不上传任何图片**，
   抓到的文字只在本地存，发给模型的只有最后 2~5 段、每段 160~260 字。
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
- 顶栏五个按钮：换皮肤 / 暂停 / 图钉 / 收起 / 关闭，鼠标停在上面有说明
- 任务左边圆点 = 标记完成或恢复；点标题 = 展开步骤。分开是为了避免点标题时误标完成
- 拖到屏幕边缘松手，鼠标移开 0.75 秒会缩成竖把手，图钉可固定成常驻展开
- 暂停时标题变金色、进度环变暗，显示的是冻结快照，直到点 ▶

## 排障

**窗口不出现** — `python engine\ctl.py panel` 看有没有报错；tkinter 缺失时 Python
安装包需要重装并勾上 tcl/tk。

**显示"待估算"且一直不更新** — 后台没起来，或模型接口不通。
看 `engine\engine_run.log`，正常应每 60 秒一行 `状态已更新` 或 `无变化`。

**耗 token 太多** — 把 `config\llm.json` 的 `interval_seconds` 调大（下限 30 秒），
或者把 `content_level` 从 `light` 降到 `off`。单轮输入：`off` 约 480 字、
`light` 约 815 字、`full` 约 1550 字。关掉面板后引擎会在 20 秒内自己休眠。

**任务名乱** — 模型只看到窗口标题和窗口里显示的字，看不到你改了哪一格、翻到第几页。
WPS 里 OCR 还有错字（`缋效` `报佾`），提示词里已让它别把乱码当客户名，但命名还是需要手动修。

**抓不到窗口内容** — 先 `pip install comtypes winsdk` 看是否缺包；UIA 对 WPS/Office
基本无效（只回固定的"文档内按F1"提示），这些程序走 OCR。OCR 若连续 8 秒不返回会被永久
关闭（防止拖死采样进程），重启引擎可恢复。`config\win_log.jsonl` 里 `src` 字段会写
`uia` / `ocr` / `uia+ocr`，为空说明这次没抓到。

## 改它

- `engine/win_watch.py` 采样频率、心跳间隔、自身窗口过滤（`SELF_PREFIXES`）、
  内容抓取节奏（`CONTENT_EVERY` / `CONTENT_IDLE_LIMIT`）
- `engine/content_probe.py` 抓内容：`OCR_ONLY_EXES`（哪些程序强制走 OCR）、
  `OCR_CROP_TOP`（切掉顶部 ribbon 的高度）、`NOISE` 词表
- `engine/llm_engine.py` 提示词（`SYSTEM_PROMPT`）、轨迹压缩（`read_log_tail`）、
  内容档位（`CONTENT_LEVELS`）
- `engine/state_store.py` 合并规则：用户操作优先于 AI，`_user_state` 不会被覆盖
- `ui/quest_window.py` 四套皮肤在 `SKINS` 字典，窗口宽 `W=336` 是布局基准

改完 `python engine\ctl.py pause` 再 `resume` 让引擎重载，界面改动要 `.\restart_all.ps1`。
