"""
business/paths.py
统一语料库（corpus.db）路径解析，消除多路径歧义。
原先项目里存在 ./corpus.db 与 src/agent_engine/assets/corpus.db 两个位置，
极易在部署/迁移时踩坑。这里集中解析为单一可信路径。
"""
import os
from pathlib import Path

# 语料库目录：src/agent_engine/assets（crawler 写入位置，与仓库同生命周期）
# 注意：历史上曾误放在 ./corpus.db 与 src/agent_engine/business/assets/corpus.db，
# 统一收敛到 业务层上层的 assets 目录，作为唯一可信路径。
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_DEFAULT_DB = _ASSETS_DIR / "corpus.db"

# 允许通过环境变量 CORPUS_DB_PATH 覆盖（生产/测试场景）
_OVERRIDE = os.getenv("CORPUS_DB_PATH")


def get_corpus_db_path() -> str:
    """返回唯一的 corpus.db 绝对路径。

    解析顺序：
      1. 环境变量 CORPUS_DB_PATH（最高优先级，便于测试/部署切换）
      2. src/agent_engine/assets/corpus.db（默认，crawler 写入处）
    """
    if _OVERRIDE:
        return os.path.abspath(_OVERRIDE)
    return str(_DEFAULT_DB)


def ensure_corpus_dir() -> None:
    """确保语料库所在目录存在（首次写入前调用）。"""
    _DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
