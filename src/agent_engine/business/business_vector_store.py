"""
business/business_vector_store.py
业务语料向量存储层：
- 基于 SQLite + 本地 embedding（siliconflow）实现轻量向量检索
- 提供按 model / version 精确过滤的检索能力
- retrieve() 返回统一契约 RetrievalHit，消除字段名歧义
"""
import os
import sqlite3
import json
import logging
from typing import List, Optional

import numpy as np
from agent_engine.config import EMBED_PROVIDER, VECTOR_DIM
from agent_engine.retriever import get_embedding
from agent_engine.business.schema import RetrievalHit
from agent_engine.business.paths import get_corpus_db_path, ensure_corpus_dir

logger = logging.getLogger("business.vector_store")

# 相关性下限（余弦相似度）：低于此分的结果视为不相关，会被丢弃，避免答非所问注入幻觉
SIM_MIN = float(os.environ.get("CORPUS_SIM_MIN", "0.30"))
# query 侧 embedding 超长截断档位（与 chunk 切片一致，规避 provider 长度限制）
_QUERY_MAX_CHARS = 512


class BusinessVectorStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_corpus_db_path()
        ensure_corpus_dir()
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT,
                ns TEXT,
                url TEXT,
                title TEXT,
                model TEXT,
                version TEXT DEFAULT '',
                date TEXT,
                chunk TEXT,
                emb BLOB
            )
        """)
        # 若已存在的表缺少 version 列，则补齐（向后兼容旧库）
        cur.execute("PRAGMA table_info(chunks)")
        cols = {r["name"] for r in cur.fetchall()}
        if "version" not in cols:
            cur.execute("ALTER TABLE chunks ADD COLUMN version TEXT DEFAULT ''")
            logger.info("已为 chunks 表补齐 version 列")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_ns ON chunks(ns)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_model ON chunks(ns, model)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_version ON chunks(ns, model, version)")
        conn.commit()
        conn.close()

    def _embed_with_retry(self, text: str):
        """embedding 带重试：超限时逐次截断到安全长度再试。"""
        candidates = [text, text[:400], text[:300], text[:200]]
        for cand in candidates:
            try:
                emb = get_embedding(cand)
                if emb:
                    return np.array(emb, dtype=np.float32)
            except Exception as e:
                logger.warning(f"embedding 失败（将尝试截断重试）: {e}")
        logger.error("embedding 多次重试仍失败，跳过该 chunk")
        return None

    def upsert(self, ns: str, chunks: List[dict], clear_ns: bool = True):
        """批量写入语料。chunks 元素需含 text/url/title/model/date，可选 version。

        单条 embedding 失败时截断重试，仍失败则跳过该条（不写空向量污染库）。
        维度保护：若 embedding 实际维度与 VECTOR_DIM 不一致，记录告警并跳过，避免维度
        冲突导致后续余弦相似度计算出错。
        失败计数：跳过条数超过半数时升级为 error 日志，便于发现批量 embedding 故障。
        """
        conn = self._conn()
        cur = conn.cursor()
        if clear_ns:
            cur.execute("DELETE FROM chunks WHERE ns=?", (ns,))
        ok = 0
        skipped = 0
        for i, c in enumerate(chunks):
            emb = self._embed_with_retry(c["text"])
            if emb is None:
                skipped += 1
                continue
            if VECTOR_DIM and emb.shape[0] != VECTOR_DIM:
                logger.error(
                    f"[{ns}] embedding 维度({emb.shape[0]})与配置 VECTOR_DIM({VECTOR_DIM})不一致，"
                    f"跳过 doc_id={c.get('doc_id', i)}（疑似 provider/模型切换，需重建语料库）"
                )
                skipped += 1
                continue
            emb_bin = emb.tobytes()
            cur.execute(
                """INSERT INTO chunks (doc_id, ns, url, title, model, version, date, chunk, emb)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    c.get("doc_id", f"{ns}-{i}"),
                    ns,
                    c.get("url", ""),
                    c.get("title", ""),
                    c.get("model", ""),
                    c.get("version", ""),
                    c.get("date", ""),
                    c["text"],
                    emb_bin,
                ),
            )
            ok += 1
        conn.commit()
        conn.close()
        level = logger.error if skipped > len(chunks) / 2 else logger.info
        level(f"[{ns}] 写入 {ok}/{len(chunks)} 条语料，跳过 {skipped} 条")

    def _cosine(self, a: np.ndarray, b: np.ndarray) -> float:
        if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
            return 0.0
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    def retrieve(
        self,
        ns: str,
        query: str,
        top_k: int = 10,
        model_filter: Optional[List[str]] = None,
        version_filter: Optional[List[str]] = None,
    ) -> List[RetrievalHit]:
        """语义检索，支持车型级(model)与版本级(version)精确过滤。

        返回统一契约 RetrievalHit 列表，消费方统一读取 .text。
        - query 超长时自动截断重试，避免 provider 长度限制导致整次检索失败
        - 维度不一致的行（旧库/模型切换）跳过并告警，不抛出崩溃
        - 低于 SIM_MIN 的结果被丢弃，至多返回 top_k 条
        """
        if len(query) > _QUERY_MAX_CHARS:
            logger.warning(f"query 长度 {len(query)} 超过 {_QUERY_MAX_CHARS}，已截断以避免 embedding 超限")
            query = query[:_QUERY_MAX_CHARS]
        q_emb = self._embed_with_retry(query)
        if q_emb is None:
            logger.error("query embedding 失败，检索终止，返回空结果")
            return []

        conn = self._conn()
        cur = conn.cursor()
        sql = "SELECT * FROM chunks WHERE ns=?"
        params: list = [ns]
        if model_filter:
            placeholders = ",".join("?" * len(model_filter))
            sql += f" AND model IN ({placeholders})"
            params.extend(model_filter)
        if version_filter:
            placeholders = ",".join("?" * len(version_filter))
            sql += f" AND version IN ({placeholders})"
            params.extend(version_filter)
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()

        if not rows:
            logger.info(f"[{ns}] 检索无候选（ns={ns}, model={model_filter}, version={version_filter}），语料库可能为空")
            return []

        scored = []
        dim_mismatch = 0
        for r in rows:
            raw = r["emb"]
            try:
                if isinstance(raw, bytes):
                    emb = np.frombuffer(raw, dtype=np.float32)
                else:
                    # 兼容旧库：embedding 以文本/JSON 形式存储
                    emb = np.array(json.loads(raw), dtype=np.float32)
            except Exception as e:
                logger.warning(f"解析 embedding 失败，跳过 doc_id={r['doc_id']}: {e}")
                continue
            if VECTOR_DIM and emb.shape[0] != VECTOR_DIM:
                dim_mismatch += 1
                continue
            score = self._cosine(q_emb, emb)
            if score < SIM_MIN:
                continue
            hit = RetrievalHit(
                text=r["chunk"],
                title=r["title"],
                url=r["url"],
                model=r["model"],
                version=r["version"] or "",
                date=r["date"] or "",
                score=score,
            )
            scored.append(hit)
        if dim_mismatch:
            logger.warning(f"[{ns}] 跳过 {dim_mismatch} 条维度不匹配的语料（需重建语料库）")
        scored.sort(key=lambda x: x.score or 0.0, reverse=True)
        return scored[:top_k]

    def distinct_models(self, ns: str) -> List[str]:
        """返回该命名空间下全部已建索引的车型代号（去重，按出现顺序）。"""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT model FROM chunks WHERE ns=? AND model<>''", (ns,))
        rows = cur.fetchall()
        conn.close()
        seen = []
        for r in rows:
            m = r["model"]
            if m and m not in seen:
                seen.append(m)
        return seen

    def distinct_versions(self, ns: str, model_filter: Optional[List[str]] = None) -> List[str]:
        """返回该命名空间下全部已建索引的版本名（去重，按出现顺序）。可限定车型。"""
        conn = self._conn()
        cur = conn.cursor()
        sql = "SELECT DISTINCT version FROM chunks WHERE ns=? AND version<>''"
        params: list = [ns]
        if model_filter:
            placeholders = ",".join("?" * len(model_filter))
            sql += f" AND model IN ({placeholders})"
            params.extend(model_filter)
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        seen = []
        for r in rows:
            v = r["version"]
            if v and v not in seen:
                seen.append(v)
        return seen
