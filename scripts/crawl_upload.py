"""
scripts/crawl_upload.py
把本地手动准备好的 corpus.db 覆盖更新到 Google Drive（共享位置）。

用法：
    PYTHONPATH=src ./venv/bin/python scripts/crawl_upload.py

环境变量：
    CORPUS_DB_PATH          本地 corpus.db 路径（默认 src/agent_engine/assets/corpus.db）
    CORPUS_DRIVE_FILENAME   上传到 Drive 的文件名（默认 corpus.db）
    CORPUS_DRIVE_FOLDER_ID  目标父文件夹 / 共享云端硬盘 ID（必填，SA 不能写 My Drive 根）
    GOOGLE_SERVICE_ACCOUNT_JSON / _FILE / service_account.json  Drive 凭据（已在 .env）

行为：若 Drive 上已有同名文件，则原地覆盖更新（保留同一云端 ID），不重复堆积。
"""
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scripts.crawl_upload")

# 保证能 import src 下的包
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main():
    import agent_engine.config  # 触发 .env 加载

    local_db = os.getenv("CORPUS_DB_PATH") or os.path.join(
        _ROOT, "src", "agent_engine", "assets", "corpus.db"
    )
    drive_filename = os.getenv("CORPUS_DRIVE_FILENAME", "corpus.db")
    folder_id = os.getenv("CORPUS_DRIVE_FOLDER_ID")

    if not os.path.exists(local_db):
        logger.error(f"本地文件不存在: {local_db}")
        return

    if not folder_id:
        logger.error(
            "未设置 CORPUS_DRIVE_FOLDER_ID。Service Account 无法上传到 My Drive 根目录"
            "（会报 403 storageQuotaExceeded）。请在 .env 中填入目标共享云端硬盘"
            "或已共享给本 Service Account 的文件夹 ID 后重试。"
        )
        return

    from agent_engine.tools import tool_drive
    logger.info(f"上传 {local_db} -> Drive 文件名 {drive_filename} (folder={folder_id})")
    result = tool_drive.upload_file_to_drive(
        local_db, drive_filename, parent_folder_id=folder_id
    )
    logger.info(result)


if __name__ == "__main__":
    main()
