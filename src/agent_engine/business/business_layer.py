"""
business/business_layer.py
业务语料层统一门面：
- crawl(): 抓取并写入语料
- retrieve(): 语义检索（车型级 / 版本级过滤），返回 RetrievalHit
- registry: 业务注册表（alias -> namespace）
"""
import logging
from typing import List, Optional

from agent_engine.business.business_vector_store import BusinessVectorStore
from agent_engine.business.asset_registry import get_registry
from agent_engine.business.schema import RetrievalHit

logger = logging.getLogger("business.layer")


class BusinessNotFoundError(Exception):
    """业务未在注册表中声明时抛出。"""
    pass


class BusinessLayer:
    def __init__(self):
        self.store = BusinessVectorStore()
        self.registry = get_registry()

    def crawl(self, business_name: str, config: Optional[dict] = None) -> dict:
        entry = self.registry.get(business_name)
        if not entry:
            raise ValueError(f"未知业务：{business_name}，请先在注册表中声明")
        ns = entry.vector_ns or entry.alias
        logger.info(f"[crawl] 业务={business_name} ns={ns}")
        # 惰性导入：playwright 仅在真正爬取时需要，避免线上检索服务强依赖爬虫环境
        from agent_engine.tools.tool_crawler import crawl_to_chunks
        chunks = crawl_to_chunks(config)
        self.store.upsert(ns, chunks, clear_ns=True)
        return {"namespace": ns, "chunks": len(chunks)}

    def retrieve(
        self,
        business_name: str,
        query: str,
        top_k: int = 10,
        model_filter: Optional[List[str]] = None,
        version_filter: Optional[List[str]] = None,
    ) -> List[RetrievalHit]:
        entry = self.registry.get(business_name)
        if not entry:
            logger.warning(f"[retrieve] 未注册业务：{business_name}")
            return []
        ns = entry.vector_ns or entry.alias
        return self.store.retrieve(
            ns,
            query,
            top_k=top_k,
            model_filter=model_filter,
            version_filter=version_filter,
        )

    def get_namespace(self, business_name: str) -> Optional[str]:
        entry = self.registry.get(business_name)
        return (entry.vector_ns or entry.alias) if entry else None

    def list_models(self, business_name: str) -> List[str]:
        """从语料库动态返回该业务下已建索引的全部车型代号（去重）。

        替代原先硬编码车型列表的做法：车型增减只需重建语料，无需改业务代码。
        排除非车型类型的整表切片（car_series / news 等 article_type 占位）。
        """
        entry = self.registry.get(business_name)
        if not entry:
            return []
        ns = entry.vector_ns or entry.alias
        _NON_MODEL = ("car_series", "news")
        return [m for m in self.store.distinct_models(ns) if m not in _NON_MODEL]

    def list_versions(self, business_name: str, model: Optional[str] = None) -> List[str]:
        """从语料库动态返回该业务（可选地限定车型）下全部版本名（去重）。

        供入口侧识别用户问题中出现的版本名，进而做版本级精确检索。
        """
        entry = self.registry.get(business_name)
        if not entry:
            return []
        ns = entry.vector_ns or entry.alias
        return self.store.distinct_versions(ns, model_filter=[model] if model else None)


_layer_instance = None


def get_business_layer() -> BusinessLayer:
    global _layer_instance
    if _layer_instance is None:
        _layer_instance = BusinessLayer()
    return _layer_instance
