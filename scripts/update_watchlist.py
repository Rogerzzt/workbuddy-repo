#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
固化脚本：动态更新 watchlist.json（手动置顶固定 + 自动每周轮换）。

由「周日动态调仓」自动化任务调用。设计要点：
  - AI 只负责选出金股并输出 JSON 数组文件，本脚本负责执行安全的合并逻辑，
    彻底消除「大模型在终端现场生成 Python 代码」导致的缩进/JSON 错误与配置损坏风险。
  - 所有合并/校验/容错逻辑都固化在此处，可独立测试、版本化、复用。

用法：
  python3 update_watchlist.py --picks data/watch_picks.json \
      --watchlist watchlist.json

合并逻辑：
  1. 板块硬门禁：拒绝创业板标的（见 BLOCKED_BOARDS），违规直接报错退出，不写文件
  2. 兼容清洗：旧数据缺 source 字段 -> 补打 manual（向后兼容无损升级）
  3. 剥离上周 auto 标的（etfs/stocks 均处理），只保留 manual
  4. 新标的默认 type=个股、source=auto，追加到 stocks 段末尾
  5. 写回，保留 version / updated / description 等元字段
"""
import json
import os
import sys
import argparse
from datetime import date

# ============================================================
# 硬性约束：自动轮换标的（source=auto）禁止入选的板块
# ------------------------------------------------------------
# 2026-08-10 用户指令固化：每周自动更新的标的不能是创业板。
# 创业板代码段：300xxx（2009 起）、301xxx（2021 注册制后新增）。
# 本门禁只作用于 --picks 传入的自动标的；手动置顶（source=manual）
# 不受限制，用户想手动放创业板依然可以。
# 如需扩充（例如再禁科创板 688/689、北交所 8xx/43x/83x/87x/920），
# 在下面字典追加前缀即可，无需改动其他逻辑。
# ============================================================
BLOCKED_BOARDS = {
    "创业板": ("300", "301"),
}


def assert_board_allowed(picks):
    """校验自动选股结果，命中禁入板块则直接终止（硬约束，不静默过滤）。"""
    violations = []
    for it in picks:
        code = str(it.get("code", "")).strip()
        for board, prefixes in BLOCKED_BOARDS.items():
            if code.startswith(prefixes):
                violations.append((code, it.get("name", "?"), board))
    if violations:
        lines = [f"  ✗ {c} {n} → 属于{b}，禁止作为自动轮换标的"
                 for c, n, b in violations]
        raise ValueError(
            "板块硬门禁拦截，watchlist 未做任何修改：\n"
            + "\n".join(lines)
            + "\n\n请回到选股步骤，改选非创业板标的（沪市主板 600/601/603/605、"
              "深市主板 000/001/002/003）后重新执行本脚本。"
        )


def main():
    ap = argparse.ArgumentParser(
        description="动态更新 watchlist.json（手动固定 + 自动每周轮换）")
    ap.add_argument("--picks", required=True,
                    help="AI 选出的金股 JSON 数组文件，元素需含 code/name/exchange")
    ap.add_argument("--watchlist",
                    default="/Users/rogerz/WorkBuddy/金融分析报告/watchlist.json",
                    help="目标 watchlist.json 路径（默认当前项目根，调用方可覆盖为相对路径）")
    args = ap.parse_args()

    # 相对路径防御：--watchlist 若非绝对路径，统一按项目根（本脚本上级目录）解析，
    # 不依赖调用方当前工作目录（CWD），避免 CWD 漂移导致写错位置。
    if not os.path.isabs(args.watchlist):
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        args.watchlist = os.path.join(_root, args.watchlist)

    # 1. 读取 AI 选出的新标的并校验
    with open(args.picks, encoding="utf-8") as f:
        new_picks = json.load(f)
    if not isinstance(new_picks, list):
        raise ValueError("picks 文件顶层必须是 JSON 数组")
    for it in new_picks:
        missing = {"code", "name", "exchange"} - set(it)
        if missing:
            raise ValueError(f"金股缺少必填字段 {missing}：{it}")
        it["source"] = "auto"
        it.setdefault("type", "个股")

    # 1b. 板块硬门禁（创业板等禁入板块）——放在任何写操作之前，违规即终止
    try:
        assert_board_allowed(new_picks)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)

    # 2. 读取现有 watchlist（不存在则初始化结构）
    if os.path.exists(args.watchlist):
        with open(args.watchlist, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"etfs": [], "stocks": []}

    # 3. 兼容清洗：旧数据补 manual
    for sec in ("etfs", "stocks"):
        for it in data.get(sec, []):
            if "source" not in it:
                it["source"] = "manual"

    # 4. 剥离上周 auto，仅保留 manual
    manual_etfs = [it for it in data.get("etfs", []) if it.get("source") == "manual"]
    manual_stocks = [it for it in data.get("stocks", []) if it.get("source") == "manual"]

    # 5. 拼接：manual 在前，本周 auto 在后
    final = {
        "version": data.get("version", 3),
        "updated": date.today().isoformat(),
        "description": data.get("description", "量化数据采集系统标的清单"),
        "etfs": manual_etfs,
        "stocks": manual_stocks + new_picks,
    }

    with open(args.watchlist, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=4)

    print(f"Watchlist 更新成功！ETF: 手动{len(manual_etfs)}；"
          f"个股: 手动{len(manual_stocks)}+自动{len(new_picks)}")


if __name__ == "__main__":
    main()
