#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_space_docs.py — 股票项目结构化文档生成器

读取各项目本地文件（背景/架构/模块/配置）+ workbuddy.db（自动化注册表，动态注入）
→ 渲染 9 个自包含 HTML（1 根索引 + 5 项目页 + 3 主题页）到 docs/space-build/。

设计要点：
- 纯标准库，不依赖网络；经 scripts/run_env.sh 调用（固化 TZ + managed python）。
- 产物零外链图片（满足资料库 page 导入图片托管闸门）。
- 图片闸门自检：生成后 grep 断言无第三方 <img src>/srcset，违例非零退出。
- 同步自动化每周重跑本脚本，再经资料库技能按 node-block-id 整体覆盖各页（URL 稳定）。

用法：
  bash scripts/run_env.sh scripts/gen_space_docs.py
"""
import os
import re
import sys
import json
import html
import sqlite3

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(REPO, "docs", "space-build")
DB = os.path.expanduser("~/.workbuddy/workbuddy.db")

# ---------------------------------------------------------------------------
# 1) 自动化注册表（从 DB 动态注入；DB 读不到时回退静态清单）
# ---------------------------------------------------------------------------
AUTO_IDS = {
    "金融分析报告": ["1786178221229", "1786114300129", "1785509026608",
                   "1785509026673", "1785424522347", "1786203745042", "1786291286955"],
}
# 静态 fallback：id -> (名称, 触发, 核心产出)
AUTO_STATIC = {
    "1786178221229": ("周日动态调仓", "仅周日 20:00", "选 1~2 金股 → data/watch_picks.json → update_watchlist.py 重写清单"),
    "1786114300129": ("周一宏观情绪雷达", "仅周一 08:00", "五档情绪 → data/weekend_sentiment_YYYYMMDD.json"),
    "1785509026608": ("盘前战略预案", "每交易日 08:30", "读 state + 情绪 → 开盘竞价方案 → 盘前战略预案 + pre_market_state"),
    "1785509026673": ("午间纠偏预警", "每交易日 12:00", "破位预警 + 尾盘竞价方案 → 午间纠偏预警"),
    "1785424522347": ("盘后量化分析", "每交易日 18:00", "采集 + 信号 → strategy_state + 复盘胜率 + 主力建仓/减仓标记"),
    "1786203745042": ("AI HOT 晨报", "每日 08:30", "AI 资讯晨报（辅助 live）"),
    "1786291286955": ("工作空间整理", "周日 00:00", "工作空间整理（辅助 live）"),
    "1785945200043": ("aquant 盘后信号监控", "工作日 15:30", "盘后信号监控 → 金融量化报告/盘后信号监控-YYYYMMDD.md"),
}


def load_autos():
    out = {}
    try:
        c = sqlite3.connect(DB)
        cur = c.cursor()
        cur.execute(
            "SELECT id,name,status,rrule,cwds,model_id,schedule_type "
            "FROM automations WHERE deleted_at IS NULL")
        for r in cur.fetchall():
            out[r[0]] = {
                "name": r[1], "status": r[2], "rrule": r[3],
                "cwds": r[4], "model": r[5], "schedule_type": r[6],
            }
        c.close()
    except Exception as e:  # 读不到 DB 时静默回退静态清单
        sys.stderr.write("WARN: workbuddy.db 读取失败，回退静态清单: %s\n" % e)
    return out


def auto_rows(auto_ids, db):
    rows = []
    for aid in auto_ids:
        if aid in db:
            d = db[aid]
            name = d.get("name") or AUTO_STATIC.get(aid, ("?", "", ""))[0]
            trig = d.get("rrule") or ("once" if d.get("schedule_type") == "once" else "")
            desc = ""
        else:
            name, trig, desc = AUTO_STATIC.get(aid, (aid, "", ""))
        rows.append((html.escape(aid), html.escape(name),
                     html.escape(trig or "—"), html.escape(desc or "—")))
    if not rows:
        rows = [("—", "无独立自动化", "—", "由专家 / 手动驱动，复用本工程 watchlist 与脚本")]
    return rows


# ---------------------------------------------------------------------------
# 2) 项目策展内容
# ---------------------------------------------------------------------------
PROJECTS = [
    {
        "key": "proj_fin_analysis", "title": "金融分析报告",
        "subtitle": "三时段量化分析自动化 · 策略闭环 v2.5 + 工程化（中枢项目）",
        "background": "本工程是 5 套 WorkBuddy 自动化（周日调仓 / 周一情绪 / 盘前 / 午间 / 盘后）驱动的中枢仓库。按交易日采集 A股/ETF 行情，生成盘前战略预案、午间纠偏预警、盘后量化分析等行政研报级 Markdown 报告并上传腾讯文档。标的范围来自 config/watchlist.json（v5，16 只）。多个下游项目（股票分析专家团、股票研究专家、aquant）复用其 watchlist 与交易日历作为单一数据源。",
        "arch": (
            "        config/watchlist.json (v5, 16只)\n"
            "                │  (单一数据源)\n"
            "                ▼\n"
            "   ┌───────────────────────────────────────────┐\n"
            "   │ 周日调仓 → 周一情绪 → 盘前 → 午间 → 盘后      │  (5 套自动化闭环)\n"
            "   └───────────────────────────────────────────┘\n"
            "        │                          │\n"
            "   pre_market_state.json      strategy_state.json\n"
            "        │                          │\n"
            "   腾讯文档上传 ←── reports/*.md ←──┘\n"
        ),
        "modules": [
            ("init_check.sh", "公共前置：时区锚定 + 周末/周一/周日/交易日闸门 + 离线比对本地交易日历。"),
            ("update_watchlist.py", "周日调仓调用，安全合并金股到 watchlist；含创业板 BLOCKED_BOARDS 硬门禁（300/301 禁入，违规 exit 2）。"),
            ("write_state.py", "JSON 唯一落盘口：json.load 校验 + 必需字段 + 原子写(mkstemp+os.replace) + 维护 strategy_state_latest.json 软链接。"),
            ("staleness_guard.py", "数据源 STALE 检测：算 state 距今日交易日数 N，N>5 输出 CIRCUIT_BREAKER_ACTIVE 并 exit 2。"),
            ("akshare_close.py", "AkShare 历史日线严格收盘价（15:05 收盘闸门防快照价冒充收盘）。"),
            ("gen_calendar.py", "生成 trading_calendar_YYYY.txt（上交所公告离线休市清单）。"),
            ("vwap_bias.py", "VWAP 量价双因子清洗：主力净流入方向 × 收盘相对 VWAP 位置，修正资金流判定。"),
            ("rotate_data.sh", "轮转 data/（mtime>30 删，白名单保留 watch_picks/首份 state）。"),
            ("backup.sh", "三层冷备：本地 mirror + 离线 bundle + GitHub 云端（须 Mac 终端跑）。"),
            ("run_env.sh", "统一运行时网关：固化 TZ、cd 工程根、自动为 *.py 前缀 managed python。"),
        ],
        "configs": [
            ("config/watchlist.json", "v5，16 只（9 ETF + 7 个股）；字段 source=manual/auto；创业板 300/301 受 BLOCKED_BOARDS 门禁。"),
            ("config/trading_calendar_2026/2027.txt", "离线休市清单，init_check.sh 比对判定是否交易日（沙箱禁联网）。"),
            ("docs/report_format_spec.md", "排版单一事实源：行政研报级 5 强制规则 + 5 模板 + 零裸 HTML 防御。"),
            (".gitignore", "忽略每日状态 JSON（strategy_state_*/pre_market_state_*/watchlist_degraded.json）。"),
        ],
        "deps": "watchlist.json 与交易日历为项目内部单一数据源（项目外复用由外部工程自行加载，不在本中心维护）。",
        "notes": "沙箱代理拦截 eastmoney/github，AkShare/爬虫须在 Mac 本机跑，脚本自动降级标注「🔴数据缺失」不阻塞；报告顶部对 STALE 数据源必🔴标注。",
        "auto_ids": AUTO_IDS["金融分析报告"],
    },
]

# ---------------------------------------------------------------------------
# 3) 主题页内容
# ---------------------------------------------------------------------------
THEME_ARCH = {
    "key": "theme_architecture", "title": "统一架构与数据流",
    "body": """
<p>本中心仅聚焦 <b>金融分析报告</b> 项目本身，不再承载其它消费端项目文档：</p>
<pre>config/watchlist.json (v5, 16只)  ──┐
config/trading_calendar_*.txt      ──┤ 单一数据源（离线，沙箱禁联网）
docs/report_format_spec.md         ──┘
        │
        └─▶ 金融分析报告（5 套自动化闭环：采集→盘前→午间→盘后→调仓）
                产出 reports/*.md + strategy_state / pre_market_state JSON</pre>
<p><b>关键约束</b>：① watchlist.json / 交易日历为唯一权威；② 创业板 300/301 段受 BLOCKED_BOARDS 硬门禁（仅 auto 标的影响，manual 不受限）；③ 沙箱代理拦截 eastmoney/github，AkShare/爬虫与 GitHub push 须在本机 Mac 终端执行。</p>
""",
}

THEME_CONFIG = {
    "key": "theme_config", "title": "关键配置参考",
    "body": """
<h3>① config/watchlist.json（v5）</h3>
<table>
<tr><th>字段</th><th>说明</th></tr>
<tr><td>code / name</td><td>标的代码（沪 600/601/603/605，深 000/001/002/003；ETF 全 manual）、名称</td></tr>
<tr><td>source</td><td>manual（不受门禁）/ auto（受 BLOCKED_BOARDS 创业板门禁约束）</td></tr>
<tr><td>BLOCKED_BOARDS</td><td>update_watchlist.py 内置：命中 300/301 段 exit 2 不写文件（仅约束 auto 标的）</td></tr>
</table>
<h3>② config/trading_calendar_YYYY.txt</h3>
<p>上交所公告离线休市清单（纯「闭市日清单 + DOW 周末」覆盖全休市，2026 无调休开市周末）。init_check.sh §4 比对判定交易日，替代 LLM 节假日联网判断。</p>
<h3>③ docs/report_format_spec.md（排版单一事实源）</h3>
<table>
<tr><th>规则</th><th>要点</th></tr>
<tr><td>① 首部摘要块</td><td>报告开头用 <code>&gt;</code> 引用块给出一句话结论</td></tr>
<tr><td>② 层级 + 表格优先</td><td>emoji 序号 + 表格，少长段落</td></tr>
<tr><td>③ 操作方向纯文字</td><td>买入/卖出/观望 一律纯文字，禁 🔒/红绿着色/HTML span</td></tr>
<tr><td>④ 北京时间戳</td><td>所有时间标注 Asia/Shanghai</td></tr>
<tr><td>⑤ 零裸 HTML 防御</td><td>禁裸 HTML 标签（防腾讯文档 12977）；文本进度条用 Unicode 方块字符且禁代码围栏包裹</td></tr>
</table>
""",
}


# ---------------------------------------------------------------------------
# 4) HTML 渲染辅助
# ---------------------------------------------------------------------------
CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       color: #1f2329; background: #fff; line-height: 1.7; margin: 0; padding: 32px 40px; max-width: 960px; }
h1 { font-size: 26px; border-bottom: 3px solid #2b6cb0; padding-bottom: 10px; color: #1a365d; }
h2 { font-size: 19px; margin-top: 30px; color: #2b6cb0; border-left: 4px solid #2b6cb0; padding-left: 10px; }
h3 { font-size: 16px; color: #2c5282; margin-top: 22px; }
p { margin: 10px 0; }
.subtitle { color: #5a6b7b; font-size: 14px; margin-top: -6px; }
pre { background: #f4f6f8; border: 1px solid #e1e6eb; border-radius: 6px;
      padding: 14px 16px; overflow-x: auto; font-size: 12.5px; line-height: 1.5; color: #243b53; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13.5px; }
th, td { border: 1px solid #dbe1e8; padding: 8px 10px; text-align: left; vertical-align: top; }
th { background: #eef3f8; color: #1a365d; font-weight: 600; }
tr:nth-child(even) td { background: #fafbfc; }
code { background: #f0f2f5; padding: 1px 5px; border-radius: 4px; font-size: 12.5px; }
ul { margin: 10px 0; padding-left: 22px; }
.note { background: #fff8e6; border: 1px solid #ffe1a8; border-radius: 6px; padding: 10px 14px; margin: 12px 0; }
.tag { display: inline-block; background: #eef3f8; color: #2b6cb0; border-radius: 4px; padding: 2px 8px; font-size: 12px; margin-right: 6px; }
"""


def esc(s):
    return html.escape(str(s))


def table(headers, rows):
    h = "".join("<th>%s</th>" % esc(h) for h in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join("<td>%s</td>" % c for c in r) + "</tr>"
    return "<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (h, body)


def render_project(p, db):
    rows_mod = [(esc(n), esc(d)) for n, d in p["modules"]]
    rows_cfg = [(esc(n), esc(d)) for n, d in p["configs"]]
    rows_auto = auto_rows(p["auto_ids"], db)
    sections = []
    sections.append("<p class='subtitle'>%s</p>" % esc(p["subtitle"]))
    sections.append("<h2>一、项目背景与定位</h2><p>%s</p>" % esc(p["background"]))
    sections.append("<h2>二、系统架构</h2><pre>%s</pre>" % esc(p["arch"]))
    sections.append("<h2>三、模块 / 脚本说明</h2>" + table(["模块 / 文件", "说明"], rows_mod))
    sections.append("<h2>四、关键配置</h2>" + table(["配置项", "说明"], rows_cfg))
    sections.append("<h2>五、自动化任务</h2>" + table(
        ["自动化 ID", "名称", "触发", "核心产出"], rows_auto))
    sections.append("<h2>六、数据流 / 依赖</h2><p>%s</p>" % esc(p["deps"]))
    sections.append("<div class='note'><b>⚠️ 当前状态与注意事项：</b> %s</div>" % esc(p["notes"]))
    return page_shell(p["title"], "\n".join(sections))


def render_theme(t):
    return page_shell(t["title"], "<p class='subtitle'>跨项目主题索引</p>" + t["body"])


def page_shell(title, body):
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>%s</title><style>%s</style></head><body>"
        "<h1>%s</h1>%s</body></html>" % (esc(title), CSS, esc(title), body)
    )


def _docmap_url(docmap, key):
    """从 doc map 取某页的访问 URL（无则返回空串）。"""
    try:
        return (docmap or {}).get("pages", {}).get(key, {}).get("url", "") or ""
    except Exception:
        return ""


def _link(docmap, key, title):
    u = _docmap_url(docmap, key)
    if u:
        return "<a href='%s'>%s</a>" % (esc(u), esc(title))
    return esc(title)


def render_index(themes, docmap=None):
    items = "".join(
        "<li><span class='tag'>项目</span> <b>%s</b> — %s</li>" % (_link(docmap, p["key"], p["title"]), esc(p["subtitle"]))
        for p in PROJECTS)
    tlist = "".join(
        "<li><span class='tag'>主题</span> <b>%s</b> — 跨项目通用参考</li>" % _link(docmap, t["key"], t["title"])
        for t in themes)
    body = (
        "<p class='subtitle'>资料库·我的文档 / 股票项目文档中心</p>"
        "<p>本中心仅聚焦「金融分析报告」项目的结构化文档，按项目与主题双维度组织。各文档作为本页的子节点挂载于资料库目录树，可直接在资料库内逐层展开浏览。</p>"
        "<h2>项目页</h2><ul>%s</ul>"
        "<h2>主题页</h2><ul>%s</ul>"
        "<div class='note'>文档由自动化「股票项目文档周同步」每周日 21:00 全量重建并整体覆盖，随项目状态保持同步。人工无需维护。</div>"
    ) % (items, tlist)
    return page_shell("股票项目文档中心", body)


# ---------------------------------------------------------------------------
# 5) 图片闸门自检
# ---------------------------------------------------------------------------
def image_gate_ok(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read()
    except Exception:
        return True  # 读不到不阻塞，交由 import 阶段报错
    # 仅检查 <img> 标签内的第三方外链（不含平台内链 codebuddy/workbuddy）
    for m in re.finditer(r"<img[^>]*>", txt, re.I):
        tag = m.group(0)
        for attr in re.findall(r"(?:src|srcset)\s*=\s*[\"']([^\"']+)", tag, re.I):
            if re.match(r"https?://", attr) and not re.search(r"codebuddy|workbuddy", attr):
                return False
    return True


# ---------------------------------------------------------------------------
# 6) main
# ---------------------------------------------------------------------------
def main():
    db = load_autos()
    os.makedirs(BUILD, exist_ok=True)

    # 读取文档节点映射（若存在），用于首页对各子页生成可点击链接。
    # 首次建页时 map 尚未生成，本步静默跳过；后续周同步会自动补全链接。
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _map_path = os.path.join(_root, "docs", "library_doc_map.json")
    docmap = None
    try:
        with open(_map_path, "r", encoding="utf-8") as f:
            docmap = json.load(f)
    except Exception:
        docmap = None

    # 主题页：自动化任务清单（汇总全部相关自动化，从 DB 动态注入）
    seen = set()
    all_ids = []
    for p in PROJECTS:
        for aid in p["auto_ids"]:
            if aid not in seen:
                seen.add(aid)
                all_ids.append(aid)
    autos_body = (
        "<p>本表汇总「金融分析报告」项目的全部 WorkBuddy 自动化（运行时传完整带前缀 id，如 "
        "<code>automation-1785424522347</code>）。名称/触发来自 workbuddy.db 实时读取。</p>"
        + table(["自动化 ID（带前缀）", "名称", "触发(rrule)", "核心产出"], auto_rows(all_ids, db)))
    theme_autos = {"key": "theme_automations", "title": "自动化任务清单", "body": autos_body}

    # (文件名, 内容) 列表
    themes = [THEME_ARCH, THEME_CONFIG, theme_autos]
    pages = []
    pages.append(("index.html", render_index(themes, docmap)))
    for p in PROJECTS:
        pages.append((p["key"] + ".html", render_project(p, db)))
    for t in themes:
        pages.append((t["key"] + ".html", render_theme(t)))

    # 写入文件 + 图片闸门自检
    for fn, content in pages:
        path = os.path.join(BUILD, fn)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        if not image_gate_ok(path):
            sys.stderr.write("FAIL 图片闸门: %s 含第三方外链 img\n" % fn)
            sys.exit(2)

    # manifest（文件名 -> 标题），供初始建页参考
    titles = {"index.html": "股票项目文档中心"}
    titles.update({p["key"] + ".html": p["title"] for p in PROJECTS})
    titles.update({t["key"] + ".html": t["title"] for t in (THEME_ARCH, THEME_CONFIG)})
    with open(os.path.join(BUILD, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(titles, f, ensure_ascii=False, indent=2)

    sys.stderr.write("OK: 生成 %d 个 HTML + manifest.json 到 %s\n" % (len(pages), BUILD))
    # stdout 给调用方（自动化）一个稳定信号
    print("KS_DOCGEN_OK files=%d" % len(pages))


if __name__ == "__main__":
    main()
