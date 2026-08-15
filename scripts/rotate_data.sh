#!/usr/bin/env bash
# ============================================================================
# rotate_data.sh — 本地数据轮转（清理过期状态/爬虫/报告文件）
# ----------------------------------------------------------------------------
# 防止长年累月运行后 data/ 与项目根被过期文件淹没、拖慢 Git 追踪、耗尽沙箱配额。
# 设计护栏：
#   - 显式 --name 模式 + -maxdepth 1，绝不误删 config/、scripts/ 或 .git
#   - 白名单：watch_picks.json 与 bootstrap 状态文件永不删
#   - 仅删 mtime > KEEP_DAYS(默认30) 的文件；近 30 天保留供复盘与人审
# 调用点：盘后分析（Task 03）步骤 9 末尾（每日最后运行，幂等）。
# ============================================================================
set -euo pipefail

export TZ="Asia/Shanghai"
WS="${AQUANT_WORKSPACE:-/Users/rogerz/WorkBuddy/金融分析报告}"
cd "$WS"

KEEP_DAYS="${KEEP_DAYS:-30}"
echo "🧹 数据轮转：删除超过 ${KEEP_DAYS} 天的过期文件（白名单受保护）..."

# 白名单保护（即便匹配到模式也不删）
PROTECT_GLOB=("data/watch_picks.json" "data/strategy_state_20260806.json")

should_keep() {
  local f="$1"
  for p in "${PROTECT_GLOB[@]}"; do
    [ "$f" = "$p" ] && return 0
  done
  return 1
}

# 1) 每日状态 JSON（data/ 顶层）
while IFS= read -r -d '' f; do
  should_keep "$f" || { echo "  🗑 $f"; rm -f "$f"; }
done < <(find data -maxdepth 1 -type f \( \
    -name 'strategy_state_*.json' -o -name 'pre_market_state_*.json' \
    -o -name 'weekend_sentiment_*.json' -o -name '_signals_*.json' \) \
    -mtime +"$KEEP_DAYS" -print0)

# 2) 爬虫原始 JSON（data/pre、data/post）
for d in data/pre data/post; do
  [ -d "$d" ] || continue
  while IFS= read -r -d '' f; do
    echo "  🗑 $f"; rm -f "$f"
  done < <(find "$d" -type f -name '*.json' -mtime +"$KEEP_DAYS" -print0)
done

# 3) 项目根每日报告（已被 .gitignore 忽略，仅清理磁盘）
while IFS= read -r -d '' f; do
  echo "  🗑 $f"; rm -f "$f"
done < <(find . -maxdepth 1 -type f \( \
    -name '盘前*.md' -o -name '午间*.md' -o -name '盘后*.md' \
    -o -name '周一宏观情绪雷达*.md' -o -name '周日热门调仓*.md' -o -name '*.html' \) \
    -mtime +"$KEEP_DAYS" -print0)

echo "✅ 轮转完成（保留最近 ${KEEP_DAYS} 天 + 白名单文件）"
