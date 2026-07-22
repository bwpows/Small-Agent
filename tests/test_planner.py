import sys
import os
import json

from agent_engine.planner import generate_plan

if __name__ == "__main__":
    # 🎯 这是一个极具挑战性的宏大目标（包含搜索、写表、发邮件三个跨维度的动作）
    test_goal = "帮我搜索一下今天关于 Apple 的最新重磅新闻，把核心内容写进我的 Google Drive 报告表里，然后自动发一封邮件给 boss@example.com，标题叫《苹果今日简报》。"
    
    print(f"🎯 接收到的初始宏大目标:\n{test_goal}\n")
    print("-" * 50)
    
    # 唤醒大脑进行拆解
    task_list = generate_plan(test_goal)
    
    # 漂亮地打印出大脑的规划结果
    if task_list:
        print("\n✅ 规划成功！以下是 Planner (大脑) 拆解的 JSON 任务清单：\n")
        print(json.dumps(task_list, indent=4, ensure_ascii=False))
    else:
        print("\n❌ 规划失败，请检查模型输出或大模型 API 是否正常。")