# 量化自动化系统 · 残余短板补丁（4 项修复）实施纪实

> 文档版本：v1.0 · 落地日期：2026-08-15
> 适用系统：三时段量化分析自动化（策略闭环 v2.5 + 工程化）
> 唯一事实源：本文件覆盖 4 项修复的设计裁决、实施细节与运维要点；prompt / 脚本以代码仓库为准。

---

## 一、背景与范围

系统主体已达工业级，但遗留 4 个边角隐患。本文档是在「终极补丁方案」基础上，经方案评估（合理性 / 可行性 / 风险）后落地的完整记录。

| # | 隐患 | 原方案 | 最终裁决 |
|---|------|--------|---------|
| 1 | 节假日检查仍依赖 LLM 调连接器查 sh000001 | bash 内 `curl` 东财 | **否决 curl，改用本地交易日历**（离线硬逻辑） |
| 2 | LLM 生成 Python 写 JSON 的引号转义风险 | 避免 LLM 写 Python | **接受，优化为固化 CLI `write_state.py`** |
| 3 | 缺乏历史数据轮转与清理 | `find -mtime +30` 删除 | **接受，加护栏（`rotate_data.sh` + 移出 git）** |
| 4 | `backup.sh` bundle 冷备原子性缺失 | 先 `rm` 再 `create` | **接受，增强为 tmp→verify→prev→mv** |

范围限定于：脚本与配置（`scripts/`、`config/`）、`prompts/*.md` 审计副本与 `~/.workbuddy/workbuddy.db` 内联 prompt、`.gitignore`、本工程化文档。不涉及交易策略逻辑改动。

---

## 二、四项问题逐一定性

### 2.1 修复1 — 节假日判断从「LLM 脆弱判断」下沉为「bash 本地日历」

- **问题**：原方案依赖 LLM 在 prompt 内调连接器判断当日是否交易日；节假日（尤其落在周一的元旦/春节）极易误判为交易日，导致无效任务运行、token 浪费、甚至错误报告。
- **风险（原 curl 方案）**：① 沙箱 egress 硬限制——自动化 bash 上下文 `HTTP_PROXY/HTTPS_PROXY=127.0.0.1:64657`，对 eastmoney 任意方式（curl / urllib / `proxies=None`）均 `RemoteDisconnected`（已精确诊断），curl 必败 → 节假日被误判为交易日，比 LLM 版本更糟；② 时间守卫 `[H%M -ge 0930]` 会让 08:30 盘前 / 12:00 午间在节假日**误放行**（H%M < 0930 不触发跳过）。
- **裁决**：**否决 curl，改用本地交易日历**。零网络、零 token、全时段正确，覆盖全部休市（2026 无调休开市周末）。

### 2.2 修复2 — JSON 落盘从「LLM 内联 Python」改为「固化 CLI 校验 + 原子写」

- **问题**：盘前/盘后要求 LLM 在终端拼 Python 写 JSON，`trigger_condition` 等字段一旦含未转义引号即 `SyntaxError` / `JSONDecodeError`，切断「盘前→午间」状态机闭环。
- **风险**：仅 `cat <<'EOF'` 只解决 shell 转义，不解决 **JSON 合法性**。
- **裁决**：**接受并优化**。LLM 用 Write 工具写 JSON 文件 → 固化 `write_state.py` 做 `json.load` 校验 + 必需字段检查 + `tempfile.mkstemp` + `os.replace` 原子落盘；非零退出必须重写直至通过。

### 2.3 修复3 — 数据轮转（含 git 移出）

- **问题**：长年运行后 `data/` 与项目根被过期状态/报告淹没，拖慢 Git 追踪、耗尽沙箱配额。
- **风险（原命令）**：`find data -name '*.json' -mtime +30` 过宽，会误删 `watch_picks.json`、bootstrap 文件，且 git-tracked 状态 JSON 删除会污染历史。
- **裁决**：**接受，加护栏**。每日状态 JSON **移出 git**（仅本地保留 + 轮转）；`rotate_data.sh` 用显式 `--name` + `-maxdepth 1` + 白名单保护，仅删 `mtime > 30` 天文件。

### 2.4 修复4 — backup.sh bundle 冷备原子性

- **问题**：原 `rm -f "$BUNDLE"` 先于 `git bundle create`，打包中途失败即丢失健康备份。
- **风险**：冷备在异常时刻反而变成数据丢失点。
- **裁决**：**接受，增强原子性**。改为 `TMP → verify → 保留上一版(.prev) → mv`，任一环节失败不破坏现有 `$BUNDLE`。

---

## 三、实施细节（对应修复1–4）

### 3.1 修复1：本地交易日历

**新建 `config/trading_calendar_2026.txt`**（每行 `YYYY-MM-DD`，据上交所 2025-12-22 公告整理，含周末邻接闭市日）：

```
2026-01-01 ~ 01-04      # 元旦（01-04 周日）
2026-02-14 ~ 02-23      # 春节
2026-02-28              # 春节邻接周六
2026-04-04 ~ 04-06      # 清明
2026-05-01 ~ 05-05      # 劳动
2026-05-09              # 劳动邻接周六
2026-06-19 ~ 06-21      # 端午
2026-09-20              # 中秋邻接周日
2026-09-25 ~ 09-27      # 中秋
2026-10-01 ~ 10-07      # 国庆
2026-10-10              # 国庆邻接周六
```

> 2026 全年无调休开市周末，故「闭市日清单 + DOW 周末」即可完整覆盖；无需 makeup 列表。

**`scripts/init_check.sh` 第 4 节新增离线节假日比对**（所有模式通用，周末已在上一步拦截）：

```bash
# ---- 4. 法定节假日检查（本地交易日历，离线硬逻辑，所有模式通用） ----
TODAY_YMD=$(date +%Y-%m-%d)
CAL_YEAR=$(date +%Y)
CAL="$WS/config/trading_calendar_${CAL_YEAR}.txt"
if [ -f "$CAL" ] && grep -qxF "$TODAY_YMD" "$CAL"; then
    echo "📅 今日 ($TODAY_YMD) 为法定休市日，跳过。"
    exit 0
fi
```

**prompt 改动（00–04）**：01/02/03 删除整段「闸门二（节假日检查，需 LLM 调连接器）」；5 个 prompt 更新调度注释「周末与法定节假日由 `init_check.sh` bash 层拦截，无需 LLM」；00/04 步骤 0 措辞同步为「脚本已比对本地交易日历 `config/trading_calendar_YYYY.txt` 拦截法定节假日」。

### 3.2 修复2：固化 `write_state.py`（JSON 唯一落盘口）

**新建 `scripts/write_state.py`**（Python 标准库，零依赖）：

```python
# 关键路径（完整见仓库）
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--out", dest="outfile", required=True)
    ap.add_argument("--required", default="", help="顶层必需字段，逗号分隔")
    ap.add_argument("--no-cleanup", action="store_true")
    args = ap.parse_args()

    raw = open(args.infile, encoding="utf-8").read()
    try:
        data = json.loads(raw)            # ① 校验合法 JSON
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析失败：{e}", file=sys.stderr); return 3

    req = [x.strip() for x in args.required.split(",") if x.strip()]
    missing = [k for k in req if k not in data]
    if missing:
        print(f"❌ 缺少必需字段：{missing}", file=sys.stderr); return 5

    fd, tmp = tempfile.mkstemp(dir=out_dir, suffix=".tmp", prefix=".wstate_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, args.outfile)         # ② 原子落盘（防断电清空）

    json.load(open(args.outfile, encoding="utf-8"))  # ③ 回读自检
    print(f"✅ 状态已校验并原子落盘: {args.outfile}"); return 0
```

退出码语义：`2`=读入失败，`3`=JSON 非法，`4`=非 dict，`5`=缺字段，`6`=落盘失败，`7`=回读失败，`0`=成功。

**prompt 改动（01 步骤 6b、03 步骤 7/8/9）**：删除内联 Python 代码块，改为「① Write 工具写纯 JSON 临时文件 `data/.tmp_pre_market_state_YYYYMMDD.json` → ② `scripts/write_state.py --in <tmp> --out <target> --required <fields>` → ③ 非零退出必须重写」。

### 3.3 修复3：数据轮转 + git 移出

**新建 `scripts/rotate_data.sh`**（幂等、本地、沙箱安全）：

```bash
KEEP_DAYS="${KEEP_DAYS:-30}"
PROTECT_GLOB=("data/watch_picks.json" "data/strategy_state_20260806.json")  # 白名单

# 1) 每日状态 JSON（data/ 顶层，仅删 >30 天）
find data -maxdepth 1 -type f \( \
    -name 'strategy_state_*.json' -o -name 'pre_market_state_*.json' \
    -o -name 'weekend_sentiment_*.json' -o -name '_signals_*.json' \) \
    -mtime +"$KEEP_DAYS" -print0 | while IFS= read -r -d '' f; do
  should_keep "$f" || { echo "  🗑 $f"; rm -f "$f"; }
done

# 2) 爬虫原始 JSON（data/pre、data/post）
# 3) 项目根每日报告（盘前*/午间*/盘后*/周一宏观*/周日热门调仓*.md、*.html）
```

**`.gitignore` 调整**（每日状态 JSON 移出 git）：新增忽略
`data/strategy_state_*.json`、`data/pre_market_state_*.json`、`data/weekend_sentiment_*.json`、`data/_signals_*.json`、`workbuddy-repo/`，并删除原「保留纳入版本控制」注释；已跟踪文件用 `git rm --cached` 解除跟踪（保留本地）。

**调用点**：prompt 03 步骤 9 末尾追加 `bash scripts/rotate_data.sh`（03 为每日最后运行，幂等）。

### 3.4 修复4：backup.sh 原子性增强

**`scripts/backup.sh` bundle 段**：

```bash
BUNDLE="$BAK/fin-analysis-$(date +%Y%m%d).bundle"
TMP_BUNDLE="${BUNDLE}.tmp"
rm -f "$TMP_BUNDLE"
git bundle create "$TMP_BUNDLE" --all
if git bundle verify "$TMP_BUNDLE" >/dev/null 2>&1; then
    [ -f "$BUNDLE" ] && mv -f "$BUNDLE" "${BUNDLE}.prev"   # 保留上一版健康备份
    mv -f "$TMP_BUNDLE" "$BUNDLE"
    echo "    bundle 校验通过: $BUNDLE"
else
    echo "    ❌ bundle 校验失败，保留旧备份: $BUNDLE" >&2
    rm -f "$TMP_BUNDLE"; exit 1
fi
```

---

## 四、沙箱 egress 注意事项（强制）

> **自动化 bash 上下文禁止任何联网探测 eastmoney。**

- WorkBuddy 沙箱内 `HTTP_PROXY/HTTPS_PROXY=127.0.0.1:64657`，对 eastmoney 任意方式（curl / urllib / `proxies=None` / `verify=False`）均 `RemoteDisconnected`（TCP `connect()` 成功但 TLS 层被重置）。
- 因此：**节假日判断必须离线化**（本地交易日历，见 3.1）；AkShare 取东财历史日线同样无法在沙箱出数，须在本机 Mac 终端运行（`scripts/akshare_close.py` 已内置 15:05 收盘闸门）。
- AkShare 依赖坑（本机）：`urllib3` 须 `<2`（1.26.20），v2 + macOS LibreSSL 2.8.3 会因 `NotOpenSSLWarning` 致 TLS 失败 → 0/16；降级后本机正常。
- `backup.sh` 第三步 `git push origin main` 同样被沙箱代理拦截，**须在 Mac 本机终端运行**（见第十一节）。

---

## 附录 A：2026 全年 A 股休市日（写入 `config/trading_calendar_2026.txt`）

数据来源：上海证券交易所 2025-12-22 公告（上证公告〔2025〕45号）。完整逐日清单（含周末邻接）：

```
01-01,01-02,01-03,01-04,
02-14,02-15,02-16,02-17,02-18,02-19,02-20,02-21,02-22,02-23,02-28,
04-04,04-05,04-06,
05-01,05-02,05-03,05-04,05-05,05-09,
06-19,06-20,06-21,
09-20,09-25,09-26,09-27,
10-01,10-02,10-03,10-04,10-05,10-06,10-07,10-10
```

其余周六/周日由 `init_check.sh` 的 DOW 判断自动覆盖；2026 无调休开市周末。

---

## 附录 B：`write_state.py` 用法

```bash
# 盘前（prompt 01 步骤 6b）
python3 scripts/write_state.py \
  --in  data/.tmp_pre_market_state_YYYYMMDD.json \
  --out data/pre_market_state_YYYYMMDD.json \
  --required date,positions

# 盘后（prompt 03 步骤 7 / 步骤 8）
python3 scripts/write_state.py \
  --in  data/.tmp_strategy_state_YYYYMMDD.json \
  --out data/strategy_state_YYYYMMDD.json \
  --required date,triggered_tickers
```

- 入参：`--in`（LLM 写出的纯 JSON 文件）、`--out`（目标落盘路径）、`--required`（逗号分隔顶层必需字段）、`--no-cleanup`（成功不删临时文件）。
- 行为：`json.load` 校验 → 必需字段检查 → 原子写（`mkstemp`+`os.replace`）→ 回读自检。
- 退出码：非零即失败（见 3.2），LLM 须重写临时文件直至 `0`。

---

## 附录 C：`rotate_data.sh` 用法

```bash
bash scripts/rotate_data.sh            # 默认保留 30 天
KEEP_DAYS=60 bash scripts/rotate_data.sh   # 自定义保留天数
```

- 作用域：`data/strategy_state_*.json`、`data/pre_market_state_*.json`、`data/weekend_sentiment_*.json`、`data/_signals_*.json`；`data/pre/`、`data/post/` 下 `*.json`；项目根 `盘前*.md` `午间*.md` `盘后*.md` `周一宏观情绪雷达*.md` `周日热门调仓*.md` `*.html`。
- 规则：`mtime +30` 删除；**白名单** `watch_picks.json` 与 bootstrap `strategy_state_20260806.json` 永不删。
- 调用点：盘后分析（Task 03）步骤 9 末尾（每日最后运行，幂等）。

---

## 附录 D：live 同步与提交记录

- 5 套自动化 prompt 改动均通过 `automation_update`（带前缀 id `automation-<id>`）同步至 `~/.workbuddy/workbuddy.db`；`prompts/*.md` 仅为审计副本。
- 提交按修复拆分 Conventional Commits：`refactor(scripts)` 节假日下沉、`fix(scripts)` JSON 双写、`chore(data)` 状态移出 git、`fix(backup)` bundle 原子化。
- 三层备份：`bash scripts/backup.sh`（Mac 本机终端）— 本地 bare mirror + 当日 `.bundle`（含 `.prev` 兜底）+ GitHub 云端。
