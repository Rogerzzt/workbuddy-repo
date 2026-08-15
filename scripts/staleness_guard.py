#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
staleness_guard.py — 策略状态陈旧度硬熔断预检（防御性，确定性判定）

设计动机（对齐架构论点：系统安全不应建立在 LLM 100% 遵循指令的假设上）：
盘前任务(01)继承 data/strategy_state_*.json 作为策略基准。若盘后/爬虫静默崩溃长达一周，
系统会无感继承一周前的点位。本脚本以确定性方式计算「基准距今日 N 个交易日」，
当 N > 阈值（默认 5）时输出 CIRCUIT_BREAKER_ACTIVE，供 01 prompt 强制将 A 级买入动作降级为观望。

用法（由 01 prompt 指示 LLM 在读取状态前先运行）：
  python3 scripts/staleness_guard.py [--state-dir data] [--threshold 5]

输出：
  LATEST_STATE_DATE=YYYYMMDD        （最新状态文件日期；无则 NO_STATE_FILE）
  STALENESS_TRADING_DAYS=N          （基准距今日 N 个交易日）
  CIRCUIT_BREAKER_ACTIVE            （仅当 N > threshold 时打印；脚本 exit 2）
退出码：0=正常；2=触发熔断；1=异常。
"""
import argparse
import glob
import os
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ_BJ = ZoneInfo("Asia/Shanghai")
STATE_RE = re.compile(r"strategy_state_(\d{8})\.json$")

# 缓存每年休市日集合，避免重复读文件
_CAL_CACHE = {}


def _load_calendar(year: int, ws: str):
    if year in _CAL_CACHE:
        return _CAL_CACHE[year]
    cal_path = os.path.join(ws, "config", f"trading_calendar_{year}.txt")
    s = set()
    if os.path.isfile(cal_path):
        with open(cal_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # 兼容 "YYYY-MM-DD" 或 "MM-DD" 两种写法
                try:
                    if len(line) == 10:
                        s.add(date.fromisoformat(line))
                    elif len(line) == 5:
                        s.add(date(year, int(line[:2]), int(line[3:5])))
                except ValueError:
                    continue
    _CAL_CACHE[year] = s
    return s


def is_trading_day(d: date, ws: str) -> bool:
    if d.weekday() >= 5:          # 周六/周日
        return False
    cal = _load_calendar(d.year, ws)
    return d not in cal


def find_latest_state(state_dir: str):
    # D4b：优先读 strategy_state_latest.json 软链接（write_state.py 维护，指向最新日期文件）。
    #      软链接存在且指向合法日期文件时直接采用，避免 glob+max 扫描的命名漂移隐患。
    latest_link = os.path.join(state_dir, "strategy_state_latest.json")
    if os.path.islink(latest_link) or os.path.lexists(latest_link):
        target = os.path.realpath(latest_link)
        m = STATE_RE.search(os.path.basename(target))
        if m and os.path.exists(target):
            dt = datetime.strptime(m.group(1), "%Y%m%d").date()
            return dt, target
    # 回退：glob + max（向后兼容，无软链接 / 软链接损坏时仍可用）。
    #      注意 strategy_state_latest.json 本身不匹配 STATE_RE(\d{8})，会被自然跳过。
    best = None
    best_dt = None
    for p in glob.glob(os.path.join(state_dir, "strategy_state_*.json")):
        m = STATE_RE.search(os.path.basename(p))
        if not m:
            continue
        dt = datetime.strptime(m.group(1), "%Y%m%d").date()
        if best_dt is None or dt > best_dt:
            best_dt, best = dt, p
    return best_dt, best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="data", help="strategy_state_*.json 所在目录")
    ap.add_argument("--threshold", type=int, default=5, help="熔断阈值（交易日数），默认 5")
    args = ap.parse_args()

    ws = os.environ.get("AQUANT_WORKSPACE", os.getcwd())
    state_dt, state_path = find_latest_state(args.state_dir)
    if state_dt is None:
        print("LATEST_STATE_DATE=NO_STATE_FILE")
        print("STALENESS_TRADING_DAYS=N/A")
        return 0

    print(f"LATEST_STATE_DATE={state_dt.strftime('%Y%m%d')}")

    today = datetime.now(TZ_BJ).date()
    # N = (state_date, today] 之间的交易日数（即「距今日 N 个交易日」）
    n = 0
    d = state_dt + timedelta(days=1)
    while d <= today:
        if is_trading_day(d, ws):
            n += 1
        d += timedelta(days=1)

    print(f"STALENESS_TRADING_DAYS={n}")

    if n > args.threshold:
        print(f"CIRCUIT_BREAKER_ACTIVE  (基准过期 {n} 个交易日 > 阈值 {args.threshold})")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
