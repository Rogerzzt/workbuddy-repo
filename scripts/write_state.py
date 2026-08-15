#!/usr/bin/env python3
# ============================================================================
# write_state.py — JSON 状态文件「唯一落盘口」（固化 CLI，零第三方依赖）
# ----------------------------------------------------------------------------
# 背景：原先盘前/盘后任务要求 LLM 在终端内联写 Python 拼 JSON，trigger_condition
#       等字段一旦含未转义引号即 SyntaxError/JSONDecodeError，切断闭环。
# 用法（由 prompt 指示 LLM 调用）：
#   1) LLM 用 Write 工具把【纯 JSON 文本】写入临时文件（禁止 ```json 代码围栏/Markdown）
#   2) 调用本脚本做校验 + 原子落盘：
#      python3 scripts/write_state.py \
#        --in  data/.tmp_pre_market_state_YYYYMMDD.json \
#        --out data/pre_market_state_YYYYMMDD.json \
#        --required date,positions
#   非零退出 = 校验失败，LLM 必须重写临时文件直至通过。
# ============================================================================
import argparse
import json
import os
import sys
import tempfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", required=True, help="LLM 写出的 JSON 临时文件")
    ap.add_argument("--out", dest="outfile", required=True, help="目标落盘路径（原子写）")
    ap.add_argument("--required", default="", help="必须存在的顶层字段，逗号分隔，如 date,positions")
    ap.add_argument("--no-cleanup", action="store_true", help="校验成功后不删除 --in 临时文件")
    args = ap.parse_args()

    # 1) 读取并解析
    try:
        with open(args.infile, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        print(f"❌ 无法读取输入文件 {args.infile}: {e}", file=sys.stderr)
        return 2

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析失败（{args.infile}）：{e}", file=sys.stderr)
        print("   请检查 trigger_condition 等字段是否含未转义引号或 Markdown 代码围栏。", file=sys.stderr)
        return 3

    if not isinstance(data, dict):
        print("❌ 顶层必须是 JSON 对象（dict）", file=sys.stderr)
        return 4

    # 2) 必需字段校验
    req = [x.strip() for x in args.required.split(",") if x.strip()]
    missing = [k for k in req if k not in data]
    if missing:
        print(f"❌ 缺少必需字段：{missing}", file=sys.stderr)
        return 5

    # 3) 原子写（tempfile + os.replace）
    out_dir = os.path.dirname(os.path.abspath(args.outfile))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_dir, suffix=".tmp", prefix=".wstate_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, args.outfile)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        print(f"❌ 落盘失败 {args.outfile}: {e}", file=sys.stderr)
        return 6

    # 4) 回读自检
    try:
        with open(args.outfile, "r", encoding="utf-8") as f:
            json.load(f)
    except Exception as e:
        print(f"❌ 落盘后回读校验失败：{e}", file=sys.stderr)
        return 7

    if not args.no_cleanup:
        try:
            os.remove(args.infile)
        except OSError:
            pass

    print(f"✅ 状态已校验并原子落盘: {args.outfile}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
