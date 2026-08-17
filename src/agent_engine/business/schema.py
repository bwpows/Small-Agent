"""
business/schema.py
统一业务语料层的数据契约，消除层间字段名歧义。
所有通过 retrieve() 返回的命中对象都用 RetrievalHit 表示，
消费方（chat_service / planner / tools）统一读取 .text / .title / .url 等属性。
"""
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class RetrievalHit:
    """业务语料检索命中结果（统一契约）。

    字段含义：
      text      检索命中的正文（消费方唯一读取入口，消除 chunk/text 歧义）
      title     语料标题（含切片序号）
      url       来源 URL
      model     车型代号（如 'L06'），用于车型级过滤
      version   版本名（如 '560Max'），用于版本级过滤，可为空
      date      发布日期，可为空
      score     相似度得分，可选
    """
    text: str
    title: str = ""
    url: str = ""
    model: str = ""
    version: str = ""
    date: str = ""
    score: Optional[float] = None

    def to_prompt_block(self) -> str:
        """把命中格式化为可注入 prompt 的文本块。"""
        head = f"【{self.title or '业务语料'}】"
        if self.url:
            head += f" (来源: {self.url})"
        return f"{head}\n{self.text}"


def hits_to_web_info(hits: List["RetrievalHit"]) -> str:
    """把命中列表拼成注入 system prompt 的 web_info 文本。"""
    if not hits:
        return ""
    return "\n\n".join(h.to_prompt_block() for h in hits)
