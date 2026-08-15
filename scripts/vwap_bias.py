#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vwap_bias.py — VWAP 量价双因子清洗 (D2b · Phase 2 可信性层)

设计目标
--------
纯 LLM 层的资金流判定（只看"主力净流入正负"）容易被对倒/被动承接误导。
本脚本以**双因子**修正：
    因子① 主力净流入方向（westock fund_flow / 腾讯主力净流入）
    因子② 收盘价相对 VWAP 的位置（主动买入 → 收在均价线之上）
    双因子共振 → 🟣 主力加仓；净流入为正但收在 VWAP 之下 → 🟣 资金对倒诱多/被动承接

🛡️ 极小值过滤（用户协同）：当 |主力净流入| < 成交额 × 2% 时，直接输出 ⚪ 主力中性，
    避免在"垃圾时间"微幅波动里产生过度解读。

数据来源
--------
- VWAP：从分钟K线（腾讯自选股 `web.ifzq.gtimg.cn` 或东财分钟线）计算，取 Σ(price×volume)/Σvolume。
- 主力净流入 / 成交额：建议由调用方（prompt）用 westock fund_flow 取出后以参数传入，
  亦可 `--code` 单独运行时由脚本自带 fetch 获取（⚠️ **仅 Mac 运行可达**；沙箱东财/腾讯 STALE）。

输出（供 prompt 注入 / grep）
-----------------------------
    VWAP=<float>
    CLOSE_VWAP_RATIO=<float, 如 +0.0123>
    TRUE_FLOW_BIAS=<🟣 主力加仓 | 🟣 资金对倒诱多/被动承接 | 🔴 主力减仓 | ⚪ 主力中性>
    STATUS=<ok | error>
并附一行人类可读结论。

用法
----
    bash scripts/run_env.sh scripts/vwap_bias.py <code> [--date YYYYMMDD]
    bash scripts/run_env.sh scripts/vwap_bias.py <code> --close 1.03 --vwap 1.00 --main-net-inflow 1.2e8 --turnover 5e9
    bash scripts/run_env.sh scripts/vwap_bias.py --selftest     # 沙箱逻辑自测（无需网络）
"""

import argparse
import json
import sys
import urllib.request
import urllib.error

HTTP_CONNECT_TIMEOUT = 8.0
HTTP_READ_TIMEOUT = 20.0
SMALL_INFLOW_RATIO = 0.02  # |净流入| < 成交额 × 2% → 中性


# ---------------------------------------------------------------------------
# 纯逻辑（可单测，不依赖网络）
# ---------------------------------------------------------------------------
def compute_vwap(minutes):
    """minutes: list[(price:float, volume:float)] -> VWAP or None（无量则 None）"""
    tot_pv = 0.0
    tot_v = 0.0
    for price, vol in minutes:
        try:
            p = float(price)
            v = float(vol)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        tot_pv += p * v
        tot_v += v
    if tot_v <= 0:
        return None
    return tot_pv / tot_v


def classify(close, vwap, main_net_inflow, turnover, small_ratio=SMALL_INFLOW_RATIO):
    """双因子分类。返回 (verdict:str, reason:str)。"""
    # 极小值过滤：垃圾时间
    if turnover and abs(float(main_net_inflow)) < abs(float(turnover)) * small_ratio:
        return ("⚪ 主力中性",
                "净流入绝对值低于成交额 %.0f%%，属垃圾时间微幅波动，避免过度解读" % (small_ratio * 100))

    mni = float(main_net_inflow)
    if vwap is None or vwap <= 0:
        # 退化为仅看净流入符号
        if mni > 0:
            return ("🟣 主力加仓(无VWAP)", "未取到 VWAP，按主力净流入为正判定加仓（置信降级）")
        if mni < 0:
            return ("🔴 主力减仓", "未取到 VWAP，按主力净流出判定减仓")
        return ("⚪ 主力中性", "净流入≈0 且无 VWAP，方向不明")

    c = float(close)
    ratio = c / vwap - 1.0
    if mni > 0 and c >= vwap:
        return ("🟣 主力加仓",
                "主力净流入为正且收盘(%.3f)站上VWAP(%.3f)，主动买入意愿真实 (CLOSE_VWAP_RATIO=%+.2f%%)"
                % (c, vwap, ratio * 100))
    if mni > 0 and c < vwap:
        return ("🟣 资金对倒诱多/被动承接",
                "主力净流入为正但收盘(%.3f)低于VWAP(%.3f)，疑似对倒或被动接盘 (CLOSE_VWAP_RATIO=%+.2f%%)"
                % (c, vwap, ratio * 100))
    if mni < 0:
        return ("🔴 主力减仓",
                "主力净流出(%.0f)且收盘(%.3f)%sVWAP(%.3f)"
                % (mni, c, "低于" if c < vwap else "高于", vwap))
    return ("⚪ 主力中性", "净流入≈0，方向不明")


# ---------------------------------------------------------------------------
# 数据获取（仅 Mac 可达；沙箱静默降级为 error）
# ---------------------------------------------------------------------------
def _norm_code(code):
    """转腾讯分钟线前缀：sh/sz + 6位。"""
    c = str(code).lower()
    if c.startswith(("sh", "sz")):
        return c
    digits = "".join(ch for ch in c if ch.isdigit())
    if digits.startswith("6") or digits.startswith("5"):
        return "sh" + digits
    return "sz" + digits


def fetch_minute_tencent(code):
    """返回 list[(price, volume)]；失败抛异常。"""
    url = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=%s" % _norm_code(code)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=HTTP_CONNECT_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8", "ignore"))
    node = data["data"][_norm_code(code)]["data"]
    out = []
    for row in node:  # 腾讯分钟线: [时间, 价格, 涨跌, 均价, 成交量(手), ...]
        try:
            price = float(row[1])
            vol = float(row[4]) * 100.0  # 手 -> 股
        except (IndexError, TypeError, ValueError):
            continue
        out.append((price, vol))
    return out


def fetch_fund_flow_tencent(code):
    """返回 (main_net_inflow:float, turnover:float)；失败抛异常。"""
    # qt.gtimg.cn 主力净流入（单位元）; 成交额用 day 接口近似
    url = "https://qt.gtimg.cn/q=%s" % _norm_code(code)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=HTTP_CONNECT_TIMEOUT) as resp:
        raw = resp.read().decode("gbk", "ignore")
    # 解析主力净流入与成交额（字段较多，取关键）
    # 该接口返回值复杂，此处仅做 best-effort 占位，失败由上层捕获降级
    raise NotImplementedError("fund_flow 解析需结合 westock MCP；建议由调用方以参数传入")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(code, date=None, close=None, vwap=None, main_net_inflow=None, turnover=None):
    status = "ok"
    # 1) VWAP
    if vwap is None:
        if code is None:
            print("VWAP=NaN\nCLOSE_VWAP_RATIO=NaN\nTRUE_FLOW_BIAS=⚪ 主力中性\nSTATUS=error")
            return 1
        try:
            minutes = fetch_minute_tencent(code)
            vwap = compute_vwap(minutes)
        except Exception as e:  # noqa: BLE001
            print("⚠️ VWAP 获取失败（沙箱/网络不可达）: %s" % e, file=sys.stderr)
            vwap = None
            status = "error"

    # 2) 主力净流入 / 成交额
    if main_net_inflow is None or turnover is None:
        try:
            mni, to = fetch_fund_flow_tencent(code)
            main_net_inflow = mni if main_net_inflow is None else main_net_inflow
            turnover = to if turnover is None else turnover
        except Exception:  # noqa: BLE001
            # 取不到则退化为中性判定
            main_net_inflow = main_net_inflow if main_net_inflow is not None else 0.0
            turnover = turnover if turnover is not None else 0.0
            if status == "ok":
                status = "error"

    if close is None:
        print("VWAP=%s\nCLOSE_VWAP_RATIO=NaN\nTRUE_FLOW_BIAS=⚪ 主力中性\nSTATUS=error"
              % ("%.4f" % vwap if vwap else "NaN"))
        return 1

    verdict, reason = classify(close, vwap, main_net_inflow, turnover)
    ratio = (float(close) / float(vwap) - 1.0) if vwap else float("nan")
    print("VWAP=%s" % ("%.4f" % vwap if vwap else "NaN"))
    print("CLOSE_VWAP_RATIO=%s" % ("%+.4f" % ratio if vwap else "NaN"))
    print("TRUE_FLOW_BIAS=%s" % verdict)
    print("STATUS=%s" % status)
    print("> 双因子结论：%s —— %s" % (verdict, reason))
    return 0


def selftest():
    """沙箱逻辑自测：不依赖网络，验证双因子 + 极小值过滤。"""
    cases = [
        # (close, vwap, mni, turnover, expect_contains)
        (1.03, 1.00, 1.2e8, 5e9, "🟣 主力加仓"),          # 净流入+且收>VWAP
        (0.99, 1.00, 1.2e8, 5e9, "🟣 资金对倒诱多/被动承接"),  # 净流入+但收<VWAP
        (0.98, 1.00, -1.2e8, 5e9, "🔴 主力减仓"),            # 净流出
        (1.00, 1.00, 1e6, 5e9, "⚪ 主力中性"),             # 极小值过滤
        (1.00, None, 1.2e8, 5e9, "🟣 主力加仓(无VWAP)"),    # 无VWAP退化
    ]
    ok = True
    for close, vwap, mni, to, expect in cases:
        verdict, _ = classify(close, vwap, mni, to)
        passed = expect in verdict
        ok = ok and passed
        print("[%s] close=%s vwap=%s mni=%s -> %s (expect %s)"
              % ("PASS" if passed else "FAIL", close, vwap, mni, verdict, expect))
    # VWAP 计算
    v = compute_vwap([(10, 100), (20, 100)])  # (10*100+20*100)/200 = 15
    assert abs(v - 15.0) < 1e-9, "VWAP calc wrong: %s" % v
    print("[PASS] compute_vwap([(10,100),(20,100)]) = 15.0")
    print("SELFTEST: %s" % ("ALL PASS" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(description="VWAP 量价双因子清洗 (D2b)")
    p.add_argument("code", nargs="?", help="标的代码，如 515880 / 603259")
    p.add_argument("--date", help="YYYYMMDD（仅 fetch 模式使用）")
    p.add_argument("--close", type=float, help="显式收盘价（由调用方传入可跳过 fetch）")
    p.add_argument("--vwap", type=float, help="显式 VWAP")
    p.add_argument("--main-net-inflow", type=float, help="主力净流入（元，正=流入）")
    p.add_argument("--turnover", type=float, help="成交额（元）")
    p.add_argument("--selftest", action="store_true", help="运行沙箱逻辑自测")
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()
    return run(args.code, args.date, args.close, args.vwap,
               args.main_net_inflow, args.turnover)


if __name__ == "__main__":
    sys.exit(main())
