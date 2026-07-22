import os
import json
import importlib
import datetime
import re
from core.llm_client import get_llm_client, get_async_llm_client
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
    """返回 OpenAI function-calling 格式的工具定义列表"""
    return _TOOLS_DEFINITIONS


def get_tools_as_mcp():
    """
    返回 MCP (Model Context Protocol) 格式的工具定义列表。
    与 OpenAI 格式等价，可被任何 MCP 客户端（Claude Desktop / Cursor / GPT）直接消费。
    
    转换规则: parameters → inputSchema, 去掉外层 type/function 包裹
    """
    mcp_tools = []
    for t in _TOOLS_DEFINITIONS:
        func = t.get("function", t)  # 兼容两种嵌套格式
        mcp_tools.append({
            "name": func["name"],
            "description": func.get("description", ""),
            "inputSchema": func.get("parameters", {"type": "object", "properties": {}}),
        })
    return mcp_tools


def export_tool_manifest(output_format: str = "openai"):
    """
    导出工具清单，支持两种格式:
    - "openai": OpenAI function-calling 格式 (默认)
    - "mcp":    MCP 标准 Tool 格式
    返回 JSON 字符串
    """
    if output_format == "mcp":
        return json.dumps({"tools": get_tools_as_mcp()}, ensure_ascii=False, indent=2)
    else:
        return json.dumps({"tools": get_tools_definition()}, ensure_ascii=False, indent=2)

def execute_tool(tool_name, arguments):
    try:
        # ── 安全参数规范化：LLM 可能传入字符串 "true"/"false" 代替布尔值 ──
        safe_args = {}
        for k, v in arguments.items():
            if isinstance(v, str) and v.lower() in ("true", "false"):
                safe_args[k] = v.lower() == "true"
            else:
                safe_args[k] = v
        if tool_name in _DYNAMIC_TOOLS:
            result = _DYNAMIC_TOOLS[tool_name](**safe_args)
        else:
            result = f"❌ 未知工具: {tool_name}"
        return result
    except Exception as e:
        return f"❌ 工具执行崩溃: {str(e)}"

# ==========================================
# 2. Agent 核心大脑 (终极防死循环 + 强力参数拦截)
# ==========================================
def _extract_usage(response) -> dict:
    """从 API 响应中提取 token 用量"""
    try:
        u = response.usage
        return {
            "prompt_tokens": u.prompt_tokens or 0,
            "completion_tokens": u.completion_tokens or 0,
            "total_tokens": u.total_tokens or 0,
        }
    except Exception:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _extract_reasoning(message_obj) -> str:
    """提取思考过程（DeepSeek reasoning_content 或 Ollama 兼容字段）"""
    reasoning = getattr(message_obj, "reasoning_content", None)
    if reasoning:
        return reasoning.strip()
    # Ollama 有些模型把思考放在 think 块或特定字段里（兼容）
    return ""


def _accumulate_usage(total: dict, step: dict) -> dict:
    """累加多轮 token 用量"""
    return {
        "prompt_tokens": total["prompt_tokens"] + step.get("prompt_tokens", 0),
        "completion_tokens": total["completion_tokens"] + step.get("completion_tokens", 0),
        "total_tokens": total["total_tokens"] + step.get("total_tokens", 0),
    }


def _make_result(content, usage=None, reasoning="", thinking_count=0):
    """工厂函数：统一返回格式"""
    return {
        "content": content,
        "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "reasoning": reasoning,
        "thinking_count": thinking_count,
    }


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

    # ── 累积 token 用量和思考过程 ──
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    all_reasoning_parts = []

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

            # 累加 token 用量
            step_usage = _extract_usage(response)
            total_usage = _accumulate_usage(total_usage, step_usage)

            # 收集思考过程
            reasoning = _extract_reasoning(message_obj)
            if reasoning:
                all_reasoning_parts.append(f"--- 回合 {step+1} 思考 ---\n{reasoning}")
            
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
                    thinking_count = len(all_reasoning_parts)
                    full_reasoning = "\n\n".join(all_reasoning_parts)
                    if error_count > 0:
                        return _make_result(
                            f"*(🤖 自动拦截虚假操作，后台纠错 {error_count} 次后返回：)*\n\n{content}",
                            total_usage, full_reasoning, thinking_count,
                        )
                    return _make_result(content, total_usage, full_reasoning, thinking_count)
                else:
                    # 修复 Ollama 偶尔吐出纯空字符导致卡死的 Bug
                    messages.append({"role": "user", "content": "你刚才返回了空内容。请根据获取的数据直接输出最终的中文回答。"})
                    continue
                
        except Exception as e:
            import traceback
            thinking_count = len(all_reasoning_parts)
            full_reasoning = "\n\n".join(all_reasoning_parts)
            return _make_result(
                f"❌ 底层思考引擎在第 {step+1} 回合崩溃:\n```python\n{traceback.format_exc()}\n```",
                total_usage, full_reasoning, thinking_count,
            )

    thinking_count = len(all_reasoning_parts)
    full_reasoning = "\n\n".join(all_reasoning_parts)
    return _make_result(
        "🚨 Agent 在后台连续尝试多次均陷入死循环。这通常是因为大模型固执地拒绝总结数据，请尝试精简指令或更换大模型。",
        total_usage, full_reasoning, thinking_count,
    )


# ==========================================
# 🔄 SSE 流式版本 — 异步 generator
# ==========================================
async def generate_answer_stream(user_input, recent_history, parsed_memories, web_info, ui_status=None, forced_tools=None):
    """
    流式版 `generate_answer`：异步 generator，逐 token 输出 SSE 事件。
    yield 格式:
      {"type": "text_delta", "content": "..."}       — 逐 token 文本
      {"type": "tool_call", "name": "...", "args": {...}}  — 开始执行工具
      {"type": "tool_result", "name": "...", "result": "..."}  — 工具执行结果
      {"type": "error", "content": "..."}            — 异常
      {"type": "done", "content": "...", "usage": {...}, "reasoning": "...", "thinking_count": N}
    """
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

    client, model_name = get_async_llm_client()
    actual_write_success = False
    max_loops = 4
    error_count = 0

    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    all_reasoning_parts = []
    full_content = ""

    for step in range(max_loops):
        try:
            kwargs = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.2,
                "stream": True,
            }
            if active_tools:
                normalized_tools = []
                for t in active_tools:
                    if "type" not in t:
                        normalized_tools.append({"type": "function", "function": t["function"]})
                    else:
                        normalized_tools.append(t)
                kwargs["tools"] = normalized_tools

            # ── 流式收集：工具调用 delta + 文本 delta ──
            collected_content_parts = []
            collected_tool_calls = []        # [{index, id, name, arguments}]
            reasoning_parts = []

            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                # 收集 tool_calls delta
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index if tc_delta.index is not None else 0
                        while len(collected_tool_calls) <= idx:
                            collected_tool_calls.append({
                                "id": None,
                                "function": {"name": "", "arguments": ""},
                            })
                        if tc_delta.id:
                            collected_tool_calls[idx]["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            collected_tool_calls[idx]["function"]["name"] += tc_delta.function.name
                        if tc_delta.function and tc_delta.function.arguments:
                            collected_tool_calls[idx]["function"]["arguments"] += tc_delta.function.arguments

                # 收集文本 delta
                if delta.content:
                    collected_content_parts.append(delta.content)
                    yield {"type": "text_delta", "content": delta.content}

                # 收集思考内容
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    reasoning_parts.append(reasoning)

                # 累加 usage（流式模式最后 chunk 通常带 usage）
                if chunk.usage:
                    total_usage = _accumulate_usage(total_usage, _extract_usage(chunk))

            # ── 流结束，判断是否有工具调用 ──
            if reasoning_parts:
                reasoning_text = "".join(reasoning_parts).strip()
                if reasoning_text:
                    all_reasoning_parts.append(f"--- 回合 {step+1} 思考 ---\n{reasoning_text}")

            step_content = "".join(collected_content_parts)

            if collected_tool_calls and collected_tool_calls[0].get("function", {}).get("name"):
                # ── 有工具调用 ──
                tc = collected_tool_calls[0]
                func_name = tc["function"]["name"]
                raw_args = tc["function"]["arguments"]
                parsed_args = robust_parse(raw_args, expect_array=False)
                args = parsed_args if isinstance(parsed_args, dict) else {}

                yield {"type": "tool_call", "name": func_name, "args": args}

                exec_result = execute_tool(func_name, args)

                if "✅ 成功" in str(exec_result) and ("drive" in func_name or "write" in func_name or "manage" in func_name):
                    actual_write_success = True

                yield {"type": "tool_result", "name": func_name, "result": str(exec_result)[:500]}

                # 追加到 messages
                tool_calls_list = []
                for ct in collected_tool_calls:
                    tool_calls_list.append({
                        "id": ct["id"] or f"call_{step}",
                        "type": "function",
                        "function": {
                            "name": ct["function"]["name"],
                            "arguments": ct["function"]["arguments"],
                        }
                    })
                messages.append({
                    "role": "assistant",
                    "content": step_content,
                    "tool_calls": tool_calls_list,
                })
                # Tool 结果消息
                for ct in collected_tool_calls:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": ct["id"] or f"call_{step}",
                        "content": str(exec_result),
                    })
                messages.append({
                    "role": "user",
                    "content": "数据已获取！请基于以上真实数据，直接用中文回答用户问题，不要再次调用工具。",
                })
                continue

            # ── 无工具调用：检查虚假写入 ──
            fake_write_claims = ["成功添加", "已成功写入", "已为您加", "成功插入记录", "已添加到"]
            ai_claims_fake_write = any(kw in step_content for kw in fake_write_claims)

            if ai_claims_fake_write and not actual_write_success:
                error_count += 1
                messages.append({"role": "assistant", "content": step_content})
                messages.append({"role": "user", "content": "🚨 **系统强制纠错**：你并未真正调用写工具却声称已添加！如果用户指令缺失关键参数（如手机号），立刻反问用户；如果参数齐全，请生成工具调用指令！"})
                continue

            if step_content.strip():
                full_content = step_content
                break
            else:
                messages.append({"role": "user", "content": "你刚才返回了空内容。请根据获取的数据直接输出最终的中文回答。"})
                continue

        except Exception as e:
            import traceback
            thinking_count = len(all_reasoning_parts)
            full_reasoning = "\n\n".join(all_reasoning_parts)
            yield {"type": "error", "content": f"引擎在第 {step+1} 回合崩溃: {str(e)}"}
            yield {
                "type": "done",
                "content": full_content or f"❌ 引擎错误",
                "usage": total_usage,
                "reasoning": full_reasoning,
                "thinking_count": thinking_count,
            }
            return

    # ── 完成 ──
    thinking_count = len(all_reasoning_parts)
    full_reasoning = "\n\n".join(all_reasoning_parts)
    if not full_content:
        full_content = "🚨 Agent 在后台连续尝试多次均陷入死循环。"
    yield {
        "type": "done",
        "content": full_content,
        "usage": total_usage,
        "reasoning": full_reasoning,
        "thinking_count": thinking_count,
    }