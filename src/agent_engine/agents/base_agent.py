# agents/base_agent.py
import json
import datetime
import re
import traceback
from agent_engine.llm_client import get_llm_client
from agent_engine.json_utils import robust_parse
from agent_engine.tracing import AgentTracer

# 兼容过渡：目前工具仍由 llm_engine 管理，后续可独立抽离为 tool_registry
from agent_engine.llm_engine import get_tools_definition, execute_tool

class BaseAgent:
    """
    🧠 Swarm 架构的核心基类：所有专家 Agent 必须继承此类。
    它定义了 Agent 的物理边界、工具权限以及标准的 ReAct 思考循环。
    """
    
    def __init__(self, agent_name: str, role_prompt: str, allowed_tool_names: list = None,
                 max_loops: int = 4):
        """
        初始化专家 Agent
        :param agent_name: 专家代号 (如 "Researcher", "Coder")
        :param role_prompt: 专家的"思想钢印"(System Prompt 的核心部分)
        :param allowed_tool_names: 该专家被允许使用的工具名称列表 (实现物理隔离)
        :param max_loops: 最大 ReAct 循环次数（默认 4，单工具 Agent 建议 3-4）
        """
        self.agent_name = agent_name
        self.role_prompt = role_prompt
        self.max_loops = max_loops
        
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
1. 🛠️ 主动执行：用户指令在你的工具能力范围内时，请调用工具获取或操作数据，不要凭空编造。
2. 🚫 严禁虚构执行：未实际调用工具前，绝对不允许编造"已查询/已写入"等谎言。
3. 🪞 报错透明化：工具抛出异常时，立即终止后续动作并如实报告。
4. 🎯 明确完成条件：在调用工具前，先想清楚"获取到什么信息就算完成任务"。满足条件后立刻输出总结，不画蛇添足。
5. 🚦 及时止损：同一工具连续调用 2 次结果仍不理想时，请基于已有信息如实总结，不要反复重试。
"""

    # ═══════════════════════════════════════════════
    # 核心执行引擎（干净的 ReAct 循环，trace 逻辑已抽离到 AgentTracer）
    # ═══════════════════════════════════════════════

    def execute(self, instruction: str, prior_context: str = "", parsed_memories: list = None, ui_status=None) -> str:
        """
        🦾 核心执行引擎：标准的 ReAct 循环 (带有自我纠错防死循环机制)
        :param instruction: 当前专家需要执行的具体指令
        :param prior_context: 前置任务传递过来的情报 (XComs)
        """
        self._tracer = AgentTracer(self.agent_name, instruction, prior_context)
        try:
            result = self._execute_impl(instruction, prior_context, parsed_memories, ui_status)
            self._tracer.finish(result)
            return result
        except Exception as e:
            self._tracer.finish(error=e)
            return f"❌ [{self.agent_name}] 执行崩溃:\n```python\n{traceback.format_exc()}\n```"

    def _execute_impl(self, instruction: str, prior_context: str = "", parsed_memories: list = None, ui_status=None) -> str:
        """
        ReAct 循环实现。返回最终结果文本（trace / audit 由 self._tracer 管理）。
        """
        # 组装 XComs 数据流转
        full_instruction = instruction
        if prior_context:
            full_instruction += f"\n\n【极其重要的前置情报】(请严格基于此情报执行):\n{prior_context}"

        messages = [{"role": "system", "content": self._build_system_prompt(parsed_memories)}]
        messages.append({"role": "user", "content": full_instruction})

        client, model_name = get_llm_client()
        actual_tool_success = False
        any_tool_called = False          # 只要任意工具被调用过就置 True，防止对 read 类操作的误判
        called_tools: dict = {}          # 追踪已调用的工具，防止同一工具死循环
        max_loops = self.max_loops
        error_count = 0

        for step in range(max_loops):
            self._tracer.step_start(step)

            try:
                # ── 1. LLM 调用 ──
                with self._tracer.llm_span(step, model_name, len(messages)) as llm_span:
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

                    llm_span.set_output({
                        "step": step + 1,
                        "finish_reason": response.choices[0].finish_reason,
                        "content_len": len(content),
                        "content_preview": content[:300],
                        "has_tool_call": bool(message_obj.tool_calls),
                        "msgs_in_context": len(messages),
                    })

                tool_called_this_step = False
                func_name = None
                args = {}

                # ── 2. 解析工具调用（兼容 JSON 和 XML 格式）──
                if message_obj.tool_calls:
                    tc = message_obj.tool_calls[0]
                    func_name = tc.function.name
                    args_str = tc.function.arguments
                    parsed = robust_parse(args_str, expect_array=False)
                    args = parsed if isinstance(parsed, dict) else {}
                    tool_called_this_step = True
                    self._tracer.log_tool_call(func_name, args)
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
                    if func_name:
                        tool_called_this_step = True
                        self._tracer.log_tool_call(func_name, args)

                # ── 3. 死循环守卫：同一工具重复调用超过 3 次则强制打断 ──
                if tool_called_this_step and func_name:
                    called_tools.setdefault(func_name, 0)
                    called_tools[func_name] += 1
                    if called_tools[func_name] > 3:
                        self._tracer.guard_span(step, "repeat_fuse",
                                                tool=func_name, count=called_tools[func_name])
                        self._tracer.step_end("continue", guard="repeat_fuse")

                        fuse_msg = f"🚨 你已经重复调用 `{func_name}` {called_tools[func_name]} 次！请基于目前已获取的数据直接输出最终中文回答，不要再调用它。"
                        if ui_status:
                            ui_status.write(f"🛑 [{self.agent_name}] 检测到 `{func_name}` 被重复调用 {called_tools[func_name]} 次，强制打断！")

                        # 拒绝调用时绝不保留 tool_calls，否则 DeepSeek 会报 "insufficient tool messages"
                        messages.append(
                            {"role": "assistant", "content": content}
                            if content.strip()
                            else {"role": "assistant", "content": f"尝试调用 {func_name}（已被系统拦截）"}
                        )
                        messages.append({"role": "user", "content": fuse_msg})
                        continue

                # ── 4. 工具执行落地 ──
                if tool_called_this_step and func_name:
                    if ui_status:
                        ui_status.write(f"🧑‍💻 [{self.agent_name}] 正在调用工具: `{func_name}` ...")

                    with self._tracer.tool_span(step, func_name, args) as tool_span:
                        exec_result = execute_tool(func_name, args)
                        tool_span.set_output({
                            "step": step + 1,
                            "tool": func_name,
                            "result_preview": str(exec_result)[:500],
                            "is_success": "✅ 成功" in str(exec_result),
                        })

                    any_tool_called = True
                    if "✅ 成功" in str(exec_result):
                        actual_tool_success = True

                    # ── 构建消息 & nudge 引导 ──
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
                        # 追加标准 tool 角色结果消息
                        for tc in message_obj.tool_calls:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": str(exec_result) if tc.id == message_obj.tool_calls[0].id
                                else "（此工具未被独立执行，请参考已获取的数据）",
                            })
                        # ── 智能识别：根据工具返回内容分场景引导 ──
                        if any(kw in str(exec_result) for kw in ["确认删除", "confirmed=True"]):
                            nudge_type = "confirm"
                            nudge_prompt = (
                                f"⚠️ 工具 `{func_name}` 返回了确认提示，删除尚未执行！"
                                f"请立刻用相同参数再次调用 `{func_name}`，并传入 `confirmed=True` 来完成删除。"
                            )
                        elif args.get("action") == "read":
                            nudge_type = "read"
                            nudge_prompt = (
                                f"已读取表格数据（如上）。请根据用户指令判断是否需要进一步操作"
                                f"（如删除、修改、添加数据）。如需要，请继续调用 `{func_name}` 并指定对应的 action；"
                                f"如果纯查询任务已完成，直接输出中文回答。"
                            )
                        else:
                            nudge_type = "general"
                            call_count = called_tools.get(func_name, 0)
                            if call_count >= 2:
                                nudge_prompt = (
                                    f"工具 `{func_name}` 已执行完毕。你已调用此工具 {call_count} 次，"
                                    f"请基于已获取的全部数据直接输出最终的中文回答，不要再继续调用工具。"
                                )
                            else:
                                nudge_prompt = (
                                    f"工具 `{func_name}` 已执行完毕。"
                                    f"如果还需要继续调用工具才能完成任务，请继续调用；"
                                    f"如果所有任务已完成，请直接输出最终的中文回答。"
                                )
                        messages.append({"role": "user", "content": nudge_prompt})
                    else:
                        # XML/正则 兜底路径
                        messages.append({"role": "assistant", "content": content})
                        if any(kw in str(exec_result) for kw in ["确认删除", "confirmed=True"]):
                            nudge_type = "confirm"
                            nudge_prompt = (
                                f"⚠️ 工具 `{func_name}` 返回了确认提示，删除尚未执行！"
                                f"请立刻用相同参数再次调用 `{func_name}`，并传入 `confirmed=True` 来完成删除。"
                            )
                        elif args.get("action") == "read":
                            nudge_type = "read"
                            nudge_prompt = (
                                f"已读取数据：\n```text\n{exec_result}\n```\n"
                                f"请根据用户指令判断是否需要进一步操作。如需继续，请调用 `{func_name}` 并指定对应 action；"
                                f"纯查询任务已完成则直接输出回答。"
                            )
                        else:
                            nudge_type = "general"
                            call_count = called_tools.get(func_name, 0)
                            if call_count >= 2:
                                nudge_prompt = (
                                    f"系统已执行 `{func_name}`（第 {call_count} 次）。"
                                    f"请基于已获取的全部数据直接输出最终的中文回答，不要再继续调用工具。"
                                )
                            else:
                                nudge_prompt = (
                                    f"系统已执行 `{func_name}`，返回数据：\n```text\n{exec_result}\n```\n"
                                    f"如果还需要继续调用工具才能完成任务，请继续调用；"
                                    f"如果所有任务已完成，请直接输出最终的中文回答。"
                                )
                        messages.append({"role": "user", "content": nudge_prompt})

                    self._tracer.step_end("continue", tool_result=exec_result, nudge_type=nudge_type)
                    continue

                # ── 5. 防幻觉与虚假动作拦截 ──
                #    关键修复：只要本轮对话中任意工具被调用过（包括 read），就不再拦截
                if not tool_called_this_step:
                    fake_claims = ["成功", "已为您", "已添加"]
                    if any(kw in content for kw in fake_claims) and not any_tool_called:
                        self._tracer.guard_span(step, "hallucination",
                                                content_preview=content[:200])
                        self._tracer.step_end("continue", guard="hallucination_block")

                        if ui_status:
                            ui_status.write(f"🚨 [{self.agent_name}] 拦截到幻觉，强制纠错重试...")
                        error_count += 1
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": "🚨 纠错：你并未真正调用工具！请生成规范的工具调用指令，或说明无法执行的原因。"})
                        continue

                    if content.strip():
                        self._tracer.step_end("return")
                        return content
                    else:
                        self._tracer.step_end("continue")
                        messages.append({"role": "user", "content": "你返回了空内容。请直接输出最终的中文总结。"})
                        continue

            except Exception as e:
                self._tracer.step_error(e)
                err_msg = f"❌ [{self.agent_name}] 在执行第 {step+1} 回合时崩溃:\n```python\n{traceback.format_exc()}\n```"
                return err_msg

        # ── 循环耗尽 → early_stopping：让 LLM 基于已有数据做最后一次总结 ──
        self._tracer.log_fuse(max_loops, called_tools)
        messages.append({
            "role": "user",
            "content": (
                f"⏰ 你已达到最大循环次数（{max_loops} 轮）。"
                f"请基于以上所有对话中已获取的全部数据，直接输出最终的中文回答。"
                f"不要再调用任何工具，直接输出文本即可。"
            )
        })
        # 不给 tools，强制 LLM 输出纯文本总结
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.3,
        )
        final_text = response.choices[0].message.content or ""
        if final_text.strip():
            return f"⚠️ 达到最大循环次数，以下是基于已获取数据的总结：\n\n{final_text}"
        return f"🚨 [{self.agent_name}] 多次尝试后无法完成任务，请尝试调整问题后重试。"
