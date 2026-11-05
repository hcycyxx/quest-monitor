"""把「每日任务总结」数据渲染成手账（bullet journal）风格的单页中文 HTML。

纯函数模块，唯一公开入口是 ``render(data) -> str``：不做任何 I/O、不读外部模板、
不联网、不依赖第三方库，输出是一份可以直接双击打开的完整 HTML 文档字符串。

设计约束：
- 只用标准库（html / datetime）；
- 所有用户内容在写入 HTML 前统一经 ``html.escape(..., quote=True)`` 转义；
- 输入字段可能缺失、为 None 或空字符串，全部走 _text / _int / _seq 容错；
- 视觉上模仿纸本手账：米色纸底 + 极淡横格线、衬线字体、胶带与手绘下划线、
  SVG 打勾方框、竖直虚线时间轴，克制使用装饰元素。
"""

import html
from datetime import datetime

_WEEKDAYS = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')

_PRIORITY_LABEL = {'high': '高', 'mid': '中', 'low': '低'}
_STATUS_LABEL = {'active': '进行中', 'pending': '待办', 'waiting': '等待'}
_KIND_LABEL = {'created': '新建', 'done': '完成', 'reopened': '重开'}
_KEY_LABEL = {'main_quests': '主线', 'side_quests': '支线'}

# 手绘感的打勾方框：描边 2px、圆头圆角，颜色由 CSS 的 currentColor 控制（跟随优先级）。
_CHECK_SVG = (
    '<svg class="check" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">'
    '<rect x="3.6" y="3.6" width="16.8" height="16.8" rx="2.8" fill="none"'
    ' stroke="currentColor" stroke-width="1.6"/>'
    '<path d="M7.4 12.3l3.3 3.5 6.3-7.2" fill="none" stroke="currentColor"'
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

# 页头右侧的小回形针，纯 SVG 描边，不用图片。
_CLIP_SVG = (
    '<svg class="clip" viewBox="0 0 24 48" width="15" height="30" aria-hidden="true" focusable="false">'
    '<path d="M15.6 12.5v20.6a5.6 5.6 0 0 1-11.2 0V9.8a3.6 3.6 0 0 1 7.2 0v20.2"'
    ' fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>'
)


# ---------------------------------------------------------------- 取值与容错

def _text(value):
    """把任意值收敛成去掉首尾空白的字符串；None / 布尔返回空串。"""
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return ''
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).strip()


def _esc(value):
    """转义为可安全嵌入 HTML 的文本（quote=True 同时处理引号）。"""
    return html.escape(_text(value), quote=True)


def _int(value, default=0):
    """宽松取整：'3' / 3.7 / None / 'x' 都能得到可用整数。"""
    if isinstance(value, bool):
        return int(value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _seq(value):
    """只接受 list / tuple，其余一律当空列表，避免把字符串当序列展开。"""
    return list(value) if isinstance(value, (list, tuple)) else []


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _priority(value):
    """high / mid / low；空值或未知值按 mid 处理。"""
    label = _text(value).lower()
    return label if label in _PRIORITY_LABEL else 'mid'


def _hours(minutes):
    """214 -> '3.6'；0 / 负数 / 非法 -> '0'。"""
    total = _int(minutes)
    if total <= 0:
        return '0'
    value = '%.1f' % (total / 60.0)
    return value.rstrip('0').rstrip('.') if '.' in value else value


def _stamp(value):
    """'2026-11-05T18:00:12+08:00' -> '2026-11-05 18:00:12'。"""
    raw = _text(value).replace('T', ' ')
    if not raw:
        return ''
    return raw[:19] if len(raw) > 19 else raw


def _weekday_label(data):
    """优先用传入的 weekday，缺失时从 date 推算；都拿不到返回空串。"""
    label = _text(data.get('weekday'))
    if label:
        return label
    iso = _text(data.get('date'))
    if len(iso) < 10:
        return ''
    try:
        return _WEEKDAYS[datetime.strptime(iso[:10], '%Y-%m-%d').weekday()]
    except ValueError:
        return ''


# ---------------------------------------------------------------- 样式

_CSS = """
:root{
  --paper:#f6f0e2;
  --ink:#3a3228;
  --ink-soft:#6f6555;
  --ink-faint:#9a8f7c;
  --high:#c2543f;
  --mid:#c08a2e;
  --low:#5f7f8c;
  --moss:#6d7f52;
  --clay:#a9704f;
  --serif:"Georgia","Songti SC","SimSun","Noto Serif CJK SC","Times New Roman",serif;
  --mono:ui-monospace,"Cascadia Mono","Consolas","Courier New",monospace;
}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{
  margin:0;padding:40px 18px 72px;
  color:var(--ink);font-family:var(--serif);font-size:15px;line-height:1.85;
  background-color:#ece2cf;
  background-image:
    radial-gradient(circle at 20% 8%,rgba(255,255,255,.52),transparent 46%),
    radial-gradient(circle at 78% 92%,rgba(200,180,142,.42),transparent 52%);
  background-attachment:fixed;
}
.page{
  position:relative;max-width:820px;margin:0 auto;padding:56px 58px 38px;
  background-color:var(--paper);
  background-image:repeating-linear-gradient(
    to bottom,rgba(124,108,82,.085) 0 1px,transparent 1px 30px);
  border-radius:2px;
  box-shadow:0 20px 46px -22px rgba(62,50,34,.5),0 2px 5px rgba(62,50,34,.12);
}
.page::before{
  content:"";position:absolute;top:0;bottom:0;left:34px;width:1px;pointer-events:none;
  background:linear-gradient(to bottom,rgba(178,96,78,0),rgba(178,96,78,.2) 14%,
    rgba(178,96,78,.2) 86%,rgba(178,96,78,0));
}

/* 页头 */
.head{position:relative;padding:2px 0 26px}
h1{margin:0;font-size:34px;font-weight:600;letter-spacing:.18em;line-height:1.3}
.tape{
  position:absolute;top:-30px;left:-6px;width:128px;height:26px;transform:rotate(-2deg);
  background:linear-gradient(102deg,rgba(228,206,158,.62),rgba(208,184,130,.44));
  border-left:1px dashed rgba(255,255,255,.6);border-right:1px dashed rgba(255,255,255,.6);
  box-shadow:0 2px 5px rgba(86,70,46,.16);opacity:.92;
}
.tape::after{
  content:"";position:absolute;inset:0;opacity:.5;
  background:repeating-linear-gradient(90deg,rgba(255,255,255,.3) 0 5px,transparent 5px 12px);
}
.clip{position:absolute;right:6px;top:-14px;color:rgba(96,80,58,.42);transform:rotate(9deg)}
.dateline{margin:11px 0 0;font-size:15px;letter-spacing:.08em;color:var(--ink-soft)}
.sep{padding:0 .4em;opacity:.55}
.stamp{margin:1px 0 0;font-size:11.5px;font-family:var(--mono);color:var(--ink-faint);letter-spacing:.05em}

/* 数据行 */
.stats{
  display:flex;flex-wrap:wrap;align-items:center;gap:0 14px;margin:0 0 8px;padding:10px 2px;
  border-top:1px solid rgba(124,108,82,.3);border-bottom:1px solid rgba(124,108,82,.3);
}
.stat{display:inline-flex;align-items:baseline;gap:7px;font-size:14px;letter-spacing:.04em;color:var(--ink-soft)}
.stat-value{font-family:var(--mono);font-size:16px;color:var(--ink);letter-spacing:.02em}
.stats-sep{width:1px;height:15px;background:rgba(124,108,82,.34)}
.stats-sub{margin:0 0 28px;font-size:11.5px;font-family:var(--mono);color:var(--ink-faint);letter-spacing:.06em}

/* 便签（一句话建议） */
.memo{
  position:relative;margin:2px 0 32px;padding:15px 18px 16px;transform:rotate(-.35deg);
  background:rgba(255,252,240,.74);border:1px solid rgba(124,108,82,.24);
  border-left:3px solid var(--clay);box-shadow:0 6px 14px -10px rgba(86,70,46,.5);
}
.memo::before{
  content:"";position:absolute;top:-9px;left:50%;width:74px;height:16px;margin-left:-37px;
  background:linear-gradient(102deg,rgba(228,206,158,.6),rgba(208,184,130,.42));
  transform:rotate(-1.6deg);opacity:.9;
}
.memo-label{margin:0 0 4px;font-size:11px;font-family:var(--mono);letter-spacing:.12em;color:var(--ink-faint)}
.memo-text{margin:0;font-size:14.5px;line-height:1.85}

/* 分区标题 + 手绘下划线 */
.sec{margin:0 0 32px;padding:0}
h2{
  position:relative;display:inline-block;margin:0 0 16px;padding:0 3px 8px;
  font-size:19px;font-weight:600;letter-spacing:.12em;
}
h2::before,h2::after{
  content:"";position:absolute;left:-2px;right:-6px;bottom:3px;
  border-bottom:1.4px solid rgba(96,82,60,.5);
}
h2::before{transform:rotate(-.55deg)}
h2::after{bottom:0;left:2px;right:-2px;border-bottom-width:1.2px;border-bottom-color:rgba(96,82,60,.26);transform:rotate(.45deg)}

/* 条目 */
.list,.next-list,.acts{list-style:none;margin:0;padding:0}
.item{display:flex;gap:12px;padding:9px 2px 10px}
.item + .item{border-top:1px dashed rgba(124,108,82,.3)}
.body{flex:1 1 auto;min-width:0}
.check{flex:0 0 auto;margin-top:5px;color:var(--mid)}
.p-high .check{color:var(--high)}
.p-low .check{color:var(--low)}
.bullet{
  flex:0 0 auto;width:10px;height:10px;margin-top:9px;border-radius:50%;
  border:1.6px solid var(--mid);background:transparent;
}
.p-high .bullet{border-color:var(--high)}
.p-low .bullet{border-color:var(--low)}
.t-title{margin:0;font-size:16px;line-height:1.62;font-weight:600;letter-spacing:.02em}
.meta{margin:3px 0 0;font-size:11.5px;font-family:var(--mono);color:var(--ink-faint);letter-spacing:.06em}
.meta .chip{font-family:var(--serif);letter-spacing:.08em}
.chip.pv-high{color:var(--high)}
.chip.pv-mid{color:var(--mid)}
.chip.pv-low{color:var(--low)}
.chip.s-active{color:var(--moss)}
.chip.s-pending{color:var(--ink-faint)}
.chip.s-waiting{color:var(--clay)}
.i-note{margin:5px 0 0;font-size:13.5px;line-height:1.8;color:var(--ink-soft)}

/* 步骤小方框 */
.steps{list-style:none;margin:7px 0 0;padding:0}
.step{display:flex;gap:8px;align-items:flex-start;font-size:13px;line-height:1.75;color:var(--ink-soft)}
.step-mark{flex:0 0 auto;width:7px;height:7px;margin-top:8px;border:1px solid currentColor;border-radius:1px;opacity:.7}
.step.is-done{color:#5d6a4c}
.step.is-done .step-mark{background:currentColor;opacity:.9}

/* 时间轴：竖直虚线 + 圆点 */
.tl{position:relative;list-style:none;margin:0;padding:2px 0 2px 30px}
.tl::before{content:"";position:absolute;left:7px;top:7px;bottom:7px;border-left:1.5px dashed rgba(110,94,68,.45)}
.tl-item{position:relative;display:flex;flex-wrap:wrap;align-items:baseline;gap:3px 10px;padding:4px 0 10px}
.tl-dot{
  position:absolute;left:-26px;top:12px;width:9px;height:9px;border-radius:50%;
  background:var(--paper);border:1.5px solid var(--ink-soft);box-shadow:0 0 0 3px rgba(246,240,226,.92);
}
.tl-dot.k-created{border-color:var(--low)}
.tl-dot.k-done{border-color:var(--moss)}
.tl-dot.k-reopened{border-color:var(--clay)}
.tl-time{min-width:44px;font-family:var(--mono);font-size:12px;color:var(--ink-faint);letter-spacing:.04em}
.tl-title{font-size:14.5px}
.tl-kind{font-size:11px;letter-spacing:.1em;color:var(--ink-faint);border-bottom:1px dotted currentColor}
.tl-kind.k-done{color:var(--moss)}
.tl-kind.k-reopened{color:var(--clay)}

/* 明天优先做 */
.next{
  position:relative;margin:0 0 10px;padding:11px 14px 12px 56px;
  border-left:3px solid var(--mid);border-radius:0 2px 2px 0;background:rgba(255,255,255,.34);
}
.next.p-high{border-left-color:var(--high)}
.next.p-low{border-left-color:var(--low)}
.next .num{position:absolute;left:16px;top:12px;font-family:var(--mono);font-size:13px;letter-spacing:.08em;color:var(--ink-faint)}
.next .t-title{font-size:15.5px;padding-right:28px}
.why{margin:4px 0 0;font-size:13px;line-height:1.78;color:var(--ink-soft)}
.plabel{position:absolute;right:12px;top:11px;font-size:10.5px;font-family:var(--mono);letter-spacing:.12em;color:var(--mid);opacity:.9}
.next.p-high .plabel{color:var(--high)}
.next.p-low .plabel{color:var(--low)}

/* 工作段 */
.act{display:flex;gap:14px;align-items:baseline;padding:8px 2px 9px}
.act + .act{border-top:1px dashed rgba(124,108,82,.26)}
.act-time{flex:0 0 auto;min-width:106px;font-family:var(--mono);font-size:12px;color:var(--ink-faint);letter-spacing:.03em}
.act-text{font-size:14px;line-height:1.8}

/* 空状态 */
.empty{
  margin:2px 0 0;padding:14px 16px;font-size:14px;line-height:1.9;font-style:italic;
  color:var(--ink-faint);letter-spacing:.04em;border:1px dashed rgba(124,108,82,.42);
  border-radius:2px;background:rgba(255,255,255,.24);
}

/* 页脚 */
.foot{
  margin:34px 0 0;padding-top:14px;border-top:1px solid rgba(124,108,82,.3);
  font-size:11.5px;font-family:var(--mono);letter-spacing:.1em;color:var(--ink-faint);text-align:center;
}

@media (max-width:640px){
  body{padding:16px 10px 40px}
  .page{padding:34px 22px 28px}
  .page::before{left:13px}
  h1{font-size:26px}
  .tape{top:-24px;left:-4px;width:104px;height:22px}
  .act{display:block}
  .act-time{display:block;min-width:0}
}

@media print{
  html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  body{padding:0;background:#fff}
  .page{
    max-width:none;margin:0;padding:18px 22px;border-radius:0;box-shadow:none;
    background-image:repeating-linear-gradient(
      to bottom,rgba(124,108,82,.07) 0 1px,transparent 1px 30px);
  }
  .tape,.clip,.memo::before{box-shadow:none}
  .sec,.item,.next,.tl-item,.act,.memo{break-inside:avoid;page-break-inside:avoid}
  h2{break-after:avoid;page-break-after:avoid}
  .foot{margin-top:20px}
  @page{margin:14mm}
}
"""


# ---------------------------------------------------------------- 各区块

def _head(data):
    title = _text(data.get('date'))
    page_title = '今日总结 · ' + title if title else '今日总结'
    return (
        '<!DOCTYPE html>\n'
        '<html lang="zh-CN">\n'
        '<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<title>' + _esc(page_title) + '</title>\n'
        '<style>' + _CSS + '</style>\n'
        '</head>\n'
        '<body>\n'
        '<main class="page">\n'
    )


def _header(data):
    date = _esc(data.get('date'))
    weekday = _esc(_weekday_label(data))
    stamp = _stamp(data.get('generated_at'))
    out = [
        '<header class="head">',
        '<span class="tape" aria-hidden="true"></span>',
        _CLIP_SVG,
        '<h1>今日总结</h1>',
    ]
    parts = [part for part in (date, weekday) if part]
    if parts:
        out.append('<p class="dateline">' + '<span class="sep">·</span>'.join(parts) + '</p>')
    if stamp:
        out.append('<p class="stamp">生成于 ' + _esc(stamp) + '</p>')
    out.append('</header>')
    return ''.join(out)


def _stats(data):
    stats = _mapping(data.get('stats'))
    rows = (
        ('完成', '%d 项' % _int(stats.get('done'))),
        ('进行中', '%d 项' % _int(stats.get('active'))),
        ('专注约', '%s 小时' % _hours(stats.get('focus_minutes'))),
    )
    out = ['<section class="stats">']
    for index, (label, value) in enumerate(rows):
        if index:
            out.append('<span class="stats-sep" aria-hidden="true"></span>')
        out.append(
            '<span class="stat"><span class="stat-label">' + _esc(label) + '</span>'
            '<span class="stat-value">' + _esc(value) + '</span></span>'
        )
    out.append('</section>')

    sub = []
    if 'main_done' in stats:
        sub.append('主线 %d' % _int(stats.get('main_done')))
    if 'side_done' in stats:
        sub.append('支线 %d' % _int(stats.get('side_done')))
    first_at = _text(stats.get('first_at'))
    if first_at:
        sub.append('第一条 ' + first_at)
    last_at = _text(stats.get('last_at'))
    if last_at:
        sub.append('收尾 ' + last_at)
    if sub:
        out.append('<p class="stats-sub">' + _esc(' · '.join(sub)) + '</p>')
    return ''.join(out)


def _suggestion(data):
    text = _text(data.get('suggestion'))
    if not text:
        return ''
    return (
        '<aside class="memo">'
        '<p class="memo-label">一句话建议</p>'
        '<p class="memo-text">' + _esc(text) + '</p>'
        '</aside>'
    )


def _steps(value):
    rows = []
    for raw in _seq(value):
        step = _mapping(raw)
        text = _esc(step.get('text'))
        if not text:
            continue
        css = 'step is-done' if step.get('done') else 'step'
        rows.append(
            '<li class="' + css + '"><span class="step-mark" aria-hidden="true"></span>'
            '<span>' + text + '</span></li>'
        )
    if not rows:
        return ''
    return '<ul class="steps">' + ''.join(rows) + '</ul>'


def _meta_line(bits):
    """bits 是已转义的 HTML 片段；用间隔点串成一行元信息。"""
    items = [bit for bit in bits if bit]
    if not items:
        return ''
    return '<p class="meta">' + '<span class="sep">·</span>'.join(items) + '</p>'


def _done_item(raw):
    item = _mapping(raw)
    priority = _priority(item.get('priority'))
    title = _esc(item.get('title')) or '（未命名任务）'
    bits = []
    completed_at = _text(item.get('completed_at'))
    if completed_at:
        bits.append(_esc(completed_at))
    key = _text(item.get('key'))
    if key in _KEY_LABEL:
        bits.append('<span class="chip">' + _esc(_KEY_LABEL[key]) + '</span>')
    task_id = _text(item.get('id'))
    if task_id:
        bits.append(_esc(task_id))
    note = _text(item.get('note'))
    return (
        '<li class="item p-' + priority + '">'
        + _CHECK_SVG
        + '<div class="body">'
        '<p class="t-title">' + title + '</p>'
        + _meta_line(bits)
        + ('<p class="i-note">' + _esc(note) + '</p>' if note else '')
        + _steps(item.get('steps'))
        + '</div></li>'
    )


def _done(data):
    items = _seq(data.get('done'))
    out = ['<section class="sec">', '<h2>今日完成</h2>']
    if not items:
        out.append('<p class="empty">今天还没有打勾的条目。留白也是本子的一部分，明天再补上。</p>')
    else:
        out.append('<ul class="list">')
        for raw in items:
            out.append(_done_item(raw))
        out.append('</ul>')
    out.append('</section>')
    return ''.join(out)


def _timeline(data):
    items = _seq(data.get('timeline'))
    out = ['<section class="sec">', '<h2>今日时间轴</h2>']
    if not items:
        out.append('<p class="empty">还没留下时间痕迹，明天从第一笔开始记。</p>')
    else:
        out.append('<ol class="tl">')
        for raw in items:
            entry = _mapping(raw)
            kind = _text(entry.get('kind')).lower()
            if kind not in _KIND_LABEL:
                kind = 'created'
            time_label = _esc(entry.get('time')) or '—'
            title = _esc(entry.get('title')) or '（未命名）'
            out.append(
                '<li class="tl-item">'
                '<span class="tl-dot k-' + kind + '" aria-hidden="true"></span>'
                '<span class="tl-time">' + time_label + '</span>'
                '<span class="tl-title">' + title + '</span>'
                '<span class="tl-kind k-' + kind + '">' + _esc(_KIND_LABEL[kind]) + '</span>'
                '</li>'
            )
        out.append('</ol>')
    out.append('</section>')
    return ''.join(out)


def _active_item(raw):
    item = _mapping(raw)
    priority = _priority(item.get('priority'))
    title = _esc(item.get('title')) or '（未命名任务）'
    status = _text(item.get('status')).lower()
    if status not in _STATUS_LABEL:
        status = 'active'
    bits = ['<span class="chip pv-' + priority + '">' + _esc(_PRIORITY_LABEL[priority]) + ' 优先</span>',
            '<span class="chip s-' + status + '">' + _esc(_STATUS_LABEL[status]) + '</span>']
    progress = _text(item.get('progress'))
    if not progress:
        total = _int(item.get('total_steps'))
        if total > 0:
            progress = '%d/%d' % (_int(item.get('done_steps')), total)
    if progress:
        bits.append(_esc(progress))
    key = _text(item.get('key'))
    if key in _KEY_LABEL:
        bits.append('<span class="chip">' + _esc(_KEY_LABEL[key]) + '</span>')
    task_id = _text(item.get('id'))
    if task_id:
        bits.append(_esc(task_id))
    note = _text(item.get('note'))
    return (
        '<li class="item p-' + priority + '">'
        '<span class="bullet" aria-hidden="true"></span>'
        '<div class="body">'
        '<p class="t-title">' + title + '</p>'
        + _meta_line(bits)
        + ('<p class="i-note">' + _esc(note) + '</p>' if note else '')
        + _steps(item.get('steps'))
        + '</div></li>'
    )


def _active(data):
    items = _seq(data.get('active'))
    out = ['<section class="sec">', '<h2>还在进行中</h2>']
    if not items:
        out.append('<p class="empty">手上没有悬着的事，页面很干净。</p>')
    else:
        out.append('<ul class="list">')
        for raw in items:
            out.append(_active_item(raw))
        out.append('</ul>')
    out.append('</section>')
    return ''.join(out)


def _tomorrow(data):
    items = _seq(data.get('tomorrow'))[:5]
    if not items:
        return ''
    out = ['<section class="sec">', '<h2>明天优先做</h2>', '<ol class="next-list">']
    for index, raw in enumerate(items, 1):
        item = _mapping(raw)
        priority = _priority(item.get('priority'))
        title = _esc(item.get('title')) or '（未命名任务）'
        why = _text(item.get('why'))
        out.append('<li class="next p-' + priority + '">')
        out.append('<span class="num" aria-hidden="true">%02d</span>' % index)
        out.append('<p class="t-title">' + title + '</p>')
        if why:
            out.append('<p class="why">' + _esc(why) + '</p>')
        out.append('<span class="plabel">' + _esc(_PRIORITY_LABEL[priority]) + '</span>')
        out.append('</li>')
    out.append('</ol>')
    out.append('</section>')
    return ''.join(out)


def _activity(data):
    items = _seq(data.get('activity'))
    if not items:
        return ''
    out = ['<section class="sec">', '<h2>今日主要工作段</h2>', '<ul class="acts">']
    for raw in items:
        entry = _mapping(raw)
        start = _text(entry.get('from'))
        end = _text(entry.get('to'))
        if start and end:
            span = '%s–%s' % (start, end)
        else:
            span = start or end or '—'
        text = _esc(entry.get('text')) or '（未记录内容）'
        out.append(
            '<li class="act">'
            '<span class="act-time">' + _esc(span) + '</span>'
            '<span class="act-text">' + text + '</span>'
            '</li>'
        )
    out.append('</ul>')
    out.append('</section>')
    return ''.join(out)


def _foot():
    return (
        '<footer class="foot">SideQuest · 由本地模型自动生成</footer>\n'
        '</main>\n'
        '</body>\n'
        '</html>\n'
    )


# ---------------------------------------------------------------- 公开入口

def render(data: dict) -> str:
    """把总结数据渲染成完整 HTML 文档字符串（含 <!DOCTYPE html>）。"""
    doc = _mapping(data)
    return ''.join((
        _head(doc),
        _header(doc),
        _stats(doc),
        _suggestion(doc),
        _done(doc),
        _timeline(doc),
        _active(doc),
        _tomorrow(doc),
        _activity(doc),
        _foot(),
    ))
