import os
import csv
import json
import threading
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from agent_engine.tracing import trace_span, SpanKind

# ==========================================
# 🌟 全局路径与权限配置
# ==========================================
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WORKSPACE_DIR = os.path.join(_PROJECT_ROOT, "data", "workspace")
TOKEN_PATH = os.path.join(WORKSPACE_DIR, 'token.json')
CREDS_PATH = os.path.join(WORKSPACE_DIR, 'credentials.json')
SERVICE_ACCOUNT_PATH = os.path.join(WORKSPACE_DIR, 'service_account.json')
SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive.metadata.readonly',
    'https://www.googleapis.com/auth/spreadsheets'
]

# ==========================================
# 🔐 线程级 Drive 凭证存储（多租户支持）
# ==========================================
_thread_local = threading.local()

# ═══════════════════════════════════════════
# Service Account 凭证缓存（全局单例，避免重复加载）
# ═══════════════════════════════════════════
_service_account_creds: Credentials | None = None
_service_account_loaded: bool = False


def _load_service_account_creds() -> Credentials | None:
    """加载 Service Account 凭证（文件路径或 JSON 字符串"""
    global _service_account_creds, _service_account_loaded
    if _service_account_loaded:
        return _service_account_creds
    _service_account_loaded = True

    # ── 方式1: 通过环境变量直接传入 JSON 字符串 ──
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if sa_json:
        try:
            info = json.loads(sa_json)
            _service_account_creds = service_account.Credentials.from_service_account_info(
                info, scopes=SCOPES
            )
            return _service_account_creds
        except (json.JSONDecodeError, ValueError):
            pass

    # ── 方式2: 通过环境变量指定文件路径 ──
    sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    if sa_file and os.path.isfile(sa_file):
        try:
            _service_account_creds = service_account.Credentials.from_service_account_file(
                sa_file, scopes=SCOPES
            )
            return _service_account_creds
        except (ValueError, IOError):
            pass

    # ── 方式3: 默认路径 data/workspace/service_account.json ──
    if os.path.isfile(SERVICE_ACCOUNT_PATH):
        try:
            _service_account_creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_PATH, scopes=SCOPES
            )
            return _service_account_creds
        except (ValueError, IOError):
            pass

    return None


def has_service_account() -> bool:
    """检查是否配置了 Service Account（无需实际加载）"""
    if os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", ""):
        return True
    if os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", ""):
        return True
    return os.path.isfile(SERVICE_ACCOUNT_PATH)


def set_service_account_from_json(sa_json_str: str):
    """从 JSON 字符串设置全局 Service Account 凭证"""
    global _service_account_creds, _service_account_loaded
    info = json.loads(sa_json_str)
    _service_account_creds = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES
    )
    _service_account_loaded = True


def clear_service_account():
    """清除全局 Service Account 凭证"""
    global _service_account_creds, _service_account_loaded
    _service_account_creds = None
    _service_account_loaded = False


def set_thread_drive_creds(token_json: str):
    """从 token JSON 字符串创建并存储 Google Credentials 到线程本地。
    由 server/chat_service.py 在调用 generate_answer() 前注入。"""
    creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    _thread_local.drive_creds = creds


def clear_thread_drive_creds():
    """清除线程本地的 Drive 凭证"""
    _thread_local.drive_creds = None


def authenticate_drive():
    """认证 Google Drive — 优先级：
    1. 线程级 OAuth 凭证（多租户，每个用户自己的 Drive）
    2. 全局 Service Account（公共 Drive 共享访问）
    3. 本地 OAuth token.json（开发环境）
    """
    # ── 优先级1：线程级 OAuth 凭证（多租户服务端）──
    creds = getattr(_thread_local, 'drive_creds', None)
    if creds is not None:
        if creds.valid or (creds.expired and creds.refresh_token):
            if creds.expired:
                creds.refresh(Request())
            return creds

    # ── 优先级2：全局 Service Account（公共 Drive）──
    sa_creds = _load_service_account_creds()
    if sa_creds is not None:
        if sa_creds.expired or not sa_creds.valid:
            sa_creds.refresh(Request())
        return sa_creds

    # ── 优先级3：本地 OAuth token.json（开发环境）──
    if not os.path.exists(WORKSPACE_DIR):
        os.makedirs(WORKSPACE_DIR)

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_PATH):
                raise FileNotFoundError(
                    f"❌ 找不到 Google 凭据！请配置以下任一方式：\n"
                    f"  1. 设置环境变量 GOOGLE_SERVICE_ACCOUNT_JSON（推荐，Service Account）\n"
                    f"  2. 设置环境变量 GOOGLE_SERVICE_ACCOUNT_FILE 指向 Service Account JSON 文件\n"
                    f"  3. 将 service_account.json 放入 {WORKSPACE_DIR} 目录\n"
                    f"  4. 将 credentials.json 放入 {WORKSPACE_DIR} 目录（开发用 OAuth）"
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=8080)
        
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
    
    return creds

# ==========================================
# 🚀 1. 增：智能数据入库专家 (创建与追加)
# ==========================================
def auto_drive_manager(sheet_name, data_array=None):
    """智能数据入库与建表专家"""
    # 🌟 修复点1：允许 data_array 为空或未传
    if data_array is None:
        data_array = []
    if data_array and not isinstance(data_array, list):
        data_array = [data_array]

    try:
        creds = authenticate_drive()
        drive_service = build('drive', 'v3', credentials=creds)
        sheets_service = build('sheets', 'v4', credentials=creds)
        
        query = f"name='{sheet_name}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
        files = drive_service.files().list(q=query, fields="files(id, name)").execute().get('files', [])

        if not files:
            # 🌟 修复点2：如果没有传数据，默认给几个基础表头占位
            headers = list(data_array[0].keys()) if data_array and isinstance(data_array[0], dict) else ["A列", "B列", "C列"]
            
            temp_csv = os.path.join(WORKSPACE_DIR, f"temp_{sheet_name}.csv")
            with open(temp_csv, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                
            file_meta = {'name': sheet_name, 'mimeType': 'application/vnd.google-apps.spreadsheet'}
            media = MediaFileUpload(temp_csv, mimetype='text/csv')
            created_file = drive_service.files().create(body=file_meta, media_body=media).execute()
            os.remove(temp_csv)
            file_id = created_file.get('id')
            cloud_headers = headers
            is_new = True
        else:
            file_id = files[0]['id']
            header_result = sheets_service.spreadsheets().values().get(spreadsheetId=file_id, range="A1:Z1").execute()
            cloud_headers = header_result.get('values', [[]])[0]
            if not cloud_headers: cloud_headers = ["A列", "B列", "C列"]
            is_new = False

        # 🌟 修复点3：如果只是为了建表（没有传具体数据），建完直接返回成功，不再往下走！
        # 🌟 修复点3：严厉的防假阳性提示
        if not data_array:
            if is_new:
                return f"✅ 成功新建了空表格『{sheet_name}』。⚠️ 但请注意：你本次调用没有传入任何 data_array，因此【没有插入任何数据记录】！"
            else:
                # 如果表存在且没传数据，必须返回严重警告，打断大模型的幻觉！
                return f"❌ 警告：表格『{sheet_name}』已存在，但你本次调用【缺少 data_array 参数】！如果你是在尝试添加记录，请务必把数据放进 data_array 中并重新调用本工具！"
            
        # --- 核心数据组装与映射 ---
        rows_to_insert = []
        for item in data_array:
            if isinstance(item, dict):
                row = [str(item.get(h, "")) for h in cloud_headers]
                # 🚨 安检：如果一整行全都是空字符串，直接扔掉！
                if any(cell.strip() for cell in row): 
                    rows_to_insert.append(row)
            elif isinstance(item, list):
                row = [str(x) for x in item]
                if any(cell.strip() for cell in row):
                    rows_to_insert.append(row)
            else:
                if str(item).strip():
                    rows_to_insert.append([str(item)])

        # 🚨 终极安检门：如果折腾半天，真正要插入的数据行依然是空的，立刻抛出带 ❌ 的报错！触发测谎仪！
        if not rows_to_insert:
            if is_new:
                return f"✅ 成功新建空表格『{sheet_name}』。⚠️ 但注意：没有提取到任何有效的数据行来插入！"
            else:
                return f"❌ 警告：你传入的 data_array 格式有误或全为空白，【最终没有任何有效数据被插入】！如果是添加记录，请确保 data_array 包含具体的键值对字典（如 [{{\"微信昵称\":\"李四\", \"手机号\":\"123\"}}]）。"

        # ================= 提交到 Google API =================
        if rows_to_insert:
            sheets_service.spreadsheets().values().append(
                spreadsheetId=file_id, range="A1", 
                valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
                body={'values': rows_to_insert}
            ).execute()
            
        action_text = "新建并初始化" if is_new else "智能追加"
        return f"✅ 成功！已向『{sheet_name}』{action_text}了 {len(rows_to_insert)} 行实体数据。"

    except Exception as e:
        return f"❌ 操作失败: {str(e)}"

# ==========================================
# 🚀 2. 删、改：高级表格编辑工具 (遗失的拼图补回)
# ==========================================
def manage_sheet_rows(sheet_name=None, action=None, sheet_id=None, row_index=None, new_data=None, confirmed=False):
    """表格高级编辑：支持读取、删除、清空、修改。
    支持通过 sheet_name 或 sheet_id 定位表格（sheet_id 优先，可跳过名称搜索直接定位）。"""
    # ── 参数前置校验（在 API 调用之前，避免浪费网络请求）──
    if not action:
        return "❌ 缺少 action 参数。可选值：read、delete、clear、update。"
    if action == 'delete' and not row_index:
        return "❌ 删除操作缺少 row_index 参数。请指定要删除的行号（如 row_index=10）后重试。"
    if action == 'update' and (not row_index or not new_data):
        return "❌ 更新操作需要同时提供 row_index 和 new_data 参数。"

    try:
        with trace_span("tool_drive::auth", kind=SpanKind.TOOL, capture_output=False):
            creds = authenticate_drive()
            sheets_service = build('sheets', 'v4', credentials=creds)
            drive_service = build('drive', 'v3', credentials=creds)
        
        if not sheet_id:
            if not sheet_name:
                return "❌ 必须提供 sheet_name 或 sheet_id 来进行定位。"
            with trace_span("tool_drive::find_sheet", kind=SpanKind.TOOL,
                           inputs={"search_name": sheet_name},
                           capture_output=False):
                query = f"name='{sheet_name}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
                files = drive_service.files().list(q=query).execute().get('files', [])
                if not files: return f"❌ 找不到名为「{sheet_name}」的表格（或该文件不是 Google Sheets 格式）。"
                sheet_id = files[0]['id']
                sheet_name = sheet_name or files[0]['name']
        else:
            # 通过 ID 定位时，回填名称便于日志输出
            if not sheet_name:
                try:
                    meta = drive_service.files().get(fileId=sheet_id, fields="name").execute()
                    sheet_name = meta.get("name", sheet_id)
                except:
                    sheet_name = sheet_id

        # 🌟 新增：读取整个表格内容的功能
        if action == 'read':
            with trace_span("tool_drive::read", kind=SpanKind.TOOL,
                           inputs={"sheet": sheet_name, "sheet_id": sheet_id},
                           capture_output=False) as read_span:
                result = sheets_service.spreadsheets().values().get(spreadsheetId=sheet_id, range="A1:Z1000").execute()
                values = result.get('values', [])
                if not values: return f"📭 表格 {sheet_name} 是空的。"
                
                output = f"📊 表格【{sheet_name}】的数据如下：\n"
                for i, row in enumerate(values):
                    output += f"第{i+1}行: {row}\n"
                read_span.set_output({"row_count": len(values), "sheet": sheet_name})
                return output

        elif action == 'clear':
            with trace_span("tool_drive::clear", kind=SpanKind.TOOL,
                           inputs={"sheet": sheet_name, "sheet_id": sheet_id},
                           capture_output=False):
                sheets_service.spreadsheets().values().clear(spreadsheetId=sheet_id, range="A1:Z1000").execute()
                return f"✅ 表格 {sheet_name} 已清空。"
        
        elif action == 'delete':
            # 🌟 关键修复：动态获取真实的 sheetId (工作表标签 ID)，干掉写死的 0
            spreadsheet_info = sheets_service.spreadsheets().get(spreadsheetId=sheet_id).execute()
            real_sheet_id = spreadsheet_info['sheets'][0]['properties']['sheetId']
            
            row_data = sheets_service.spreadsheets().values().get(spreadsheetId=sheet_id, range=f"A{row_index}:Z{row_index}").execute().get('values', [[]])[0]
            if not confirmed:
                with trace_span("tool_drive::delete_preview", kind=SpanKind.TOOL,
                               inputs={"sheet": sheet_name, "row": row_index, "data": str(row_data)[:200]},
                               capture_output=False):
                    return (
                        f"⚠️ 确认删除：您准备删除第 {row_index} 行。\n"
                        f"数据为：{row_data}\n"
                        f"⏩ 请用相同参数再次调用，并传入 confirmed=True 即可执行删除。"
                    )
            
            with trace_span("tool_drive::delete_exec", kind=SpanKind.TOOL,
                           inputs={"sheet": sheet_name, "row": row_index, "confirmed": True},
                           capture_output=False) as del_span:
                # 使用获取到的 real_sheet_id 替换掉原来的 0
                body = {"requests": [{"deleteDimension": {"range": {"sheetId": real_sheet_id, "dimension": "ROWS", "startIndex": row_index-1, "endIndex": row_index}}}]}
                sheets_service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()
                del_span.set_output({"sheet": sheet_name, "deleted_row": row_index})
                return f"✅ 已成功删除第 {row_index} 行数据。"
            
        elif action == 'update':
            with trace_span("tool_drive::update", kind=SpanKind.TOOL,
                           inputs={"sheet": sheet_name, "row": row_index, "new_data": str(new_data)[:200]},
                           capture_output=False) as upd_span:
                range_to_update = f"A{row_index}"
                body = {'values': [new_data]}
                sheets_service.spreadsheets().values().update(
                    spreadsheetId=sheet_id, range=range_to_update, 
                    valueInputOption="USER_ENTERED", body=body
                ).execute()
                upd_span.set_output({"sheet": sheet_name, "updated_row": row_index})
                return f"✅ 已将第 {row_index} 行更新成功。"
            
        return "❌ 缺少必要参数或未知的 action。"
    except Exception as e:
        return f"❌ 操作失败: {str(e)}"

# ==========================================
# 🚀 3. 查：云端文件检索工具
# ==========================================
def list_drive_files(limit=10, query=None):
    try:
        creds = authenticate_drive()
        service = build('drive', 'v3', credentials=creds)
        search_q = f"name contains '{query}'" if query else None
        
        results = service.files().list(
            pageSize=limit, q=search_q, fields="files(id, name, mimeType)", orderBy="modifiedTime desc"
        ).execute()
        
        files = results.get('files', [])
        if not files: return f"📭 没有找到包含『{query}』的文件。" if query else "📭 没有任何文件。"
        
        # 🌟 根据 mimeType 标记文件类型
        def type_label(mime):
            if mime == "application/vnd.google-apps.spreadsheet": return "📊"
            if mime == "application/vnd.google-apps.document": return "📝"
            if mime == "application/vnd.google-apps.folder": return "📁"
            return "📄"
            
        file_list = [f"- {type_label(f.get('mimeType',''))} {f['name']} (ID: {f['id']}, 类型: {f.get('mimeType','未知')})" for f in files]
        return f"📂 【查询结果】:\n" + "\n".join(file_list)
    except Exception as e:
        return f"❌ 获取列表失败: {str(e)}"

# ==========================================
# 🚀 4. 传：文件上传工具
# ==========================================
def upload_file_to_drive(local_file_path, drive_filename=None):
    try:
        if not os.path.isabs(local_file_path):
            local_file_path = os.path.join(PROJECT_ROOT, local_file_path)
        if not os.path.exists(local_file_path): return f"❌ 找不到本地文件 {local_file_path}"

        creds = authenticate_drive()
        service = build('drive', 'v3', credentials=creds)
        file_metadata = {'name': drive_filename or os.path.basename(local_file_path)}
        media = MediaFileUpload(local_file_path, resumable=True)
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return f"✅ 上传成功，云端 ID: {file.get('id')}"
    except Exception as e:
        return f"❌ 上传失败: {str(e)}"

# ==========================================
# 🛠️ 动态路由批量注册声明 (包含完整的四大工具)
# ==========================================
REGISTER_TOOLS = [
    {
        "name": "auto_drive_manager",
        "func": auto_drive_manager,
        "definition": {
            "type": "function",
            "function": {
                "name": "auto_drive_manager",
                "description": "智能数据入库专家。用于新建表格或追加数据。如果只想新建空表，传一个空的 data_array 即可。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sheet_name": {"type": "string"},
                        "data_array": {"type": "array", "description": "要追加的数据，如果仅新建表则传空数组 []"}
                    },
                    "required": ["sheet_name"]  # 🌟 修复点4：把 data_array 从这里去掉了！
                }
            }
        }
    },
    # ==========================================
    # 请确保 REGISTER_TOOLS 里 manage_sheet_rows 的定义是这样的
    # ==========================================
    {
        "name": "manage_sheet_rows",
        "func": manage_sheet_rows,
        "definition": {
            "type": "function",
            "function": {
                "name": "manage_sheet_rows",
                "description": "表格高级编辑工具。支持：读取(read)、删除(delete)、清空(clear)、更新(update)。⚠️ 删除需两步：第1次调用返回预览，第2次必须带 confirmed=True 才会真正删除。可通过 sheet_name 或 sheet_id 定位表格（sheet_id 优先）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sheet_name": {"type": "string", "description": "表格名称（和 sheet_id 二选一）"},
                        "sheet_id": {"type": "string", "description": "Google Sheets 文件 ID（和 sheet_name 二选一，优先使用）"},
                        "action": {"type": "string", "enum": ["read", "delete", "clear", "update"]},
                        "row_index": {"type": "integer", "description": "目标行号 (read和clear模式下不需要)"},
                        "new_data": {"type": "array", "description": "修改模式下必填的新数据数组"},
                        "confirmed": {"type": "boolean", "description": "删除确认标记，首次调用预览数据，传入 True 执行真实删除"}
                    },
                    "required": ["action"]
                }
            }
        }
    },
    {
        "name": "list_drive_files",
        "func": list_drive_files, 
        "definition": {
            "type": "function",
            "function": {
                "name": "list_drive_files",
                "description": "查看 Google Drive 文件列表，支持按文件名关键词搜索。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "返回数量"},
                        "query": {"type": "string", "description": "模糊搜索的文件名关键词"}
                    }
                }
            }
        }
    },
    {
        "name": "upload_file_to_drive",
        "func": upload_file_to_drive,
        "definition": {
            "type": "function",
            "function": {
                "name": "upload_file_to_drive",
                "description": "上传本地文件到 Google Drive。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "local_file_path": {"type": "string"},
                        "drive_filename": {"type": "string"}
                    },
                    "required": ["local_file_path"]
                }
            }
        }
    }
]