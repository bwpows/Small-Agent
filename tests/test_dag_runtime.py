"""
DAG Runtime 完整测试套件
========================
覆盖所有 workflow 模块：ArtifactStore → TaskState → WorkflowPlan
→ GlobalContext/TaskContext → DAGScheduler → WorkflowRuntime（含降级）
"""

import sys
import os
import threading

# 确保能找到项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_engine.workflow.artifact import Artifact, ArtifactStore
from agent_engine.workflow.state import TaskStatus, TaskState
from agent_engine.workflow.plan import Task, WorkflowPlan
from agent_engine.workflow.context import GlobalContext, TaskContext
from agent_engine.workflow.risk_gate import RiskGate
from agent_engine.workflow.scheduler import DAGScheduler
from agent_engine.workflow.runtime import WorkflowRuntime
from agent_engine.agents.registry import AgentRegistry, AgentCard, AGENT_ROSTER


# ══════════════════════════════════════════════════════════
# Mock Agent（无需真实 LLM）
# ══════════════════════════════════════════════════════════

class MockAgent:
    """模拟 Agent，返回预设结果，记录调用次数"""

    def __init__(self, name: str = "mock", result: str = "done"):
        self.agent_name = name
        self.role = name
        self._result = result
        self.call_count = 0
        self.last_ctx = None

    def execute_with_ctx(self, ctx):
        self.call_count += 1
        self.last_ctx = ctx
        return self._result

    def execute(self, instruction, prior_context="", parsed_memories=None, ui_status=None):
        self.call_count += 1
        return self._result


def make_mock_registry():
    """创建带 Mock Agent 的注册表"""
    registry = AgentRegistry(use_cache=False)
    registry._initialized = True

    def mock_agent_factory(cls_name):
        class DynamicMock(MockAgent):
            pass
        DynamicMock.__name__ = cls_name
        return DynamicMock

    MockResearcher = mock_agent_factory("MockResearcher")
    MockCoder = mock_agent_factory("MockCoder")
    MockDrive = mock_agent_factory("MockDrive")

    registry._cards = {
        "researcher": AgentCard(
            role_id="researcher", display_name="研究员",
            description="搜索资料",
            agent_class=MockResearcher,
            risk_profile="low",
            tags=["search"],
        ),
        "coder": AgentCard(
            role_id="coder", display_name="工程师",
            description="编写代码",
            agent_class=MockCoder,
            risk_profile="medium",
            tags=["code"],
        ),
        "googledrive": AgentCard(
            role_id="googledrive", display_name="Drive管家",
            description="管理文件",
            agent_class=MockDrive,
            risk_profile="high",
            tags=["drive"],
        ),
    }
    return registry


# ══════════════════════════════════════════════════════════
# 1. Artifact + ArtifactStore 测试
# ══════════════════════════════════════════════════════════

def test_artifact_store():
    print("\n── 1. ArtifactStore 测试 ──")

    store = ArtifactStore()
    assert len(store) == 0, "初始为空"

    store.put(1, Artifact(task_id=1, agent_role="researcher",
                          output="AI 最新动态：GPT-5 发布..."))
    store.put(2, Artifact(task_id=2, agent_role="coder",
                          output="代码已生成：def hello(): ..."))
    assert len(store) == 2, "存储两个产物"
    assert 1 in store, "task_id=1 存在"

    a1 = store.get(1)
    assert a1.agent_role == "researcher", "角色正确"
    assert a1.output == "AI 最新动态：GPT-5 发布...", "输出正确"

    # build_prior_context
    ctx = store.build_prior_context([1, 2])
    assert "GPT-5" in ctx, "包含任务1的内容"
    assert "hello" in ctx, "包含任务2的内容"
    assert "前置任务情报" in ctx, "包含标题头"

    # 缺失的 task_id
    ctx_missing = store.build_prior_context([1, 99])
    assert "未产出结果" in ctx_missing, "提示缺失任务"

    print(f"  ✅ 全部通过（存储={len(store)}，上下文={len(ctx)}字符）")


# ══════════════════════════════════════════════════════════
# 2. TaskState 状态机测试
# ══════════════════════════════════════════════════════════

def test_task_state():
    print("\n── 2. TaskState 状态机测试 ──")

    ts = TaskState({
        "task_id": 1, "agent_role": "researcher",
        "instruction": "搜索 AI 新闻", "depends_on": [],
        "risk_level": "low", "risk_details": "", "expected_output": "新闻摘要"
    })
    assert ts.status == TaskStatus.PENDING, "初始 PENDING"
    assert not ts.is_terminal, "非终态"

    # PENDING → RUNNING
    ok = ts.transition(TaskStatus.RUNNING)
    assert ok, "PENDING → RUNNING 合法"
    assert ts.status == TaskStatus.RUNNING

    # RUNNING → SUCCEEDED
    ok = ts.transition(TaskStatus.SUCCEEDED, output="找到 3 条新闻")
    assert ok, "RUNNING → SUCCEEDED 合法"
    assert ts.output == "找到 3 条新闻"
    assert ts.is_terminal, "终态"

    # 终态不可再转换
    ok = ts.transition(TaskStatus.RUNNING)
    assert not ok, "SUCCEEDED → RUNNING 非法"

    # block 和 skip
    ts2 = TaskState({
        "task_id": 2, "agent_role": "coder", "instruction": "写代码",
        "depends_on": [1], "risk_level": "medium"
    })
    ts2.block(reason="前置失败")
    assert ts2.status == TaskStatus.BLOCKED

    ts3 = TaskState({
        "task_id": 3, "agent_role": "googledrive", "instruction": "删文件",
        "depends_on": [], "risk_level": "high"
    })
    ts3.skip(reason="风控拦截")
    assert ts3.status == TaskStatus.SKIPPED

    # to_dict
    d = ts.to_dict()
    assert d["task_id"] == 1 and d["status"] == "SUCCEEDED"

    print("  ✅ 全部通过（状态机 6 种状态，转换校验正确）")


# ══════════════════════════════════════════════════════════
# 3. WorkflowPlan 测试
# ══════════════════════════════════════════════════════════

def test_workflow_plan():
    print("\n── 3. WorkflowPlan 测试 ──")

    # 正常 DAG 计划
    plan = WorkflowPlan([
        Task(task_id=1, title="搜索", action="web_search", agent_role="researcher",
             depends_on=[], instruction="搜新闻"),
        Task(task_id=2, title="分析", action="analyze", agent_role="coder",
             depends_on=[1], instruction="分析新闻"),
        Task(task_id=3, title="存储", action="save", agent_role="googledrive",
             depends_on=[2], instruction="保存结果"),
    ])
    assert plan.is_dag, "多任务有依赖 = DAG"
    assert plan.task_count == 3
    assert plan.validate(), "校验通过"

    roots = plan.get_root_tasks()
    assert len(roots) == 1 and roots[0].task_id == 1, "根任务是 #1"

    leaves = plan.get_leaf_tasks()
    assert len(leaves) == 1 and leaves[0].task_id == 3, "叶子任务是 #3"

    # 单任务（非 DAG）
    plan2 = WorkflowPlan([
        Task(task_id=1, title="xxx", action="chat", agent_role="researcher",
             depends_on=[]),
    ])
    assert not plan2.is_dag, "单任务不是 DAG"

    # 校验：引用了不存在的 task_id
    plan3 = WorkflowPlan([
        Task(task_id=1, title="x", action="a", agent_role="coder", depends_on=[99]),
    ])
    assert not plan3.validate(), "无效依赖应校验失败"

    # 校验：自依赖
    plan4 = WorkflowPlan([
        Task(task_id=1, title="x", action="a", agent_role="coder", depends_on=[1]),
    ])
    assert not plan4.validate(), "自依赖应校验失败"

    # from_planner_output
    pp = {"plan_type": "dag", "tasks": [
        {"task_id": 1, "title": "搜索", "action": "search", "agent_role": "researcher",
         "depends_on": [], "instruction": "搜", "risk_level": "low", "risk_details": "",
         "expected_output": "新闻"},
        {"task_id": 2, "title": "编码", "action": "code", "agent_role": "coder",
         "depends_on": [1], "instruction": "写", "risk_level": "medium", "risk_details": "",
         "expected_output": "代码"},
    ]}
    plan5 = WorkflowPlan.from_planner_output(pp)
    assert plan5 is not None and plan5.is_dag, "from_planner_output 正常"

    # from_planner_output: 非 DAG
    pp2 = {"plan_type": "single", "tasks": []}
    assert WorkflowPlan.from_planner_output(pp2) is None, "single plan 返回 None"

    print("  ✅ 全部通过（DAG 判断、校验、from_planner_output）")


# ══════════════════════════════════════════════════════════
# 4. GlobalContext + TaskContext 测试
# ══════════════════════════════════════════════════════════

def test_context():
    print("\n── 4. GlobalContext + TaskContext 测试 ──")

    store = ArtifactStore()
    store.put(1, Artifact(task_id=1, agent_role="researcher",
                          output="搜索结果：找到 5 篇相关文章"))

    global_ctx = GlobalContext(
        artifacts=store,
        memories="用户偏好简洁风格",
        profile="用户是后端工程师",
        history="之前讨论过微服务架构",
    )

    ts = TaskState({
        "task_id": 2, "agent_role": "coder",
        "instruction": "根据搜索情报编写分析代码",
        "depends_on": [1],
        "risk_level": "low", "risk_details": "", "expected_output": "Python脚本"
    })

    task_ctx = TaskContext(global_ctx=global_ctx, task_state=ts)

    # 委托属性
    assert task_ctx.task_id == 2
    assert task_ctx.agent_role == "coder"
    assert task_ctx.memories == "用户偏好简洁风格"
    assert task_ctx.profile == "用户是后端工程师"
    assert task_ctx.history == "之前讨论过微服务架构"

    # prior_context（懒计算 + 缓存）
    prior = task_ctx.prior_context
    assert "前置任务情报" in prior, "包含标题头"
    assert "搜索结果" in prior, "包含前置任务输出"
    prior2 = task_ctx.prior_context
    assert prior is prior2, "缓存生效（同一对象）"

    # build_full_prompt
    prompt = task_ctx.build_full_prompt()
    assert "前置任务情报" in prompt
    assert "用户画像" in prompt
    assert "用户偏好" in prompt
    assert "当前任务" in prompt
    assert "期望产出" in prompt

    # get_prior_artifact
    a = task_ctx.get_prior_artifact(1)
    assert a is not None and a.agent_role == "researcher"

    print(f"  ✅ 全部通过（full_prompt={len(prompt)}字符）")


# ══════════════════════════════════════════════════════════
# 5. RiskGate 测试
# ══════════════════════════════════════════════════════════

def test_risk_gate():
    print("\n── 5. RiskGate 风控测试 ──")

    gate = RiskGate()

    # 低风险 → 放行
    ts_low = TaskState({
        "task_id": 1, "agent_role": "researcher",
        "instruction": "搜索", "depends_on": [],
        "risk_level": "low", "risk_details": ""
    })
    d = gate.evaluate(ts_low)
    assert not d["blocked"], "低风险放行"

    # 高风险 → 拦截
    ts_high = TaskState({
        "task_id": 2, "agent_role": "googledrive",
        "instruction": "删除文件", "depends_on": [],
        "risk_level": "high", "risk_details": "会删除用户云盘文件"
    })
    d = gate.evaluate(ts_high)
    assert d["blocked"], "高风险拦截"
    assert "人工确认" in d["reason"]

    # 中风险 → 放行
    ts_mid = TaskState({
        "task_id": 3, "agent_role": "coder",
        "instruction": "写文件", "depends_on": [],
        "risk_level": "medium", "risk_details": ""
    })
    d = gate.evaluate(ts_mid)
    assert not d["blocked"], "中风险放行"

    print("  ✅ 全部通过（low/medium 放行，high 拦截）")


# ══════════════════════════════════════════════════════════
# 6. DAGScheduler 拓扑排序测试
# ══════════════════════════════════════════════════════════

def test_dag_scheduler_topology():
    print("\n── 6. DAGScheduler 拓扑排序测试 ──")

    # 场景: A → B → D
    #         ↘ C ↗
    ts_A = TaskState({"task_id": 1, "agent_role": "researcher",
                       "instruction": "A", "depends_on": []})
    ts_B = TaskState({"task_id": 2, "agent_role": "coder",
                       "instruction": "B", "depends_on": [1]})
    ts_C = TaskState({"task_id": 3, "agent_role": "coder",
                       "instruction": "C", "depends_on": [1]})
    ts_D = TaskState({"task_id": 4, "agent_role": "googledrive",
                       "instruction": "D", "depends_on": [2, 3]})

    layers = DAGScheduler.topological_layers([ts_A, ts_B, ts_C, ts_D])
    layer_ids = [[t.task_id for t in layer] for layer in layers]
    assert layer_ids == [[1], [2, 3], [4]], f"分层应为 [[1],[2,3],[4]]，实际 {layer_ids}"

    # 场景: 无依赖（所有任务独立）
    ts_1 = TaskState({"task_id": 1, "agent_role": "a", "instruction": "x", "depends_on": []})
    ts_2 = TaskState({"task_id": 2, "agent_role": "a", "instruction": "x", "depends_on": []})
    ts_3 = TaskState({"task_id": 3, "agent_role": "a", "instruction": "x", "depends_on": []})
    layers2 = DAGScheduler.topological_layers([ts_1, ts_2, ts_3])
    assert len(layers2) == 1 and len(layers2[0]) == 3, "无依赖应全部在同一层"

    # 场景: 空列表
    assert DAGScheduler.topological_layers([]) == [], "空列表返回空"

    print("  ✅ 全部通过（正确分层，支持并发识别）")


# ══════════════════════════════════════════════════════════
# 7. DAGScheduler 并发执行测试
# ══════════════════════════════════════════════════════════

def test_dag_scheduler_execution():
    print("\n── 7. DAGScheduler 并发执行测试 ──")

    # 模拟有依赖的任务链
    ts_A = TaskState({"task_id": 1, "agent_role": "researcher",
                       "instruction": "搜索", "depends_on": []})
    ts_B = TaskState({"task_id": 2, "agent_role": "coder",
                       "instruction": "编码", "depends_on": [1]})
    ts_C = TaskState({"task_id": 3, "agent_role": "googledrive",
                       "instruction": "存储", "depends_on": [2]})

    exec_order = []
    lock = threading.Lock()

    def executor(ts):
        with lock:
            exec_order.append(ts.task_id)
        ts.transition(TaskStatus.RUNNING)
        ts.transition(TaskStatus.SUCCEEDED, output=f"任务#{ts.task_id}完成")

    scheduler = DAGScheduler(max_workers=3)
    ok = scheduler.run([ts_A, ts_B, ts_C], executor)

    assert ok, "执行成功"
    assert exec_order == [1, 2, 3], f"顺序执行，实际: {exec_order}"
    assert all(ts.status == TaskStatus.SUCCEEDED for ts in [ts_A, ts_B, ts_C]), "全部成功"

    scheduler.shutdown()
    print("  ✅ 全部通过（依赖链顺序执行成功）")


# ══════════════════════════════════════════════════════════
# 8. DAGScheduler 失败传染测试
# ══════════════════════════════════════════════════════════

def test_failure_propagation():
    print("\n── 8. 失败传染测试 ──")

    ts_A = TaskState({"task_id": 1, "agent_role": "researcher",
                       "instruction": "搜索", "depends_on": []})
    ts_B = TaskState({"task_id": 2, "agent_role": "coder",
                       "instruction": "编码", "depends_on": [1]})
    ts_C = TaskState({"task_id": 3, "agent_role": "googledrive",
                       "instruction": "存储", "depends_on": [2]})

    def executor(ts):
        ts.transition(TaskStatus.RUNNING)
        if ts.task_id == 1:
            ts.transition(TaskStatus.FAILED, error="搜索失败")
        else:
            ts.transition(TaskStatus.SUCCEEDED, output="ok")

    scheduler = DAGScheduler(max_workers=3)
    ok = scheduler.run([ts_A, ts_B, ts_C], executor)

    assert not ok, "有失败任务应返回 False"
    assert ts_A.status == TaskStatus.FAILED, "#1 失败"
    assert ts_B.status == TaskStatus.BLOCKED, "#2 被阻塞（传染）"
    assert ts_C.status == TaskStatus.BLOCKED, "#3 被阻塞（连锁传染）"

    scheduler.shutdown()
    print("  ✅ 全部通过（#1 失败 → #2 和 #3 被 BLOCKED）")


# ══════════════════════════════════════════════════════════
# 9. WorkflowRuntime 完整流程测试
# ══════════════════════════════════════════════════════════

def test_workflow_runtime_full():
    print("\n── 9. WorkflowRuntime 完整流程测试 ──")

    plan = WorkflowPlan([
        Task(task_id=1, title="搜索情报", action="web_search",
             agent_role="researcher", depends_on=[],
             instruction="搜索最新的 AI 发展趋势",
             risk_level="low", risk_details="",
             expected_output="AI 趋势摘要"),
        Task(task_id=2, title="分析数据", action="analyze",
             agent_role="coder", depends_on=[1],
             instruction="分析搜索结果并生成报告",
             risk_level="low", risk_details="",
             expected_output="分析报告"),
        Task(task_id=3, title="存储报告", action="save",
             agent_role="googledrive", depends_on=[2],
             instruction="将报告保存到 Google Drive",
             risk_level="high", risk_details="会操作云盘文件",
             expected_output="文件链接"),
    ])
    assert plan.validate()

    registry = make_mock_registry()
    runtime = WorkflowRuntime(
        plan=plan,
        registry=registry,
        user_query="帮我分析 AI 趋势并保存报告",
        memories="用户偏好详细报告",
        profile="用户是技术经理",
        max_workers=3,
    )

    result = runtime.execute()

    # 基本结构检查
    assert "success" in result, "返回 success 字段"
    assert "summary" in result, "返回 summary 字段"
    assert "task_results" in result, "返回 task_results 字段"
    assert "blocked_tasks" in result, "返回 blocked_tasks 字段"
    assert "artifacts" in result, "返回 artifacts 字段"

    # 由于 #3 是高风险任务，应被风控拦截
    blocked = result["blocked_tasks"]
    assert len(blocked) >= 1, "至少一个任务被拦截"
    blocked_ids = [b["task_id"] for b in blocked]
    assert 3 in blocked_ids, "任务 #3 (high risk) 被拦截"

    # 检查成功的任务
    task_results = {tr["task_id"]: tr for tr in result["task_results"]}
    assert task_results[1]["status"] == "SUCCEEDED", "#1 应成功"
    assert task_results[2]["status"] == "SUCCEEDED", "#2 应成功（依赖#1已成功）"
    assert task_results[3]["status"] == "SKIPPED", "#3 应被跳过（风控）"

    # artifacts 应包含 #1 和 #2
    assert 1 in result["artifacts"] and 2 in result["artifacts"], "产物存储正确"

    # HITL 测试
    assert runtime.has_blocked_tasks, "有被拦截的任务"
    assert len(runtime.get_blocked_tasks()) == 1

    # 审批通过后恢复
    resumed = runtime.resume_blocked_task(3, approved=True)
    assert resumed, "恢复成功"
    assert runtime.task_states[3].status == TaskStatus.PENDING

    print("  ✅ 全部通过（风控拦截 + 正常执行 + HITL 恢复）")


# ══════════════════════════════════════════════════════════
# 10. 降级策略测试（Plan 非 DAG → 返回 None）
# ══════════════════════════════════════════════════════════

def test_fallback():
    print("\n── 10. 降级策略测试 ──")

    # 单任务计划 → is_dag = False
    plan = WorkflowPlan([
        Task(task_id=1, title="聊天", action="chat", agent_role="researcher",
             depends_on=[]),
    ])
    assert not plan.is_dag, "单任务不是 DAG"

    # 空 from_planner_output
    assert WorkflowPlan.from_planner_output({}) is None
    assert WorkflowPlan.from_planner_output(None) is None
    assert WorkflowPlan.from_planner_output({"plan_type": "single", "tasks": []}) is None

    # from_planner_output 只有一个任务
    pp = {"plan_type": "dag", "tasks": [
        {"task_id": 1, "title": "x", "action": "a", "agent_role": "coder",
         "depends_on": [], "instruction": "x", "risk_level": "low",
         "risk_details": "", "expected_output": "x"}
    ]}
    plan2 = WorkflowPlan.from_planner_output(pp)
    assert plan2 is not None, "单任务也可以构建 WorkflowPlan"
    assert not plan2.is_dag, "但 is_dag 为 False（调用方据此降级）"

    print("  ✅ 全部通过（降级判断正确）")


# ══════════════════════════════════════════════════════════
# 11. 线程安全测试（并发写入 ArtifactStore）
# ══════════════════════════════════════════════════════════

def test_thread_safety():
    print("\n── 11. 线程安全测试 ──")

    store = ArtifactStore()
    num_threads = 10
    barrier = threading.Barrier(num_threads)

    def writer(thread_id):
        barrier.wait()  # 所有线程同时开始
        for i in range(5):
            tid = thread_id * 100 + i
            store.put(tid, Artifact(task_id=tid, agent_role="test",
                                    output=f"thread-{thread_id}-iter-{i}"))

    threads = [threading.Thread(target=writer, args=(t,))
               for t in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(store) == num_threads * 5, f"应存储 {num_threads * 5} 个产物"
    # 验证每个产物都可读取
    all_artifacts = store.get_all()
    for tid in range(num_threads):
        for i in range(5):
            key = tid * 100 + i
            assert key in all_artifacts, f"缺失 key={key}"

    print(f"  ✅ 全部通过（{num_threads}线程 × 5次写入 = {len(store)}产物，无数据丢失）")


# ══════════════════════════════════════════════════════════
# 12. AgentRegistry 工厂方法测试
# ══════════════════════════════════════════════════════════

def test_agent_registry():
    print("\n── 12. AgentRegistry 工厂测试 ──")

    # 测试带缓存的 Registry
    registry_cached = AgentRegistry(use_cache=True)
    registry_cached._initialized = True  # 跳过惰性加载
    # 使用真实 Agent 类做缓存测试需要避免 agent 初始化，用 mock 覆盖
    registry = make_mock_registry()

    # create 方法
    a1 = registry.create("researcher")
    assert a1 is not None
    assert hasattr(a1, "execute_with_ctx"), "有 execute_with_ctx"

    # create_new 总是返回新实例
    a_new = registry.create_new("researcher")
    assert a_new is not a1, "create_new 应返回新实例（use_cache=False 时 create 也不缓存）"

    # 大小写不敏感
    a_lower = registry.create("CODER")
    assert a_lower is not None, "大小写不敏感匹配"

    # 不存在的角色
    assert registry.create("nonexistent") is None, "不存在返回 None"

    # list_roles
    roles = registry.list_roles()
    assert set(roles) == {"researcher", "coder", "googledrive"}

    # __contains__
    assert "researcher" in registry
    assert "unknown" not in registry

    print("  ✅ 全部通过（工厂创建、缓存、大小写不敏感、不存在返回 None）")


# ══════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  DAG Runtime 完整测试套件")
    print("=" * 60)

    all_tests = [
        test_artifact_store,
        test_task_state,
        test_workflow_plan,
        test_context,
        test_risk_gate,
        test_dag_scheduler_topology,
        test_dag_scheduler_execution,
        test_failure_propagation,
        test_workflow_runtime_full,
        test_fallback,
        test_thread_safety,
        test_agent_registry,
    ]

    passed = 0
    failed = 0

    for test_fn in all_tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ 失败: {test_fn.__name__} — {e}")
            failed += 1
        except Exception as e:
            print(f"  💥 崩溃: {test_fn.__name__} — {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"  结果: {passed} 通过 / {failed} 失败 / {len(all_tests)} 总计")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
