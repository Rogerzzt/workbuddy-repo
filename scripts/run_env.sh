#!/usr/bin/env bash
# ============================================================================
# run_env.sh — 量化工程「统一运行时网关」
# ----------------------------------------------------------------------------
# 目的：
#   1) 固化时区（所有交易日历/收盘闸门判定依赖 Asia/Shanghai）
#   2) 用环境变量解耦 5 套 prompt / 脚本里的硬编码绝对路径
#      - AQUANT_WORKSPACE 覆盖工程根（默认本机路径）
#      - WORKBUDDY_PYTHON 覆盖 Python 解释器（默认 managed 3.13）
#   3) cd 到工程根后 exec 原命令；若首个参数为 *.py 则自动用 $WORKBUDDY_PYTHON 运行，
#      调用方只需把命令前缀加上 `bash scripts/run_env.sh` 即可，脚本路径可写相对路径。
#
# 用法（由自动化 prompt 指示 LLM 调用）：
#   bash scripts/run_env.sh scripts/staleness_guard.py --state-dir data
#   bash scripts/run_env.sh /Users/rogerz/.workbuddy/skills/cn-exchange-jisilu-scraper/scraper.py --watchlist config/watchlist.json
#   bash scripts/run_env.sh /Users/rogerz/WorkBuddy/金融量化工具/run.sh --watchlist config/watchlist.json
#   注：akshare_close.py 需专用 venv，仍用其绝对 venv 路径直接调用，仅把 watchlist 改为相对路径。
# ============================================================================
set -euo pipefail

export TZ="${TZ:-Asia/Shanghai}"
export AQUANT_WORKSPACE="${AQUANT_WORKSPACE:-/Users/rogerz/WorkBuddy/金融分析报告}"
export WORKBUDDY_PYTHON="${WORKBUDDY_PYTHON:-/Users/rogerz/.workbuddy/binaries/python/versions/3.13.12/bin/python3}"

cd "$AQUANT_WORKSPACE"

# 首个参数为 *.py 时自动用 managed python 执行；其余（如 run.sh）原样 exec
if [[ "${1:-}" == *.py ]]; then
  exec "$WORKBUDDY_PYTHON" "$@"
else
  exec "$@"
fi
