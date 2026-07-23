#!/usr/bin/env bash
# ──────────────────────────────────────────
# Small-Agent 云服务器一键部署脚本
# 支持：Ubuntu 20.04+ / Debian 11+ / CentOS 8+
# ──────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# ── 配置变量（根据你的服务器修改）──
PROJECT_DIR="/opt/small-agent"
PYTHON_VERSION="3.11"
SERVER_PORT=8000

# ── 检查是否为 root ──
if [ "$EUID" -ne 0 ]; then
    err "请使用 root 执行：sudo bash deploy.sh"
fi

echo "========================================="
echo "  Small-Agent 云服务器部署"
echo "========================================="
echo ""

# ── 1. 安装系统依赖 ──
log "步骤 1/6：安装系统依赖..."

if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq python${PYTHON_VERSION} python${PYTHON_VERSION}-venv \
        python3-pip nginx curl git
elif command -v yum &>/dev/null; then
    yum install -y python${PYTHON_VERSION} python3-pip nginx curl git
else
    err "不支持的操作系统"
fi

# ── 2. 创建项目目录 ──
log "步骤 2/6：创建项目目录..."
mkdir -p "$PROJECT_DIR/data/workspace"
# 如果项目代码不在当前目录，从 git 克隆
if [ ! -f "$PROJECT_DIR/pyproject.toml" ]; then
    # 假设部署脚本在项目根目录的 deploy/ 下
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_SRC="$(dirname "$SCRIPT_DIR")"
    if [ -f "$PROJECT_SRC/pyproject.toml" ]; then
        log "从本地 $PROJECT_SRC 复制项目文件..."
        cp -r "$PROJECT_SRC"/* "$PROJECT_DIR/"
        # 排除不需要的文件
        rm -rf "$PROJECT_DIR/.git" "$PROJECT_DIR/venv" "$PROJECT_DIR/__pycache__"
    else
        err "找不到项目源码，请先 cd 到项目根目录再执行 deploy/deploy.sh"
    fi
fi

# ── 3. 配置环境变量 ──
log "步骤 3/6：配置环境变量..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    if [ -f "$PROJECT_DIR/.env.example" ]; then
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
        warn "已创建 .env 文件，请编辑填入 API Key："
        warn "  vim $PROJECT_DIR/.env"
        warn "  至少需要填写 DEEPSEEK_API_KEY"
    else
        err "缺少 .env.example 文件"
    fi
fi

# ── 4. 创建 Python 虚拟环境并安装 ──
log "步骤 4/6：安装 Python 依赖..."
cd "$PROJECT_DIR"

if [ ! -d "venv" ]; then
    python${PYTHON_VERSION} -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip -q
pip install -e . -q

log "Python 依赖安装完成"

# ── 5. 配置 Nginx ──
log "步骤 5/6：配置 Nginx 反向代理..."

if [ -f "$PROJECT_DIR/deploy/nginx.conf" ]; then
    # 替换 nginx.conf 中的 upstream 为裸机地址
    sed 's/server agent-backend:8000;/server 127.0.0.1:8000;/' \
        "$PROJECT_DIR/deploy/nginx.conf" > /etc/nginx/sites-available/small-agent

    # 移除 docker 网络的 location 层级（nginx 裸机部署直接反向代理到后端）
    ln -sf /etc/nginx/sites-available/small-agent /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default

    nginx -t && systemctl reload nginx
    log "Nginx 配置完成"
else
    warn "未找到 deploy/nginx.conf，跳过 Nginx 配置"
fi

# ── 6. 配置 systemd 服务 ──
log "步骤 6/6：配置 systemd 服务..."

if [ -f "$PROJECT_DIR/deploy/small-agent.service" ]; then
    cp "$PROJECT_DIR/deploy/small-agent.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable small-agent
    systemctl restart small-agent
    log "systemd 服务已启动"
else
    # 直接用 uvicorn 启动（不推荐生产环境）
    warn "未找到 service 文件，手动启动 uvicorn..."
    nohup venv/bin/uvicorn app_server.main:app \
        --host 0.0.0.0 --port "$SERVER_PORT" --workers 4 \
        > /var/log/small-agent.log 2>&1 &
    log "uvicorn 已后台启动，端口 $SERVER_PORT"
fi

# ── 完成 ──
echo ""
echo "========================================="
echo -e "  ${GREEN}部署完成！${NC}"
echo "========================================="
echo -e "  ${GREEN}部署完成！${NC}"
echo "========================================="
echo ""
echo "  站点地址：  https://agent.bwpow.com"
echo "  API 文档：  https://agent.bwpow.com/api/docs"
echo ""
echo "  后续步骤："
echo "  1. 编辑 .env 填入 API Key："
echo "     vim $PROJECT_DIR/.env"
echo "  2. 重启服务："
echo "     systemctl restart small-agent"
echo "  3. 查看日志："
echo "     journalctl -u small-agent -f"
echo ""
echo "  配置 HTTPS（Let's Encrypt 免费证书）："
echo "    sudo apt install certbot python3-certbot-nginx -y"
echo "    sudo certbot --nginx -d agent.bwpow.com"
echo ""
echo "  前端部署（在 small-agent-web 目录执行）："
echo "    npm install && npm run build"
echo "    cp -r dist/ /usr/share/nginx/html/"
echo "========================================="
