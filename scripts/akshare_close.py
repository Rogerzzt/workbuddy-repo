#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
akshare_close.py — 严格收盘价采集（AkShare 后端，东方财富历史日线）

设计原则（对齐「数据红线」）：
- 仅在区间 [15:05, 次日 09:15) 内调用，方得「严格收盘价」。
  盘中调用 fund_etf_hist_em / stock_zh_a_hist 会返回当日未完成 bar 的当前价（≠收盘），
  本模块用 _enforce_post_close() 闸门强制拦截，杜绝快照价冒充收盘价。
- 解析 watchlist.json（etfs / stocks 两数组），自动判别 ETF/个股，去除 sh/sz 前缀。
- 错误分型：non_trading_day（空 df/非交易日） / no_data（停牌等无数据） / error（网络·接口）。
- 输出 JSON，供盘后任务做「四源交叉验证」的第 4 源（交易所官网 / 腾讯自选股 / 通达信 / AkShare）。

依赖：akshare（装于托管 venv：…/python/envs/default/bin/pip install akshare）；其余标准库。
"""
import argparse
import json
import os
import sys
import time
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import akshare as ak
except ImportError:
    sys.stderr.write("ERROR: akshare 未安装 -> …/python/envs/default/bin/pip install akshare\n")
    sys.exit(3)

# 强制进程级时区为北京时间（消除宿主机 TZ 漂移；与 init_check.sh 基调一致）。
# zoneinfo 本身与 TZ 无关，这里仅做全局兜底，确保任何依赖 time.localtime() 的代码也走北京时间。
os.environ["TZ"] = "Asia/Shanghai"
if os.name != "nt":
    time.tzset()

TZ_BJ = ZoneInfo("Asia/Shanghai")


def _beijing_now():
    return datetime.now(TZ_BJ)


def _enforce_post_close():
    """仅当处于「已收盘」安全窗口返回 True：15:05~23:59 或 00:00~09:15（取上一交易日）。"""
    now = _beijing_now()
    if now.weekday() >= 5:          # 周末无收盘
        return False
    if now.hour < 9 or (now.hour == 9 and now.minute < 15):
        return True                 # 夜间/凌晨：取上一交易日已定稿
    if now.hour > 15 or (now.hour == 15 and now.minute >= 5):
        return True                 # 收盘后
    return False                    # 9:15~15:05：盘中/集合竞价，严禁取价


def _strip_prefix(code: str) -> str:
    return code[2:] if code[:2].lower() in ("sh", "sz") else code


def get_strict_close(symbol: str, is_etf: bool, retries: int = 3):
    """返回 {code, close, status, detail?}；close=None 时 status 说明原因。"""
    today = _beijing_now().strftime("%Y%m%d")
    last_err = None
    for attempt in range(retries):
        try:
            if is_etf:
                df = ak.fund_etf_hist_em(symbol=symbol, period="daily",
                                         start_date=today, end_date=today)
            else:
                df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                        start_date=today, end_date=today)
            if df is None or getattr(df, "empty", True) or "收盘" not in df.columns:
                return {"code": symbol, "close": None, "status": "non_trading_day"}
            val = df["收盘"].iloc[0]
            if val is None or (isinstance(val, float) and val != val):   # NaN
                return {"code": symbol, "close": None, "status": "no_data"}
            return {"code": symbol, "close": float(val), "status": "ok"}
        except Exception as e:                       # 网络/接口异常
            last_err = str(e)
            # 指数退避：1.0 / 1.5 / 2.25 秒，封顶 6 秒，避免被东财反爬机制彻底封锁
            time.sleep(min(1.5 ** attempt, 6))
    return {"code": symbol, "close": None, "status": "error", "detail": last_err[:200]}


def load_watchlist(path):
    with open(path, encoding="utf-8") as f:
        wl = json.load(f)
    items = []
    for e in wl.get("etfs", []):
        items.append((_strip_prefix(e["code"]), True, e.get("name", "")))
    for s in wl.get("stocks", []):
        items.append((_strip_prefix(s["code"]), False, s.get("name", "")))
    return items


def _atomic_write_json(path, obj, *, indent=2):
    """原子写 JSON：先落临时文件再 os.replace，避免写入中途进程被杀/断电清空白文件。"""
    dir_name = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watchlist", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--force", action="store_true",
                    help="跳过 15:05 收盘闸门（仅调试；实盘勿开）")
    args = ap.parse_args()

    if not args.force and not _enforce_post_close():
        sys.stderr.write("WARN: 当前非收盘后窗口，严格收盘价不可信，已中止（用 --force 可强开）。\n")
        sys.exit(4)

    items = load_watchlist(args.watchlist)
    results = []
    for code, is_etf, name in items:
        r = get_strict_close(code, is_etf)
        r["name"] = name
        r["is_etf"] = is_etf
        results.append(r)
        time.sleep(0.4)                            # 节流，避免东财限流
    out = {
        "source": "akshare_eastmoney_hist",
        "fetched_at": _beijing_now().isoformat(),
        "items": results,
    }
    _atomic_write_json(args.out, out)
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"AKSHARE 严格收盘价：{ok}/{len(results)} 成功 -> {args.out}")


if __name__ == "__main__":
    main()
