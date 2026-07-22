# business/asset_registry.py
# 业务资产注册表 — 可插拔存储后端（本地 JSON / Mem0 记忆 / 未来数据库）
# 核心原则：业务名 → 资源定位 是确定性查表，绝不走 LLM 模糊匹配

import os
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict


@dataclass
class BusinessAsset:
    """一条业务资产记录"""
    alias: str                          # 业务别名（如 "奖金表"、"邀约表"）
    type: str = "google_sheet"          # 资源类型：google_sheet / google_doc / local_file / db_table
    drive_file_id: Optional[str] = None # Google Drive 文件 ID（精确直达）
    columns: List[str] = field(default_factory=list)   # 表结构列名
    allowed_ops: List[str] = field(default_factory=lambda: ["read", "append", "update"])  # 允许的操作
    description: str = ""               # 业务描述
    confirmed: bool = True              # 是否已确认（自动同步的默认 False）

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BusinessAsset":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class AssetRegistry(ABC):
    """资产注册表抽象基类 — 可插拔存储后端"""

    @abstractmethod
    def get(self, name: str) -> Optional[BusinessAsset]:
        """精确查表：按业务别名获取资产。找不到返回 None"""
        ...

    @abstractmethod
    def list_all(self) -> List[BusinessAsset]:
        """列出所有已注册业务资产"""
        ...

    @abstractmethod
    def register(self, asset: BusinessAsset) -> None:
        """注册/更新一条业务资产"""
        ...

    @abstractmethod
    def remove(self, name: str) -> bool:
        """移除一条业务资产"""
        ...

    @abstractmethod
    def list_names(self) -> List[str]:
        """列出所有业务别名（用于提示和报错）"""
        ...

    def sync_from_drive(self, limit: int = 50) -> List[BusinessAsset]:
        """从 Google Drive 自动获取表格清单（需 Google API 认证）。
        返回新发现的资产列表（标记为未确认）。
        子类可选实现，默认空列表。"""
        try:
            from agent_engine.tools.tool_drive import authenticate_drive
            from googleapiclient.discovery import build

            creds = authenticate_drive()
            service = build('drive', 'v3', credentials=creds)
            results = service.files().list(
                pageSize=limit,
                q="mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                fields="files(id, name, mimeType)",
                orderBy="modifiedTime desc"
            ).execute()

            new_assets = []
            for f in results.get('files', []):
                name = f['name']
                file_id = f['id']
                # 如果已存在则跳过
                existing = self.get(name)
                if existing:
                    if existing.drive_file_id != file_id:
                        # 更新 file_id
                        existing.drive_file_id = file_id
                        self.register(existing)
                    continue
                # 新发现的资产
                asset = BusinessAsset(
                    alias=name,
                    type="google_sheet",
                    drive_file_id=file_id,
                    description=f"从 Drive 自动同步: {name}",
                    confirmed=False  # 标记为未确认，等待人工审核
                )
                self.register(asset)
                new_assets.append(asset)

            return new_assets
        except ImportError:
            print("⚠️ Google API 未安装，无法自动同步 Drive 文件列表")
            return []
        except Exception as e:
            print(f"⚠️ Drive 自动同步失败: {e}")
            return []


# ==========================================
# 实现 1：本地 JSON 文件存储（当前默认）
# ==========================================

class LocalJsonRegistry(AssetRegistry):
    """本地 JSON 文件存储实现"""

    def __init__(self, file_path: str = None):
        if file_path is None:
            pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            file_path = os.path.join(pkg_root, "assets", "business_assets.json")
        self.file_path = file_path
        self._assets: Dict[str, BusinessAsset] = {}
        self._load()

    def _load(self):
        """从 JSON 文件加载资产"""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for item in data if isinstance(data, list) else []:
                    asset = BusinessAsset.from_dict(item)
                    self._assets[asset.alias] = asset
                print(f"✅ [LocalJsonRegistry] 已加载 {len(self._assets)} 条业务资产")
            except Exception as e:
                print(f"⚠️ [LocalJsonRegistry] 加载失败: {e}")
                self._assets = {}
        else:
            print(f"📝 [LocalJsonRegistry] 配置文件不存在，初始化空注册表: {self.file_path}")
            self._assets = {}

    def _save(self):
        """持久化到 JSON 文件"""
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump([a.to_dict() for a in self._assets.values()], f, ensure_ascii=False, indent=2)

    def get(self, name: str) -> Optional[BusinessAsset]:
        return self._assets.get(name)

    def list_all(self) -> List[BusinessAsset]:
        return list(self._assets.values())

    def register(self, asset: BusinessAsset) -> None:
        self._assets[asset.alias] = asset
        self._save()

    def remove(self, name: str) -> bool:
        if name in self._assets:
            del self._assets[name]
            self._save()
            return True
        return False

    def list_names(self) -> List[str]:
        return list(self._assets.keys())


# ==========================================
# 实现 2：Mem0 长期记忆存储（后期可切换）
# ==========================================

class Mem0Registry(AssetRegistry):
    """基于 Mem0 长期记忆的存储实现"""

    def __init__(self):
        self._cache: Dict[str, BusinessAsset] = {}
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        try:
            from agent_engine.tools.tool_memory import MemoryManager
            manager = MemoryManager()
            results = manager.search_memory("业务资产注册表")
            for r in results:
                text = r.get('text', '')
                # 从记忆文本中解析业务资产信息
                if '业务资产:' in text:
                    try:
                        data = json.loads(text.split('业务资产:')[1].strip())
                        asset = BusinessAsset.from_dict(data)
                        self._cache[asset.alias] = asset
                    except (json.JSONDecodeError, KeyError):
                        continue
            print(f"✅ [Mem0Registry] 已从长期记忆加载 {len(self._cache)} 条业务资产")
        except Exception as e:
            print(f"⚠️ [Mem0Registry] 加载失败: {e}")
        self._loaded = True

    def _save_to_memory(self, asset: BusinessAsset):
        """写入 Mem0 长期记忆"""
        try:
            from agent_engine.tools.tool_memory import MemoryManager
            manager = MemoryManager()
            memory_text = f"业务资产: {json.dumps(asset.to_dict(), ensure_ascii=False)}"
            manager.add_memory(memory_text)
        except Exception as e:
            print(f"⚠️ [Mem0Registry] 写入记忆失败: {e}")

    def get(self, name: str) -> Optional[BusinessAsset]:
        self._ensure_loaded()
        return self._cache.get(name)

    def list_all(self) -> List[BusinessAsset]:
        self._ensure_loaded()
        return list(self._cache.values())

    def register(self, asset: BusinessAsset) -> None:
        self._ensure_loaded()
        self._cache[asset.alias] = asset
        self._save_to_memory(asset)

    def remove(self, name: str) -> bool:
        self._ensure_loaded()
        if name in self._cache:
            del self._cache[name]
            # Mem0 删除需要额外处理（通过覆盖标记）
            try:
                from agent_engine.tools.tool_memory import MemoryManager
                manager = MemoryManager()
                manager.add_memory(f"业务资产删除标记: {name}")
            except Exception:
                pass
            return True
        return False

    def list_names(self) -> List[str]:
        self._ensure_loaded()
        return list(self._cache.keys())


# ==========================================
# 全局单例
# ==========================================

_registry_instance: Optional[AssetRegistry] = None


def get_registry(backend: str = "json") -> AssetRegistry:
    """获取注册表单例。backend 可选: 'json'（默认）, 'mem0'"""
    global _registry_instance
    if _registry_instance is None:
        if backend == "mem0":
            _registry_instance = Mem0Registry()
        else:
            _registry_instance = LocalJsonRegistry()
    return _registry_instance
