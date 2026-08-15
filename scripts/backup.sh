#!/usr/bin/env bash
#
# 三层备份一键同步脚本
# ⚠️ 须在【用户自己的 Mac 终端】运行，不要在 WorkBuddy 内运行。
#    原因：WorkBuddy 运行环境代理会拦截 github.com（CONNECT 502），
#          git push 只能在直连公网的终端执行；本机镜像/bundle 不受此限。
#
set -euo pipefail

# 强制时区为北京时间（影响后续所有 date 命令与子进程 Python 的默认时区，
# 消除调度引擎宿主机 TZ 漂移；与 init_check.sh / run.sh 基调一致）
export TZ="Asia/Shanghai"

# 解析仓库根目录（scripts/ 的上级），避免硬编码绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
BAK="$HOME/backups"

cd "$REPO"
echo "📁 仓库: $REPO"

echo "==> [1/3] 本地热备镜像 (bare mirror)"
mkdir -p "$BAK"
if [ ! -d "$BAK/fin-analysis-mirror.git" ]; then
  git clone --mirror "$REPO" "$BAK/fin-analysis-mirror.git" >/dev/null 2>&1 || true
fi
git push --mirror "$BAK/fin-analysis-mirror.git"

echo "==> [2/3] 离线冷备 bundle（原子性：先建 tmp → 校验 → 保留上一版 → 覆盖）"
BUNDLE="$BAK/fin-analysis-$(date +%Y%m%d).bundle"
TMP_BUNDLE="${BUNDLE}.tmp"
rm -f "$TMP_BUNDLE"
git bundle create "$TMP_BUNDLE" --all
if git bundle verify "$TMP_BUNDLE" >/dev/null 2>&1; then
    # 保留上一版健康备份作为兜底，再覆盖当日 bundle
    [ -f "$BUNDLE" ] && mv -f "$BUNDLE" "${BUNDLE}.prev"
    mv -f "$TMP_BUNDLE" "$BUNDLE"
    echo "    bundle 校验通过: $BUNDLE"
else
    echo "    ❌ bundle 校验失败，保留旧备份: $BUNDLE" >&2
    rm -f "$TMP_BUNDLE"
    exit 1
fi

echo "==> [3/3] GitHub 云端热备"
git push origin main

echo "✅ 三层备份同步完成（本地镜像 + 离线 bundle + GitHub 云端）"
