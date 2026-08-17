"""
tools/tool_corpus.py
业务语料检索工具——把 web_corpus 作为统一调度的数据源（一等公民），
而非仅在入口旁路注入。planner / ReAct 均可显式调用。
"""
import logging
from agent_engine.business import get_business_layer
from agent_engine.business.schema import hits_to_web_info

logger = logging.getLogger("tools.corpus")


def retrieve_corpus(query: str, business: str = "深蓝", top_k: int = 10,
                    model: str = "", version: str = "") -> str:
    """
    从业务语料库（如深蓝官网）检索结构化信息。

    适用场景：
      - 用户询问某汽车品牌的车型、新闻、具体车型配置、各版本差异等
      - 需要基于官方语料作答，而非联网搜索或编造

    参数：
      query:   检索问题，例如「L06 有几个版本」「S07 续航」
      business:业务别名，需是注册表中已声明的业务（默认「深蓝」）
      top_k:   返回的最大片段数
      model:   车型代号过滤（如 L06），为空表示不限
      version: 版本名过滤（如 560Max），为空表示不限

    返回：检索到的语料文本；业务未注册或查询无结果时返回空字符串。
    """
    layer = get_business_layer()
    # 业务名校验：拒绝未注册的业务名，避免静默空结果误导调用方
    if business not in layer.registry:
        logger.warning(f"retrieve_corpus 收到未注册业务名: {business}")
        return ""
    models = [model] if model else None
    versions = [version] if version else None
    hits = layer.retrieve(
        business,
        query,
        top_k=top_k,
        model_filter=models,
        version_filter=versions,
    )
    return hits_to_web_info(hits)


REGISTER_TOOLS = [
    {
        "name": "retrieve_corpus",
        "func": retrieve_corpus,
        "definition": {
            "type": "function",
            "function": {
                "name": "retrieve_corpus",
                "description": (
                    "从本地业务语料库检索官方结构化信息（如深蓝官网的车型、新闻、配置表）。"
                    "当用户询问汽车品牌的车型列表、最新新闻、某车型各版本配置与差异时，"
                    "优先调用本工具获取权威语料，禁止联网搜索或编造库外信息。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索问题，如『L06 有几个版本』『S07 续航』"},
                        "business": {"type": "string", "description": "业务别名，默认『深蓝』", "default": "深蓝"},
                        "top_k": {"type": "integer", "description": "返回片段数，默认 10", "default": 10},
                        "model": {"type": "string", "description": "车型代号过滤，如 L06；留空表示不限", "default": ""},
                        "version": {"type": "string", "description": "版本名过滤，如 560Max；留空表示不限", "default": ""},
                    },
                    "required": ["query"],
                },
            },
        },
    }
]
