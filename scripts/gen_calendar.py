#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_calendar.py — 交易日历年度自动生成（防御「次年 1-1 日历错乱」运维风险）

设计动机：原 trading_calendar_YYYY.txt 需「每年末据交易所公告手动更新」，存在人为遗忘风险。
本脚本用 akshare.tool_trade_date_hist_sina() 拉取交易日，对目标年求补集即得休市日。

⚠️ 关键约束（已实测）：tool_trade_date_hist_sina() 返回的是【历史】交易日（截至当前），
   不含未来年份。因此：
   · 对【完全过去】的年份（year < 数据最大年）：取补集 = 正确完整休市日。
   · 对【当年(部分) / 未来】年份：sina 无完整数据，无法推导法定节假日。
     此时退化为「仅含周末」的引导版（weekend-only bootstrap），并在文件头醒目标注
     「法定节假日须据交易所公告手动补全」。这能防止次年 1-1 因文件缺失而崩溃
     （周末已被 init_check.sh 的 DOW 闸门拦截，且文件存在即不会误判），但节假日
     仍需人工补全 —— 这是该数据源能做到的最佳自动化边界。

用法：
  python3 scripts/gen_calendar.py                 # 生成明年（引导版，周末+警告）
  python3 scripts/gen_calendar.py --year 2025     # 生成完全过去的年（补集，正确）
  python3 scripts/gen_calendar.py --dry-run       # 仅打印，不写文件
依赖：akshare（装于托管 venv）；网络可达 sina（finance.sina.com.cn）。
"""
import argparse
import os
import sys
from datetime import date, timedelta


def fetch_all_trade_dates():
    """返回全部历史交易日集合（datetime.date 对象）。

    任何失败（akshare 未装 / 网络不可达 / 接口异常）均返回空集，
    交由 derive() 退化为 bootstrap（仅周末）模式，绝不因网络问题使脚本崩溃。
    """
    try:
        import akshare as ak
    except Exception:
        sys.stderr.write("⚠️ akshare 未安装，跳过历史比对，仅生成周末引导版。\n")
        return set()
    try:
        df = ak.tool_trade_date_hist_sina()
    except Exception as e:
        sys.stderr.write(f"⚠️ sina 交易日历拉取失败（{e}），仅生成周末引导版。\n")
        return set()
    s = set()
    for v in df["trade_date"].tolist():
        if hasattr(v, "date"):          # pandas Timestamp
            v = v.date()
        s.add(v)
    return s


def year_dates(year):
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def derive(year, all_trade):
    """
    返回 (non_trading_days, mode)。
    - 完全过去的年（且能取到该年交易日）-> mode='complement'（正确完整补集）
    - 当年(部分)/未来年 / 无历史数据 -> mode='bootstrap'（仅周末 + 警告）
    """
    if all_trade:
        ytrade = {d for d in all_trade if d.year == year}
        max_year = max(d.year for d in all_trade)
        if year < max_year and ytrade:
            non = [d for d in year_dates(year) if d not in ytrade]
            return non, "complement"
    non = [d for d in year_dates(year) if d.weekday() >= 5]
    return non, "bootstrap"


HEADER_BASE = [
    "# A 股 {year} 年休市日清单（本地交易日历，离线硬逻辑）",
    "# 数据来源：新浪财经交易日历 tool_trade_date_hist_sina() 自动推导（补集）",
    "# 用途：init_check.sh 在 bash 层离线比对，替代 LLM 查 sh000001 的脆弱判断。",
    "# 格式：每行一个 YYYY-MM-DD；含法定节假日及邻接周末闭市日。",
]
HEADER_BOOTSTRAP_NOTE = (
    "# ⚠️ 自动引导版：sina 仅返回历史交易日（不含未来/当年完整数据），本文件【仅含周末】。\n"
    "# 法定节假日须据上交所/深交所次年公告手动补全，否则节假日会被误判为交易日。"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=None, help="目标年（默认明年）")
    ap.add_argument("--out", default=None, help="输出路径（默认 ../config/trading_calendar_YYYY.txt）")
    ap.add_argument("--dry-run", action="store_true", help="仅打印，不写文件")
    ap.add_argument("--force", action="store_true",
                    help="强制覆盖；默认会跳过已被手动补全（无引导版标记）的既有文件")
    args = ap.parse_args()

    year = args.year or (date.today().year + 1)
    all_trade = fetch_all_trade_dates()
    non, mode = derive(year, all_trade)

    if mode == "bootstrap":
        if all_trade:
            max_year = max(d.year for d in all_trade)
            sys.stderr.write(
                f"⚠️ 警告：sina 仅返回历史交易日（截至 {max_year} 年），无法推导 {year} 年完整休市日。\n"
                f"   已生成【仅含周末】的引导版；法定节假日须据交易所公告手动补全。\n"
            )
        else:
            sys.stderr.write(
                f"⚠️ 警告：未能获取 sina 历史交易日，已生成【仅含周末】的引导版；\n"
                f"   法定节假日须据交易所公告手动补全。\n"
            )

    print(f"目标年 {year} | 模式={mode} | 休市日条数={len(non)}")
    lines = [h.format(year=year) for h in HEADER_BASE]
    if mode == "bootstrap":
        lines.append(HEADER_BOOTSTRAP_NOTE)
    lines += [d.strftime("%Y-%m-%d") for d in non]
    content = "\n".join(lines) + "\n"

    if args.dry_run:
        print(content)
        return 0

    if args.out:
        out = os.path.abspath(args.out)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
        out = os.path.abspath(os.path.join(base, "..", "config", f"trading_calendar_{year}.txt"))

    # 安全闸：若目标文件已存在且已被手动补全（不含「自动引导版」标记），
    # 默认跳过覆盖，避免每年 12-20 自动化把用户手填的法定节假日冲掉。
    if os.path.exists(out) and not args.force:
        try:
            with open(out, "r", encoding="utf-8") as f:
                existing = f.read()
        except Exception:
            existing = ""
        if "自动引导版" not in existing:
            print(
                f"⏭️  跳过：{out} 已存在且已手动补全（无引导版标记），"
                f"不覆盖以保护人工添加的法定节假日。如需强制重建请加 --force。"
            )
            return 0

    with open(out, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ 已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
