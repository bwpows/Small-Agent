#!/usr/bin/env bash
# deploy/upload.sh — 增量上传到云服务器（rsync，只传变化的文件）
# 用法: bash deploy/upload.sh [server]
#   server 默认 root@你的服务器IP

set -euo pipefail

# ── 配置（改成你自己的） ──
SERVER="${1:-root@146.190.72.26}"
REMOTE_DIR="/opt/Small-Agent"

# 项目根目录（Small-Agent/）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "📦 增量同步: $PROJECT_DIR  →  $SERVER:$REMOTE_DIR"

rsync -avz --progress \
    --delete \
    --exclude 'venv/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '*.pyo' \
    --exclude '.git/' \
    --exclude '.DS_Store' \
    --exclude '*.egg-info/' \
    --exclude 'node_modules/' \
    --exclude '.env' \
    --exclude 'data/' \
    --include '.env.example' \
    "$PROJECT_DIR/" \
    "$SERVER:$REMOTE_DIR/"

echo ""
echo "✅ 上传完成！"
echo ""
echo "SSH 登录部署:"
echo "  ssh $SERVER"
echo "  cd $REMOTE_DIR"
echo "  docker compose up -d --build"
