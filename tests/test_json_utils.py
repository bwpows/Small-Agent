"""快速验证 json_utils 修复引擎（无需 LLM）"""
from agent_engine.json_utils import robust_parse, extract_json, validate_task_list

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        print(f"✅ {name}")
        passed += 1
    else:
        print(f"❌ {name}")
        failed += 1

# 1: 正常 JSON
r = robust_parse('{"tasks": [{"task_id": 1}]}', expect_array=False)
check("正常 JSON 解析", isinstance(r, dict) and "tasks" in r)

# 2: Markdown 包裹
raw = '```json\n{"tasks": [{"task_id": 1}]}\n```'
r = robust_parse(raw, expect_array=False)
check("Markdown 包裹提取", isinstance(r, dict))

# 3: 尾部逗号修复
raw = '{"tasks": [{"task_id": 1, "action": "test",}],}'
r = robust_parse(raw, expect_array=False)
check("尾部逗号修复", isinstance(r, dict))

# 4: 未加引号 key
raw = '{tasks: [{"task_id": 1}]}'
r = robust_parse(raw, expect_array=False)
check("未加引号 key 修复", isinstance(r, dict))

# 5: 前后有废话
raw = '介绍文本 {"tasks": [{"task_id": 1}]} 结尾说明'
r = robust_parse(raw, expect_array=False)
check("混合文本提取", isinstance(r, dict))

# 6: Schema 校验 - 缺失字段自动补全
raw = [
    {"action": "搜索", "agent_role": "researcher", "instruction": "搜新闻",
     "risk_level": "low", "risk_details": "只读"},
    {"action": "缺失大部分字段"},  # 缺很多
    {"task_id": 2, "action": "发送", "agent_role": "coder", "depends_on": [1],
     "instruction": "发邮件", "risk_level": "HIGH", "risk_details": "发邮件"},
]
v = validate_task_list(raw)
check("Schema: 不应丢弃任何任务", len(v) == 3)
check("Schema: 自动分配 task_id", v[0]["task_id"] == 1 and v[1]["task_id"] == 2)
check("Schema: illegal risk_level 修正为 low", v[2]["risk_level"] == "low")
check("Schema: 缺失 agent_role 补 general", v[1]["agent_role"] == "general")

# 7: 空数组返修
r = robust_parse("[]", expect_array=True)
check("空数组解析", isinstance(r, list) and len(r) == 0)

print(f"\n{'='*40}")
print(f"结果: {passed} 通过 / {passed + failed} 总计")
if failed:
    print("⚠️  存在失败用例！")
else:
    print("🎉 全部通过！JSON 保障引擎运转正常。")
