# business/business_layer.py
# 专属业务层：确定性路由 + Guardrails + 工具代理
# 核心原则：业务名 → 资源定位 100% 确定，绕过 LLM 猜测

from typing import Optional, Dict, List, Any
from business.asset_registry import (
    AssetRegistry,
    BusinessAsset,
    get_registry,
)


class BusinessNotFoundError(Exception):
    """业务未注册异常 —— 明确的报错，不让 LLM 猜"""
    def __init__(self, biz_name: str, available: List[str]):
        self.biz_name = biz_name
        self.available = available
        super().__init__(
            f"『{biz_name}』未在业务资产注册表中登记。\n"
            f"可用业务: {', '.join(available) if available else '（暂无）'}\n"
            f"请先登记该业务（或使用 '同步 Drive 文件' 自动发现）。"
        )


class BusinessLayer:
    """
    专属业务层 —— 保证 100% 精确定位。

    职责：
    1. resolve(biz_name) → 确定性查表，返回 file_id（找不到直接报错，绝不模糊匹配）
    2. 为 Planner 提供业务清单（注入到 system prompt）
    3. 代理工具调用（自动把业务名替换成 file_id）
    """

    def __init__(self, registry: AssetRegistry = None):
        self.registry = registry or get_registry()

    # ── 核心：确定性解析 ──

    def resolve(self, biz_name: str) -> BusinessAsset:
        """
        确定性解析业务名 → 资产定位。
        找不到直接抛 BusinessNotFoundError，绝不降级为模糊搜索。
        这是整个业务层"100% 正确"的基石。
        """
        asset = self.registry.get(biz_name)
        if not asset:
            available = self.registry.list_names()
            raise BusinessNotFoundError(biz_name, available)
        return asset

    def resolve_optional(self, biz_name: str) -> Optional[BusinessAsset]:
        """非严格解析：找不到返回 None（用于可选场景）"""
        return self.registry.get(biz_name)

    # ── Planner 辅助 ──

    def get_registry_prompt(self) -> str:
        """
        生成注入 Planner system prompt 的业务资产清单。
        LLM 看到这个清单后，会直接在 instruction 中使用 sheet_id。
        """
        assets = self.registry.list_all()
        if not assets:
            return "（当前无已登记的业务资产）"

        lines = ["【📋 已登记的业务资产（使用 sheet_id 直接精确定位）】"]
        for a in assets:
            ops = ", ".join(a.allowed_ops)
            confirmed = "✅" if a.confirmed else "⚠️待确认"
            cols = ", ".join(a.columns) if a.columns else "未定义"
            lines.append(
                f"- {confirmed} **{a.alias}** | sheet_id=`{a.drive_file_id}` "
                f"| 列: [{cols}] | 操作: {ops} | {a.description}"
            )
        lines.append("⚠️ 以上业务表请直接使用 sheet_id 精确定位，不要用 sheet_name 搜索！")
        return "\n".join(lines)

    def list_business_names(self) -> List[str]:
        """列出所有已注册业务名"""
        return self.registry.list_names()

    # ── 工具代理（高层封装，内部调通用 tool） ──

    def read(self, biz_name: str) -> str:
        """读取业务表全部数据"""
        asset = self.resolve(biz_name)
        from tools.tool_drive import manage_sheet_rows
        return manage_sheet_rows(
            sheet_name=asset.alias,
            sheet_id=asset.drive_file_id,
            action="read",
        )

    def append(self, biz_name: str, data_array: list) -> str:
        """向业务表追加数据"""
        asset = self.resolve(biz_name)
        from tools.tool_drive import auto_drive_manager
        return auto_drive_manager(
            sheet_name=asset.alias,
            data_array=data_array,
        )

    def update_row(self, biz_name: str, row_index: int, new_data: list) -> str:
        """更新业务表指定行"""
        asset = self.resolve(biz_name)
        from tools.tool_drive import manage_sheet_rows
        return manage_sheet_rows(
            sheet_name=asset.alias,
            sheet_id=asset.drive_file_id,
            action="update",
            row_index=row_index,
            new_data=new_data,
        )

    def delete_row(self, biz_name: str, row_index: int, confirmed: bool = False) -> str:
        """删除业务表指定行"""
        asset = self.resolve(biz_name)
        from tools.tool_drive import manage_sheet_rows
        return manage_sheet_rows(
            sheet_name=asset.alias,
            sheet_id=asset.drive_file_id,
            action="delete",
            row_index=row_index,
            confirmed=confirmed,
        )

    # ── 业务管理 ──

    def register_business(self, alias: str, drive_file_id: str,
                          columns: list = None, description: str = "",
                          type: str = "google_sheet") -> BusinessAsset:
        """手动登记业务资产"""
        asset = BusinessAsset(
            alias=alias,
            type=type,
            drive_file_id=drive_file_id,
            columns=columns or [],
            description=description,
            confirmed=True,
        )
        self.registry.register(asset)
        return asset

    def sync_from_drive(self, limit: int = 50) -> List[BusinessAsset]:
        """从 Google Drive 自动同步表格清单"""
        return self.registry.sync_from_drive(limit)


# ── 全局单例 ──

_business_layer_instance: Optional[BusinessLayer] = None


def get_business_layer() -> BusinessLayer:
    """获取业务层单例"""
    global _business_layer_instance
    if _business_layer_instance is None:
        _business_layer_instance = BusinessLayer()
    return _business_layer_instance
