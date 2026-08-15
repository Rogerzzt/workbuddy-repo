#!/usr/bin/env bash
#
# 三层备份一键同步脚本
#
# 用法：
#   bash scripts/backup.sh                       # 完整三段（本地镜像 + 离线 bundle + GitHub 云端）
#   SKIP_GITHUB=1 bash scripts/backup.sh         # 仅本地两段（断网/云端不可达时仍保底）
#   GITHUB_REMOTE=origin GITHUB_REF=main bash scripts/backup.sh
#
# 说明：
#   - 本地镜像 / bundle 在任意环境均可运行（纯本地文件系统）。
#   - GitHub 段带【重试 3 次 + 指数退避】，并采用 git 原生超时而非 coreutils `timeout`
#     （macOS 默认无 `timeout` 命令）：http.timeout=120s + lowSpeedLimit 防止长时挂起；
#     GIT_TERMINAL_PROMPT=0 避免无凭据时卡在交互输入。
#   - 云端失败不影响本地两段；脚本以明确退出码区分（2 = 仅云端失败）。
#
set -uo pipefail

# 强制北京时间（与 init_check.sh / run.sh 基调一致，消除宿主机 TZ 漂移）
export TZ="Asia/Shanghai"

# 解析仓库根目录（scripts/ 的上级），避免硬编码绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
BAK="$HOME/backups"
GITHUB_REMOTE="${GITHUB_REMOTE:-origin}"
GITHUB_REF="${GITHUB_REF:-main}"

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

# 可选跳过云端（断网保底）
if [ "${SKIP_GITHUB:-0}" = "1" ]; then
  echo "==> [3/3] GitHub 云端热备：已通过 SKIP_GITHUB=1 跳过"
  echo "✅ 本地两段备份完成（镜像 + bundle）。GitHub 云端未同步。"
  exit 0
fi

echo "==> [3/3] GitHub 云端热备（重试 3 次，git 原生超时，禁止交互提示）"
MAX_TRIES=3
TRY=0
PUSH_OK=0
while [ "$TRY" -lt "$MAX_TRIES" ]; do
  TRY=$((TRY + 1))
  echo "    尝试 $TRY/$MAX_TRIES ..."
  if GIT_TERMINAL_PROMPT=0 git -c http.timeout=120 -c http.lowSpeedLimit=1 -c http.lowSpeedTime=30 \
        push "$GITHUB_REMOTE" "$GITHUB_REF" 2>&1; then
    PUSH_OK=1
    break
  fi
  if [ "$TRY" -lt "$MAX_TRIES" ]; then
    echo "    ⚠️ 第 $TRY 次推送失败（网络/认证/远程），5s 后重试" >&2
    sleep 5
  fi
done

if [ "$PUSH_OK" -eq 1 ]; then
  echo "✅ 三层备份同步完成（本地镜像 + 离线 bundle + GitHub 云端）"
else
  echo "❌ GitHub 云端推送失败（已重试 $MAX_TRIES 次）。本地镜像与离线 bundle 均已成功，代码不丢。" >&2
  echo "   排查：检查本机网络/代理/VPN；确认 remote 可达；可改用 SSH（git@github.com:Rogerzzt/workbuddy-repo.git）；或稍后重跑本脚本。" >&2
  exit 2
fi
