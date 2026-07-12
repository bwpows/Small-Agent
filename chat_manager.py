import os
import json
# 关键点：从引擎导入 generate_answer，用于让 AI 自己起标题
from core.llm_engine import generate_answer

class ChatManager:
    # 锁定数据库文件路径，与 app.py 同级
    DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_history_db.json")

    @classmethod
    def load_chats(cls):
        """从 JSON 数据库加载所有历史对话"""
        if not os.path.exists(cls.DB_FILE):
            return {"新对话 1": []}
        try:
            with open(cls.DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if data else {"新对话 1": []}
        except (json.JSONDecodeError, Exception):
            return {"新对话 1": []}

    @classmethod
    def save_chats(cls, all_chats):
        """将当前内存中的对话实时保存到 JSON 数据库"""
        with open(cls.DB_FILE, "w", encoding="utf-8") as f:
            json.dump(all_chats, f, ensure_ascii=False, indent=4)

    @classmethod
    def generate_chat_title(cls, first_message):
        """🌟 新增：调用 LLM 给对话起标题"""
        # 给模型下达简短总结的指令
        prompt = f"请根据这句话，给这段对话起一个 4-8 个字的简短标题，直接返回标题内容，不要带引号、不要标点：{first_message}"
        
        # 调用你的大脑，注意这里不需要联网，所以 web_info=False
        title = generate_answer(prompt, recent_history=[], parsed_memories=[], web_info=False)
        
        # 简单清洗：防止大模型偶尔产生的废话
        clean_title = title.strip().replace('"', '').replace("'", "")
        return clean_title if clean_title else "新对话"

    @classmethod
    def add_new_chat(cls, all_chats, first_message=None):
        """新建对话时，自动调用 LLM 生成标题"""
        
        # 如果有第一条消息，就调用 AI 起名；没有则用默认名
        if first_message:
            title = cls.generate_chat_title(first_message)
        else:
            title = "新对话"
        
        # 防止标题重复 (如果标题已存在，则追加数字序号)
        final_title = title
        counter = 1
        while final_title in all_chats:
            final_title = f"{title}_{counter}"
            counter += 1
            
        all_chats[final_title] = []
        cls.save_chats(all_chats)
        return final_title