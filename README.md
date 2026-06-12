# 多智能体协作集成（MACE）

## 技术栈

FastAPI、SQLAlchemy、SQLite、LangChain、DeepSeek、PyJWT、Redis、BeautifulSoup4、HTML5、CSS3、JavaScript、Docker、Git

## 项目描述

1. **多 Agent 协作编排**：自研 AgentGraph 图式调度引擎，构建 3 类 Worker Agent（代码/知识/闲聊）+ 1 个意图路由器 + 1 个 Supervisor 质检节点的多智能体协作体系。实现 intent 路由 → 子 Agent 执行 → Supervisor 审查 → 纠错重试的闭环决策回路，闲聊场景直出跳过审查。

2. **LLM 高可用密钥池**：设计三态断路器（CLOSED → OPEN → HALF_OPEN），基于指数退避算法（10s→120s）自动熔断与恢复；支持多 API Key 池化负载，单 Key 故障零秒切换。Redis Lua 脚本实现分布式令牌桶限流，内存 Token Bucket 降级兜底。

3. **联网搜索与知识时效补足**：集成 Bing + 百度双搜索引擎降级链路，自动检测用户消息中 16 个关键词触发联网搜索；内置 14 个过时响应标记检测，大模型回复显示知识过时时自动搜后重试。

4. **会话级上下文记忆**：基于 session_id 实现会话历史隔离持久化，Redis 优先 + 内存降级双模存储，1 小时 TTL 自动过期，最多保留 20 轮对话上下文。Agent 执行前加载历史、执行后自动保存。

5. **安全与权限体系**：基于 PyJWT 实现 Token 鉴权与过期检测，SHA-256 密码哈希加密；内置 Token 黑名单机制、全局 + 用户级双层分布式限流，jieba 敏感词过滤。

6. **前端交互开发**：采用原生 HTML+CSS+JS 开发全栈前端，实现登录注册、多会话管理、实时聊天、限流熔断状态看板等完整交互功能。AJAX 异步对接后端 8 个 RESTful 接口，零第三方前端框架依赖。

7. **异步架构与缓存防护**：全链路 asyncio 异步架构，ChatOpenAI 实例按 Key 缓存复用；缓存穿透（空值标记）、缓存雪崩（TTL 抖动）防护策略保障高并发下 LLM 响应稳定性。

8. **智能化 Agent 能力**：集成 LangChain ChatOpenAI 封装 DeepSeek 大模型调用。intent 节点 temperature=0.1 加速意图识别，各子 Agent 分派专用 System Prompt，Supervisor 质检不满意自动退栈重答，最多 3 轮纠错，降低大模型幻觉。

## 项目总结

独立完成多智能体协作平台前后端全流程开发，构建了覆盖多 Agent 调度编排、断路器熔断降级、联网搜索增强、会话记忆持久化的完整解决方案。掌握 FastAPI 全异步开发、LangChain Agent 集成、断路器设计模式、Redis 分布式限流与会话持久化、Docker 容器化部署的工程实践能力。
