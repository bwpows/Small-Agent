"""
LLM 客户端工厂：按 LLM_PROVIDER 开关返回 (OpenAI 客户端, 模型名)。
Ollama / Cloud / DeepSeek 都走 OpenAI 兼容的 /v1 协议，业务代码只有一条调用路径。
嵌入源独立于推理源，通过 EMBED_PROVIDER 控制。
"""
from openai import OpenAI, AsyncOpenAI
from config.config import (
    LLM_PROVIDER,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
    CLOUD_BASE_URL, CLOUD_API_KEY, CLOUD_MODEL,
    DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODEL,
    EMBED_PROVIDER, EMBEDDING_MODEL,
    OPENAI_EMBED_MODEL, OPENAI_EMBED_API_KEY,
    SILICONFLOW_EMBED_BASE_URL, SILICONFLOW_EMBED_API_KEY, SILICONFLOW_EMBED_MODEL,
)


def _build_client_kwargs():
    """返回当前 LLM_PROVIDER 对应的 (ClientClass, base_url, api_key, model_name)"""
    if LLM_PROVIDER == "ollama":
        return (OpenAI, f"{OLLAMA_BASE_URL}/v1", "ollama", OLLAMA_MODEL)

    if LLM_PROVIDER == "cloud":
        if not CLOUD_API_KEY:
            raise RuntimeError(
                "LLM_PROVIDER='cloud' 但未设置环境变量 LLM_API_KEY。\n"
                "请在终端执行: export LLM_API_KEY='sk-...' 或在 .env 中配置。"
            )
        return (OpenAI, CLOUD_BASE_URL, CLOUD_API_KEY, CLOUD_MODEL)

    if LLM_PROVIDER == "deepseek":
        if not DEEPSEEK_API_KEY:
            raise RuntimeError(
                "LLM_PROVIDER='deepseek' 但未设置环境变量 DEEPSEEK_API_KEY。\n"
                "请在终端执行: export DEEPSEEK_API_KEY='sk-...' 或在 .env 中配置。"
            )
        return (OpenAI, DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODEL)

    raise ValueError(f"未知 LLM_PROVIDER: {LLM_PROVIDER}，可选值: 'ollama' | 'cloud' | 'deepseek'")


def get_llm_client():
    """按 LLM_PROVIDER 配置返回 (client, model_name) 元组"""
    _, base_url, api_key, model_name = _build_client_kwargs()
    client = OpenAI(base_url=base_url, api_key=api_key)
    return client, model_name


def get_async_llm_client():
    """返回 (AsyncOpenAI 客户端, model_name)，用于 SSE 流式调用"""
    _, base_url, api_key, model_name = _build_client_kwargs()
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    return client, model_name


def get_embedding_client():
    """按 EMBED_PROVIDER 返回嵌入专用的 (client, embed_model_name)。
    嵌入源独立于推理 LLM_PROVIDER：推理选 DeepSeek，嵌入仍可走 Ollama。"""
    if EMBED_PROVIDER == "ollama":
        client = OpenAI(base_url=f"{OLLAMA_BASE_URL}/v1", api_key="ollama")
        return client, EMBEDDING_MODEL

    if EMBED_PROVIDER == "openai":
        if not OPENAI_EMBED_API_KEY:
            raise RuntimeError(
                "EMBED_PROVIDER='openai' 但未设置 OPENAI_API_KEY 或 LLM_API_KEY。\n"
                "请在终端执行: export OPENAI_API_KEY='sk-...' 或在 .env 中配置。"
            )
        # 使用 OpenAI 官方端点做嵌入（与推理的 CLOUD_BASE_URL 无关）
        client = OpenAI(base_url="https://api.openai.com/v1", api_key=OPENAI_EMBED_API_KEY)
        return client, OPENAI_EMBED_MODEL

    if EMBED_PROVIDER == "siliconflow":
        if not SILICONFLOW_EMBED_API_KEY:
            raise RuntimeError(
                "EMBED_PROVIDER='siliconflow' 但未设置 SILICONFLOW_API_KEY。\n"
                "1. 前往 https://siliconflow.cn 注册（国内直连）\n"
                "2. 获取 API Key 后在 .env 中配置: SILICONFLOW_API_KEY=sk-..."
            )
        client = OpenAI(base_url=SILICONFLOW_EMBED_BASE_URL, api_key=SILICONFLOW_EMBED_API_KEY)
        return client, SILICONFLOW_EMBED_MODEL

    raise ValueError(f"未知 EMBED_PROVIDER: {EMBED_PROVIDER}，可选值: 'ollama' | 'openai' | 'siliconflow'")
