#!/usr/bin/env bash
# ============================================================================
# init_check.sh — 公共前置（全局 DRY 抽象）
# ----------------------------------------------------------------------------
# 抽走 5 个量化自动化 prompt 中 100% 重复的「目录锚定 + 周几速退」纯 bash 逻辑。
# 调用方式（由各任务 prompt 首行执行）：
#   export TZ=Asia/Shanghai
#   bash scripts/init_check.sh trading    # 交易日任务（周末速退）
#   bash scripts/init_check.sh monday     # 周末情绪任务（仅周一）
#   bash scripts/init_check.sh sunday     # 周日调仓任务（仅周日）
#
# 注意：节假日检查（腾讯自选股 MCP 查 sh000001）依赖 LLM 调连接器，无法进 bash，
#       仍保留在各任务 prompt 的「步骤 0 · 闸门二」中。
# ============================================================================
set -euo pipefail

# ---- 1. 时区强制锚定（消除机器本地时区漂移） ----
export TZ=Asia/Shanghai

# ---- 2. 目录锚定（无论调度引擎把 CWD 设到哪，强制回到项目根） ----
WS="${AQUANT_WORKSPACE:-/Users/rogerz/WorkBuddy/金融分析报告}"
cd "$WS"
[ -f config/watchlist.json ] || {
    echo "❌ 目录锚定失败：在 $(pwd) 下未找到 config/watchlist.json，请检查 AQUANT_WORKSPACE 或项目路径"
    exit 1
}
echo "📁 工作根目录已锚定: $(pwd)  (TZ=$(date +%Z))"

# ---- 3. 周几速退（纯 bash 闸门，替代各 prompt 里的 date +%u 判断） ----
DOW=$(date +%u)   # 1=Mon, 2=Tue, ... 7=Sun
MODE="${1:-trading}"
case "$MODE" in
    trading)
        [ "$DOW" -ge 6 ] && { echo "周末休市，跳过（$(date +%u)）"; exit 0; }
        ;;
    monday)
        [ "$DOW" != "1" ] && { echo "非周一，跳过（$(date +%u)）"; exit 0; }
        ;;
    sunday)
        [ "$DOW" != "7" ] && { echo "非周日，跳过（$(date +%u)）"; exit 0; }
        ;;
    *)
        echo "❌ 未知模式: $MODE（应为 trading/monday/sunday）"
        exit 2
        ;;
esac

exit 0
