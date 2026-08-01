# business_vector_store.py
# 本地 SQLite 向量存储 — 按业务命名空间隔离，零外部依赖（向量库）
# 复用 retriever.py 的 get_embedding + cosine_similarity

import json
import math
import os
import sqlite3
import hashlib
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime

from agent_engine.retriever import get_embedding, cosine_similarity

_DB_PATH = Path(__file__).resolve().parent.parent / "assets" / "corpus.db"


def _get_conn() -> sqlite3.Connection:
    os.makedirs(_DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            ns TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            url TEXT,
            title TEXT,
            model TEXT,
            date TEXT,
            chunk TEXT,
            emb TEXT,
            created_at TEXT,
            PRIMARY KEY (ns, doc_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_ns ON chunks (ns)
    """)
    conn.commit()


class Chunk:
    """语料片段"""
    def __init__(self, text: str, url: str = "", title: str = "", model: str = "", date: str = "", metadata: dict = None):
        self.text = text
        self.url = url
        self.title = title
        self.model = model
        self.date = date
        self.metadata = metadata or {}


def _chunk_id(ns: str, text: str) -> str:
    """生成 chunk 唯一 ID"""
    return hashlib.md5(f"{ns}::{text}".encode()).hexdigest()


def _split_text(text: str, max_chars: int = 500, overlap: int = 50) -> List[str]:
    """按最大字符数切片，带重叠"""
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        # 尽量在句号/换行处截断
        if end < len(text):
            for punct in ["\n", "。", "!", "?", "；", ";"]:
                pos = text.rfind(punct, start, end + 1)
                if pos > start + max_chars // 2:
                    end = pos + 1
                    break
        chunks.append(text[start:end].strip())
        start = end - overlap if end < len(text) else end
    return chunks


# ── 公共接口 ──

def upsert(ns: str, chunks: List[Chunk]) -> int:
    """
    批量写入/更新语料片段。
    对每个 chunk 计算 embedding 后写入 SQLite，按 (ns, doc_id) 去重。
    返回实际写入条数。
    """
    conn = _get_conn()
    inserted = 0
    now = datetime.now().isoformat()

    for ch in chunks:
        if not ch.text or len(ch.text) < 10:
            continue

        doc_id = _chunk_id(ns, ch.text)
        # 检查是否已存在
        cur = conn.execute(
            "SELECT 1 FROM chunks WHERE ns = ? AND doc_id = ?",
            (ns, doc_id)
        )
        if cur.fetchone():
            continue

        emb = get_embedding(ch.text)
        if not emb:
            continue

        conn.execute(
            """INSERT INTO chunks (ns, doc_id, url, title, model, date, chunk, emb, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ns, doc_id, ch.url, ch.title, ch.model, ch.date, ch.text,
             json.dumps(emb), now)
        )
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


def retrieve(ns: str, query: str, top_k: int = 5) -> List[Dict]:
    """
    在指定命名空间检索 Top-K 相关片段。
    返回 [{doc_id, url, title, model, date, chunk, score}, ...]
    """
    conn = _get_conn()
    cur = conn.execute(
        "SELECT doc_id, url, title, model, date, chunk, emb FROM chunks WHERE ns = ?",
        (ns,)
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return []

    q_emb = get_embedding(query)
    if not q_emb:
        return []

    scored = []
    for doc_id, url, title, model, date, chunk, emb_json in rows:
        try:
            emb = json.loads(emb_json)
        except (json.JSONDecodeError, TypeError):
            continue
        score = cosine_similarity(q_emb, emb)
        scored.append({
            "doc_id": doc_id,
            "url": url,
            "title": title,
            "model": model,
            "date": date,
            "chunk": chunk,
            "score": score,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def list_ns() -> List[str]:
    """列出所有已存在的命名空间"""
    conn = _get_conn()
    cur = conn.execute("SELECT DISTINCT ns FROM chunks")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def count(ns: str) -> int:
    """返回指定命名空间的 chunk 数量"""
    conn = _get_conn()
    cur = conn.execute("SELECT COUNT(*) FROM chunks WHERE ns = ?", (ns,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0


def clear_ns(ns: str) -> int:
    """清空指定命名空间的所有数据，返回删除条数"""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM chunks WHERE ns = ?", (ns,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted
