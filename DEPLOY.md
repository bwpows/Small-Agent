# 🚀 部署运维指南

> 服务器：`root@146.190.72.26`  
> 项目路径：`/opt/Small-Agent`  
> 域名：`agent.bwpow.com`

---

## 架构概览

```
浏览器 (agent.bwpow.com)
       │
       ▼
┌─────────────────────────────┐
│  Nginx (:80/:443)           │  ← nginx:alpine 镜像
│  · HTTPS 终止               │
│  · /api/* → 转发后端 :8000   │
│  · /*     → 静态文件 dist/   │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  small-agent-backend (:8000)│  ← 自建 Docker 镜像
│  · FastAPI + Uvicorn        │
│  · DeepSeek V4 推理         │
│  · SQLite 持久化             │
└─────────────────────────────┘
```

两个容器通过 `agent-network` bridge 网络通信。

---

## 目录映射

| 本地路径 | 服务器路径 | 说明 |
|----------|-----------|------|
| `Small-Agent/src/` | `/opt/Small-Agent/src/` | 后端源码 |
| `Small-Agent/Dockerfile` | `/opt/Small-Agent/Dockerfile` | 镜像构建文件 |
| `Small-Agent/docker-compose.yml` | `/opt/Small-Agent/docker-compose.yml` | 容器编排 |
| `Small-Agent/.env` | `/opt/Small-Agent/.env` | 环境变量（不上传） |
| `Small-Agent/data/` | `/opt/Small-Agent/data/` | 数据库 + 工作区 |
| `Small-Agent/dist/` | `/opt/Small-Agent/dist/` | 前端构建产物 |
| `Small-Agent/deploy/nginx.conf` | `/opt/Small-Agent/deploy/nginx.conf` | Nginx 配置 |
| `small-agent-web/` | — | 前端源码（本地构建后上传 dist） |

---

## 部署流程

### 一、后端部署

**⚠️ 重要：后端源码是 Docker 构建时 `COPY` 进镜像的，不是 volume 挂载。任何代码修改都必须 `--build` 重建镜像，单纯 `scp` + `restart` 不会生效。**

```bash
# 1. 上传修改的文件到服务器
scp Small-Agent/src/agent_engine/llm_engine.py \
    root@146.190.72.26:/opt/Small-Agent/src/agent_engine/

scp Small-Agent/src/agent_engine/tools/tool_search.py \
    root@146.190.72.26:/opt/Small-Agent/src/agent_engine/tools/

scp Small-Agent/src/app_server/chat_service.py \
    root@146.190.72.26:/opt/Small-Agent/src/app_server/

# 2. 重建镜像并重启容器（必须执行这一步）
ssh root@146.190.72.26 "cd /opt/Small-Agent && docker compose up -d --build agent-backend"
```

> **为什么必须 rebuild？**  
> `Dockerfile` 第 21 行 `COPY src/ ./src/` 在构建时把源码拷贝进镜像。  
> `docker-compose.yml` 里没有 `./src:/app/src` 的 volume 挂载，所以 scp 改了宿主机文件，容器里还是旧代码。  
> 只有 `data/` 和 `.env` 是 volume 挂载，可以热更新。

### 二、前端部署

前端是独立项目，本地构建后上传 `dist/` 即可。Nginx 通过 volume 挂载直接读取，**无需重启任何容器**。

```bash
# 1. 本地构建
cd small-agent-web
npm run build

# 2. 上传到服务器
scp -r dist/* root@146.190.72.26:/opt/Small-Agent/dist/
```

前端立即生效，无需重启 Nginx。

### 三、Nginx 配置更新

Nginx 配置通过 volume 挂载 (`./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro`)，上传后 reload 即可，无需重建。

```bash
# 1. 上传
scp deploy/nginx.conf root@146.190.72.26:/opt/Small-Agent/deploy/nginx.conf

# 2. 重新加载
ssh root@146.190.72.26 "docker compose -f /opt/Small-Agent/docker-compose.yml exec nginx nginx -s reload"
```

### 四、环境变量更新

`.env` 是 volume 挂载，修改后需要重启后端容器。

```bash
# 1. 上传
scp .env root@146.190.72.26:/opt/Small-Agent/.env

# 2. 重启后端
ssh root@146.190.72.26 "cd /opt/Small-Agent && docker compose restart agent-backend"
```

---

## 常用运维命令

```bash
ssh root@146.190.72.26

# 查看容器状态
cd /opt/Small-Agent && docker compose ps

# 查看后端日志（最近 100 行）
cd /opt/Small-Agent && docker compose logs --tail=100 agent-backend

# 查看 Nginx 日志
cd /opt/Small-Agent && docker compose logs --tail=50 nginx

# 重启后端容器（不重建镜像）
cd /opt/Small-Agent && docker compose restart agent-backend

# 重启所有服务
cd /opt/Small-Agent && docker compose restart

# 完全重建并启动所有服务
cd /opt/Small-Agent && docker compose up -d --build

# 进入容器调试
cd /opt/Small-Agent && docker compose exec agent-backend bash

# 在容器内验证 Python 导入
docker compose exec agent-backend python3 -c "from duckduckgo_search import DDGS; print('OK')"
```

---

## 踩坑记录

### ❌ 坑 1：scp + restart 不会让后端代码生效

**现象**：上传了代码文件，`docker compose restart` 后发现没变化。  
**原因**：后端源码是 Dockerfile 中 `COPY` 进镜像的，restart 只是重启旧容器，不会重新 COPY 新代码。  
**解决**：必须执行 `docker compose up -d --build agent-backend` 重建镜像。

### ❌ 坑 2：conversation_id 放错位置导致每次新会话

**现象**：每次提问都生成一条新对话，左侧历史列表全是"新会话"。  
**原因**：前端把 `conversation_id` 放在 JSON body 里，后端从 URL 查询参数读取，前后端不一致。  
**解决**：`ChatBox.jsx` 中把 `conversation_id` 拼到 URL query 参数上（`url.searchParams.set('conversation_id', convId)`），body 中不再携带。

### ❌ 坑 3：search_web 工具在线上不显示

**现象**：本地有搜索工具，线上没有。  
**原因链条**：
1. `tool_search.py` 导入的是 `from ddgs import DDGS`（另一个独立的 pip 包）
2. `requirements.txt` 安装的是 `duckduckgo-search`（导入路径是 `duckduckgo_search.DDGS`）
3. `llm_engine.py` 第 36 行 `except Exception as e: pass` 静默吞掉了 `ModuleNotFoundError`
4. 工具加载失败没有任何日志，悄悄消失

**解决**：
- 统一导入为 `from duckduckgo_search import DDGS`
- `except` 改为 `logger.warning(f"[ToolLoader] 加载工具 {module_name} 失败: {e}")`

### ❌ 坑 4：模型反复调用同一工具陷入死循环

**现象**：模型搜完一次又搜一次，直到 `max_loops=4` 上限后报"陷入死循环"。  
**原因**：系统提示词中"绝对权限"措辞过于激进，且代码层没有任何拦截重复调用的机制。  
**解决**：
- 提示词增加第 5 条铁律"严禁重复调用"
- 代码层增加 `prev_tool_name` 追踪，同一工具连续调用则拦截返回警告

---

## 快速参考卡

```
                    是否需要 rebuild？
    ┌──────────────┬───────────────────┐
    │  修改内容     │  生效方式          │
    ├──────────────┼───────────────────┤
    │  后端源码     │  上传 + rebuild   │
    │  前端 dist    │  上传即生效        │
    │  nginx.conf  │  上传 + reload    │
    │  .env 环境变量│  上传 + restart   │
    │  data/ 数据   │  volume，自动同步  │
    └──────────────┴───────────────────┘
```
