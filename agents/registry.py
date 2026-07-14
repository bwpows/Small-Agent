# ==========================================
# 🌟 专家注册表 (百人级架构底座)
# ==========================================
AGENT_ROSTER = {
    "researcher": {
        "class_name": "ResearcherAgent",
        "desc": "调研专家。专精：联网搜索新闻、查阅资料、搜集全网情报。无本地修改权限。"
    },
    "coder": {
        "class_name": "CoderAgent",
        "desc": "编程/执行专家。专精：读写本地文件、数据处理、操作云盘、发送邮件等落地执行操作。"
    },
    "googledrive": {
        "class_name": "GoogleDriveAgent",
        "desc": "Google Drive 管理专家。专精：管理和操作用户在 Google Drive 上的文件和数据。"
    }
    # 未来你可以在这里无限添加新专家，比如：
    # "translator": { "class_name": "TranslatorAgent", "desc": "翻译专家..." }
}