# agents/base_agent.py
import json
import datetime
import re
import traceback
from core.llm_client import get_llm_client
from core.json_utils import robust_parse
from core.tracing import trace_span, SpanKind, get_tracer

# 兼容过渡：目前工具仍由 llm_engine 管理，后续可独立抽离为 tool_registry
from core.llm_engine import get_tools_definition, execute_tool

class BaseAgent:
    """
    🧠 Swarm 架构的核心基类：所有专家 Agent 必须继承此类。
    它定义了 Agent 的物理边界、工具权限以及标准的 ReAct 思考循环。
    """
    
    def __init__(self, agent_name: str, role_prompt: str, allowed_tool_names: list = None):
        """
        初始化专家 Agent
        :param agent_name: 专家代号 (如 "Researcher", "Coder")
        :param role_prompt: 专家的“思想钢印”(System Prompt 的核心部分)
        :param allowed_tool_names: 该专家被允许使用的工具名称列表 (实现物理隔离)
        """
        self.agent_name = agent_name
        self.role_prompt = role_prompt
        
        # ==========================================
        # 🛡️ 架构级安全：工具权限物理隔离
        # ==========================================
        all_tools = get_tools_definition()
        if allowed_tool_names is None:
            # 如果不传，默认拥有所有工具权限（仅供全能 Worker 或调试使用）
            self.allowed_tools = all_tools 
        else:
            # 严格按照白名单过滤工具，没授权的工具在内存里根本不存在
            self.allowed_tools = [t for t in all_tools if t["function"]["name"] in allowed_tool_names]
            
        print(f"✅ 专家 [{self.agent_name}] 注册完毕，已挂载 {len(self.allowed_tools)} 个专属工具。")

    def _build_system_prompt(self, parsed_memories: list) -> str:
        """构建融合了长期记忆与专家设定的系统提示词"""
        current_time = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M")
        memory_text = "\n".join([f"- {m['text']}" for m in parsed_memories]) if parsed_memories else "无相关长期记忆。"
        
        return f"""当前系统时间：{current_time}。
【用户的长期记忆】：\n{memory_text}

【🎭 你的专属专家设定】
{self.role_prompt}

【⚙️ 物理边界与执行铁律 (最高优先级)】
1. 🛠️ 绝对权限：只要用户指令在你的工具能力范围内，必须立刻调用工具去执行，严禁推脱！
2. 🚫 严禁虚构执行：未实际调用工具前，绝对不允许编造“已查询/已写入”等谎言。
3. 🪞 报错透明化：工具抛出异常时，立即终止后续动作并如实报告。
4. 🎯 拒绝废话：直接给出结构化的结果，保持极其专业的专家语气。
"""

    def execute(self, instruction: str, prior_context: str = "", parsed_memories: list = None, ui_status=None) -> str:
        """
        🦾 核心执行引擎：标准的 ReAct 循环 (带有自我纠错防死循环机制)
        :param instruction: 当前专家需要执行的具体指令
        :param prior_context: 前置任务传递过来的情报 (XComs)
        """
        tracer = get_tracer()
        agent_span = tracer.start_span(
            name=f"agent::{self.agent_name}",
            kind=SpanKind.AGENT,
            inputs={"instruction": instruction, "prior_context": prior_context[:200] if prior_context else ""},
            metadata={"agent_name": self.agent_name},
        )

        try:
            result = self._execute_impl(instruction, prior_context, parsed_memories, ui_status)
            tracer.end_span(agent_span, output=result)
            return result
        except Exception as e:
            tracer.end_span(agent_span, error=e)
            return f"❌ [{self.agent_name}] 执行崩溃:\n```python\n{traceback.format_exc()}\n```"

    def _execute_impl(self, instruction: str, prior_context: str = "", parsed_memories: list = None, ui_status=None) -> str:
        # 组装 XComs 数据流转
        full_instruction = instruction
        if prior_context:
            full_instruction += f"\n\n【极其重要的前置情报】(请严格基于此情报执行):\n{prior_context}"

        messages = [{"role": "system", "content": self._build_system_prompt(parsed_memories)}]
        messages.append({"role": "user", "content": full_instruction})

        client, model_name = get_llm_client()
        actual_tool_success = False
        called_tools: dict = {}          # 追踪已调用的工具，防止同一工具死循环
        max_loops = 6                   # 给多步工具链留足空间
        error_count = 0

        for step in range(max_loops):
            try:
                # 1. 呼叫大模型
                with trace_span(f"llm_chat::{self.agent_name}", kind=SpanKind.LLM, capture_input=False) as llm_span:
                    kwargs = {
                        "model": model_name,
                        "messages": messages,
                        "temperature": 0.2,
                    }
                    if self.allowed_tools:
                        # 确保工具格式符合 OpenAI 规范：必须有 "type": "function"
                        normalized_tools = []
                        for t in self.allowed_tools:
                            if "type" not in t:
                                normalized_tools.append({"type": "function", "function": t["function"]})
                            else:
                                normalized_tools.append(t)
                        kwargs["tools"] = normalized_tools

                    response = client.chat.completions.create(**kwargs)
                    message_obj = response.choices[0].message
                    content = message_obj.content or ""
                    llm_span.set_output({"content_len": len(content), "has_tool_call": bool(message_obj.tool_calls)})
                
                tool_called_this_step = False
                func_name = None
                args = {}

                # 2. 兼容解析 JSON 或 XML 格式的工具调用（加固：自动修复参数 JSON）
                if message_obj.tool_calls:
                    tc = message_obj.tool_calls[0]
                    func_name = tc.function.name
                    args_str = tc.function.arguments
                    parsed = robust_parse(args_str, expect_array=False)
                    args = parsed if isinstance(parsed, dict) else {}
                    tool_called_this_step = True
                elif "<function=" in content or "<tool_call>" in content:
                    # (保留你原有的正则解析逻辑)
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

                # ── 死循环守卫：同一工具重复调用超过 2 次则强制打断 ──
                if tool_called_this_step and func_name:
                    called_tools.setdefault(func_name, 0)
                    called_tools[func_name] += 1
                    if called_tools[func_name] > 2:
                        if ui_status:
                            ui_status.write(f"🛑 [{self.agent_name}] 检测到 `{func_name}` 被重复调用 {called_tools[func_name]} 次，强制打断！")
                        nudge = f"🚨 你已经重复调用 `{func_name}` {called_tools[func_name]} 次！禁止再次调用它。请基于目前已获取的数据直接输出最终中文回答。"
                        # 🔧 关键修复：拒绝调用时绝不保留 tool_calls，否则 DeepSeek 会报 "insufficient tool messages"
                        messages.append({"role": "assistant", "content": content} if content.strip() else {"role": "assistant", "content": f"尝试调用 {func_name}（已被系统拦截）"})
                        messages.append({"role": "user", "content": nudge})
                        continue

                # 3. ⚙️ 工具执行落地
                if tool_called_this_step and func_name:
                    if ui_status:
                        ui_status.write(f"🧑‍💻 [{self.agent_name}] 正在调用工具: `{func_name}` ...")

                    with trace_span(f"tool::{func_name}", kind=SpanKind.TOOL, inputs={"args": args}, metadata={"agent": self.agent_name}) as tool_span:
                        exec_result = execute_tool(func_name, args)
                        tool_span.set_output(exec_result)
                    
                    if "✅ 成功" in str(exec_result):
                        actual_tool_success = True
                    
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
                        # 追加标准 tool 角色结果消息（必须为每个 tool_call_id 都提供响应，否则 DeepSeek 报错）
                        for tc in message_obj.tool_calls:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": str(exec_result) if tc.id == message_obj.tool_calls[0].id else "（此工具未被独立执行，请参考已获取的数据）",
                            })
                        # 补一条 user 消息做总结提示（鼓励多步工具链，但禁止重复）
                        nudge_prompt = (
                            f"如果还需要调用**其他**工具才能完成任务，请继续调用；"
                            f"如果数据已经足够，请直接输出最终的中文回答。"
                            f"【重要】绝对禁止再次调用 `{func_name}`！"
                        )
                        messages.append({"role": "user", "content": nudge_prompt})
                    else:
                        # XML/正则 兜底路径
                        messages.append({"role": "assistant", "content": content})
                        nudge_prompt = (
                            f"系统已执行 `{func_name}`，返回数据：\n```text\n{exec_result}\n```\n"
                            f"如果还需要调用**其他**工具才能完成任务，请继续调用；"
                            f"如果数据已经足够，请直接输出最终的中文回答。"
                            f"【重要】绝对禁止再次调用 `{func_name}`！"
                        )
                        messages.append({"role": "user", "content": nudge_prompt})
                    continue  

                # 4. 🚨 防幻觉与虚假动作拦截
                if not tool_called_this_step:
                    fake_claims = ["成功", "已为您", "已添加"]
                    if any(kw in content for kw in fake_claims) and not actual_tool_success:
                        if ui_status:
                            ui_status.write(f"🚨 [{self.agent_name}] 拦截到幻觉，强制纠错重试...")
                        error_count += 1 
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": "🚨 纠错：你并未真正调用工具！请生成规范的工具调用指令，或说明无法执行的原因。"})
                        continue

                    if content.strip():
                        return content
                    else:
                        messages.append({"role": "user", "content": "你返回了空内容。请直接输出最终的中文总结。"})
                        continue
                    
            except Exception as e:
                return f"❌ [{self.agent_name}] 在执行第 {step+1} 回合时崩溃:\n```python\n{traceback.format_exc()}\n```"

        return f"🚨 [{self.agent_name}] 后台连续尝试多次陷入死循环，任务被强制熔断。"