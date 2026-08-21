#!/usr/bin/env bash
#
# 一键重应用 dsh-im-gateway 自定义实现（模型切换卡片 + 模型偏好持久化）。
#
# 背景：dsh-im-gateway 的官方包在更新/重装时会被还原为干净版本，
# 我们在 lib/*.js 里的自定义实现（/model 发卡片切换模型）会丢失。
# pnpm 的 patchedDependencies 会在每次 pnpm install 时自动重新打好补丁；
# 本脚本是另一道保险：在不想跑完整 pnpm install 时，直接把补丁打到 node_modules。
#
# 用法：
#   ./reapply.sh                       # 默认补丁当前 dsh profile 的 node_modules
#   ./reapply.sh <node_modules 根路径> # 指定 node_modules 位置
#
# 幂等：已应用则跳过并提示；未应用则打上；版本不匹配/冲突则报错退出（不破坏文件）。

set -euo pipefail

# 定位本脚本目录，进而定位补丁文件（跟随符号链接）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_FILE="${SCRIPT_DIR}/dsh-im-gateway@0.3.1.patch"
PKG_VERSION="0.3.1"
PKG_REL="dsh-im-gateway"

NODE_MODULES="${1:-${HOME}/.dsh/profiles/web/node_modules}"
PKG_DIR="${NODE_MODULES}/${PKG_REL}"

if [[ ! -f "${PATCH_FILE}" ]]; then
    echo "[reapply] 补丁文件不存在: ${PATCH_FILE}" >&2
    exit 1
fi
if [[ ! -d "${PKG_DIR}" ]]; then
    echo "[reapply] 未找到插件目录: ${PKG_DIR}" >&2
    exit 1
fi

# 校验已安装版本是否与补丁匹配
INSTALLED=$(node -e "try{console.log(require('${PKG_DIR}/package.json').version)}catch(e){process.exit(1)}" 2>/dev/null || \
            grep -m1 '"version"' "${PKG_DIR}/package.json" | sed -E 's/.*: *"([^"]+)".*/\1/' || echo "unknown")
if [[ "${INSTALLED}" != "${PKG_VERSION}" ]]; then
    echo "[reapply] 警告: 已安装版本 ${INSTALLED} != 补丁版本 ${PKG_VERSION}。" >&2
    echo "[reapply] 当前补丁是按 ${PKG_VERSION} 生成的，直接应用可能冲突。请改用 pnpm patch 流程为新版本重新生成补丁。" >&2
    exit 1
fi

cd "${PKG_DIR}"
# git apply 严格且语义明确：不做模糊匹配、不会像 BSD patch 那样在 --batch 下自动反向把已打的补丁卸掉。
if ! git apply --check "${PATCH_FILE}" >/dev/null 2>&1; then
    # 正向无法干净应用 → 优先判断是否已打过补丁（此时应能反向应用）
    if git apply --check --reverse "${PATCH_FILE}" >/dev/null 2>&1; then
        echo "[reapply] 补丁已存在，无需重复应用。"
        exit 0
    fi
    echo "[reapply] 正向应用与反向校验均失败，代码与补丁不匹配或已被部分改动。" >&2
    echo "[reapply] 请对照 lib/*.js 与补丁手动核验后再运行本脚本。" >&2
    exit 1
fi

echo "[reapply] 检测到未打补丁，正在应用 dsh-im-gateway@${PKG_VERSION} 自定义实现 ..."
if ! git apply "${PATCH_FILE}"; then
    echo "[reapply] 应用失败，文件未被破坏，请人工检查。" >&2
    exit 1
fi
echo "[reapply] 完成 ✓ 请重启 dsh web 生效。"
exit 0