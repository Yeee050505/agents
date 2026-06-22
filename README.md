# 多智能体协作平台

## 技术栈

FastAPI · LangChain · LangGraph · DeepSeek · Qwen2.5-3B+LoRA · BGE · Redis · SQLite · Docker · React+Vite+TypeScript+TailwindCSS

## 项目描述

单一大模型在实时问答中存在延迟高、知识过时、无会话记忆、单点故障等问题。本项目基于 **五层解耦架构**（L1 LLM + L2 RAG + L3 MCP + L4 ReAct + L5 React）搭建了一个具备多 Agent 协作、ReAct 决策循环、MCP 工具总线、私有知识库、联网搜索增强、LoRA 本地推理、流式输出、高可用 LLM 调用的智能问答平台。

1. **五层解耦架构**：L1 LLM 基座（DeepSeek API 3 Key 池+断路器 / Qwen2.5-3B LoRA）→ L2 RAG 知识库（BGE small + BM25 混合检索）→ L3 MCP 工具总线（统一注册/调用/日志）→ L4 ReAct 决策循环（Thought→Action→Observation→Final Answer）→ L5 React SPA 前端。

2. **LangGraph 多 Agent 编排**：基于 LangGraph StateGraph 构建 7 节点（intent / code / knowledge / chat / tool / data / lora）+ supervisor 质检 + merger 合并的图式调度引擎，支持并行扇出（Send()）和 supervisor 重分类。

3. **ReAct + MCP 协同决策**：共享 `_run_react_loop()` 函数实现 ReAct 循环，所有外部数据访问强制通过 MCP 工具总线（`rag_search` / `web_search` / `rate_stats` / `session_info`），各节点禁止直连 RAG/搜索。

4. **LLM 高可用密钥池**：3 把 DeepSeek Key 池化轮询 + 三态断路器（CLOSED→OPEN→HALF_OPEN）+ 指数退避（10s→120s），`_call_llm` 主实例失败遍历剩余健康实例，全部熔断友好降级。

5. **LoRA 本地推理**：Qwen2.5-3B + LoRA 适配器（世界杯助手，34 Q&A 10 epoch），RTX 4060 8GB 运行，体育/世界杯关键词自动路由到本地 GPU，降低 API 成本，低质量回答自动降级 ReAct-MCP。

6. **Bing/百度双搜 + 知识时效补足**：双引擎并发（FIRST_COMPLETED），16 个关键词触发联网搜索，14 个过时标记检测 + 自动重试。

7. **RAG 混合检索知识库**：BGE 本地嵌入（512 维） + BM25 混合融合（0.6+0.4），语义分块 + query 重写，支持 .txt/.md/.pdf 上传，动态新增无需重训模型。

8. **会话级上下文记忆**：基于 session_id 隔离，Redis 存储（TTL=3600s）+ 内存二级降级，最多保留 20 轮，1 小时无活动自动清除。TCP 探活解决 redis-py 8.0 超时 bug。

9. **流式输出 + LLM 缓存**：`graph.astream()` 逐 token SSE 推送（1s 首字），SHA256 内存缓存（5ms 命中 218 QPS）。

## Benchmark

| 场景 | 延迟 | QPS |
|------|------|-----|
| 缓存命中 | 5ms | 218 |
| 纯路由吞吐 | P50=190ms | 905 |
| 首次 LLM 回答 | 8.5s | — |
| 旧冷启动（修复前） | ~100s | — |

## 五层架构图

```
L5  React SPA (Vite + TypeScript + TailwindCSS)
    │  SSE streaming / Auth / KB manager
    ▼
L4  ReAct 决策 (Thought → Action → Observation → Final Answer)
    │  _run_react_loop() 共享函数
    ▼  Action: rag_search | web_search | rate_stats | session_info
L3  MCP 工具总线 (MCPToolRegistry, ~60行自研)
    │  统一注册/调用/日志/权限
    ▼
L2  RAG 知识库 (BGE small 512维 + BM25 混合检索)
    │  语义分块 / query 重写
    ▼
L1  LLM 基座 (DeepSeek API + Qwen2.5-3B LoRA)
```

## 启动

```bash
# 后端
cd agents && venv\Scripts\uvicorn main:app --host 0.0.0.0 --port 8000

# 前端（新终端）
cd frontend && npm run dev  # localhost:5173 → proxy → :8000

# 测试
cd agents && venv\Scripts\python -m pytest tests/ -v
```
