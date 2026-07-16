import os
import json
import importlib
import datetime
import re
from core.llm_client import get_llm_client
from core.json_utils import robust_parse

# ==========================================
# 🌟 全自动动态工具加载引擎 
# ==========================================
_DYNAMIC_TOOLS = {}      
_TOOLS_DEFINITIONS = []  

def discover_and_load_tools():
    global _DYNAMIC_TOOLS, _TOOLS_DEFINITIONS
    if _DYNAMIC_TOOLS: return
    tools_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
    for filename in os.listdir(tools_dir):
        if filename.startswith("tool_") and filename.endswith(".py"):
            module_name = f"tools.{filename[:-3]}"
            try:
                module = importlib.import_module(module_name)
                group_registry = getattr(module, "REGISTER_TOOLS", None)
                if group_registry:
                    for tool in group_registry:
                        _DYNAMIC_TOOLS[tool["name"]] = tool["func"]
                        _TOOLS_DEFINITIONS.append(tool["definition"])
                    continue
                reg_name = getattr(module, "REGISTER_NAME", None)
                tool_def = getattr(module, "TOOL_DEFINITION", None)
                exec_func = getattr(module, reg_name, None) if reg_name else None
                if reg_name and tool_def and exec_func:
                    _DYNAMIC_TOOLS[reg_name] = exec_func
                    _TOOLS_DEFINITIONS.append(tool_def)
            except Exception as e: pass

discover_and_load_tools()

def get_tools_definition():
    return _TOOLS_DEFINITIONS

def execute_tool(tool_name, arguments):
    try:
        if tool_name in _DYNAMIC_TOOLS:
            result = _DYNAMIC_TOOLS[tool_name](**arguments)
        else:
            result = f"❌ 未知工具: {tool_name}"
        return result
    except Exception as e:
        return f"❌ 工具执行崩溃: {str(e)}"

# ==========================================
# 2. Agent 核心大脑 (终极防死循环 + 强力参数拦截)
# ==========================================
def generate_answer(user_input, recent_history, parsed_memories, web_info, ui_status=None, forced_tools=None):
    current_time = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M")
    memory_text = "\n".join([f"- {m['text']}" for m in parsed_memories]) if parsed_memories else "无相关长期记忆。"
    
    system_prompt = f"""你是一个具备全自动化能力的超级智能助理（Agent OS）。
当前系统时间：{current_time}。
【用户的长期记忆】：\n{memory_text}

【⚙️ 物理边界与执行铁律 (最高优先级)】
1. 🛠️ 绝对权限与严禁推脱：你已完美接入系统，拥有操作 Google Drive 及本地文件的【最高绝对权限】！绝对禁止以"缺少相关权限"、"AI无法直接操作"、"工具不支持"等任何借口拒绝用户。只要用户要求查看或修改数据，必须立刻检索并调用你的工具箱（如 manage_sheet_rows 等）去执行！
2. 🚫 严禁虚构执行：未实际调用写入工具时，绝对不允许编造"已添加/已写入"。
3. 🧱 强制参数拦截：如果用户指令缺失必填的核心身份参数（如手机号、姓名），立刻停止调用工具，直接反问用户获取缺失信息。
4. 🪞 报错透明化：工具抛出异常时，立即终止后续动作并如实报告。

【📝 输出与格式规范】
1. 🎯 拒绝废话：直接给出结果。
2. 📊 结构化呈现：多条数据必须使用 Markdown 表格或无序列表。
3. 🧊 情绪克制：保持专业、冷静、极简的专家语气。
"""

    messages = [{"role": "system", "content": system_prompt}]
    
    # 🌟 显式工具路由拦截：如果传入了 forced_tools，在提示词里加上最高权重指令
    all_tools = get_tools_definition()
    active_tools = []
    
    if forced_tools and len(forced_tools) > 0:
        active_tools = [t for t in all_tools if t["function"]["name"] in forced_tools]
        tool_names = ", ".join(forced_tools)
        messages.append({"role": "system", "content": f"🚨 用户已强制指定使用以下工具：【{tool_names}】。请优先使用这些工具来完成任务！"})
    else:
        active_tools = all_tools

    if recent_history:
        for msg in recent_history:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_input})

    client, model_name = get_llm_client()
    actual_write_success = False
    max_loops = 4  
    error_count = 0

    for step in range(max_loops):
        try:
            kwargs = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.2,
            }
            if active_tools:
                # 确保工具格式符合 OpenAI 规范：必须有 "type": "function"
                normalized_tools = []
                for t in active_tools:
                    if "type" not in t:
                        normalized_tools.append({"type": "function", "function": t["function"]})
                    else:
                        normalized_tools.append(t)
                kwargs["tools"] = normalized_tools

            response = client.chat.completions.create(**kwargs)
            message_obj = response.choices[0].message
            content = message_obj.content or ""
            
            tool_called_this_step = False
            func_name = None
            args = {}

            # --- 解析 JSON 工具调用（加固：自动修复参数 JSON）---
            if message_obj.tool_calls:
                tc = message_obj.tool_calls[0]
                func_name = tc.function.name
                args_str = tc.function.arguments
                parsed = robust_parse(args_str, expect_array=False)
                args = parsed if isinstance(parsed, dict) else {}
                tool_called_this_step = True

            # --- 解析 正则 XML 工具调用 ---
            elif "<function=" in content or "<tool_call>" in content:
                if "<function=" in content:
                    match1 = re.search(r"<function=(.*?)>", content)
                    if match1:
                        func_name = match1.group(1).strip()
                        for p in re.finditer(r"<parameter=(.*?)>(.*?)</parameter>", content, re.DOTALL):
                            args[p.group(1).strip()] = p.group(2).strip()
                elif "<tool_call>" in content:
                    match2 = re.search(r"<tool_call>(.*?)</tool_call>", content, re.DOTALL)
                    if match2:
                        try:
                            tool_data = json.loads(match2.group(1).strip())
                            func_name = tool_data.get("name")
                            args = tool_data.get("arguments", {})
                        except: pass
                if func_name: tool_called_this_step = True

            # 🌟 工具执行逻辑 🌟
            if tool_called_this_step and func_name:
                print(f"⚙️ [循环回合 {step+1}] 执行工具: {func_name}, 参数: {args}")
                
                # 🌟 如果传入了 ui_status，把底层调用动态写回前端
                if ui_status:
                    ui_status.write(f"⚙️ 正在调用工具: `{func_name}` ...")
                    
                exec_result = execute_tool(func_name, args)
                
                if "✅ 成功" in str(exec_result) and ("drive" in func_name or "write" in func_name or "manage" in func_name):
                    actual_write_success = True
                
                if message_obj.tool_calls:
                    # 标准协议：追加 assistant 消息（含 tool_calls）
                    tc_list = []
                    for tc in message_obj.tool_calls:
                        tc_list.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        })
                    messages.append({
                        "role": "assistant",
                        "content": message_obj.content,
                        "tool_calls": tc_list,
                    })
                    # 追加标准 tool 角色结果消息（必须为每个 tool_call_id 都提供响应）
                    for tc in message_obj.tool_calls:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": str(exec_result) if tc.id == message_obj.tool_calls[0].id else "（此工具未被独立执行，请参考已获取的数据）",
                        })
                    # 补一条 user 消息做总结提示
                    messages.append({
                        "role": "user",
                        "content": "数据已获取！请基于以上真实数据，直接用中文回答用户问题，不要再次调用工具。",
                    })
                else:
                    # XML/正则 兜底路径：保持原有 user 角色（无 tool_call_id 可用）
                    messages.append({"role": "assistant", "content": content})
                    nudge_prompt = f"系统已自动执行工具 `{func_name}`，拿到以下真实数据：\n```text\n{exec_result}\n```\n【最高指令】：数据已获取！请立刻基于上述数据，直接用中文回答用户的问题，绝不允许再次调用该工具！"
                    messages.append({"role": "user", "content": nudge_prompt})
                continue  

            # ==========================================
            # 🚨 真正拦截纠错防线
            # ==========================================
            if not tool_called_this_step:
                fake_write_claims = ["成功添加", "已成功写入", "已为您加", "成功插入记录", "已添加到"]
                ai_claims_fake_write = any(kw in content for kw in fake_write_claims)
                
                if ai_claims_fake_write and not actual_write_success:
                    print(f"🚨 [第{step+1}回合] 拦截虚假写入！准备打回重做...")
                    if ui_status:
                        ui_status.write("🚨 拦截到虚假操作，正在强制重试...")
                    error_count += 1 
                    warning_prompt = "🚨 **系统强制纠错**：你并未真正调用写工具却声称已添加！如果用户指令缺失关键参数（如手机号），立刻反问用户；如果参数齐全，请生成工具调用指令！"
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": warning_prompt})
                    continue

                if content.strip():
                    if error_count > 0:
                        return f"*(🤖 自动拦截虚假操作，后台纠错 {error_count} 次后返回：)*\n\n{content}"
                    return content
                else:
                    # 修复 Ollama 偶尔吐出纯空字符导致卡死的 Bug
                    messages.append({"role": "user", "content": "你刚才返回了空内容。请根据获取的数据直接输出最终的中文回答。"})
                    continue
                
        except Exception as e:
            import traceback
            return f"❌ 底层思考引擎在第 {step+1} 回合崩溃:\n```python\n{traceback.format_exc()}\n```"

    return "🚨 Agent 在后台连续尝试多次均陷入死循环。这通常是因为大模型固执地拒绝总结数据，请尝试精简指令或更换大模型。"