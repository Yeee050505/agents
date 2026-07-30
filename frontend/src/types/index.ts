export interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export interface Session {
  id: string;
  messages: Message[];
}

export interface LLMKeyStatus {
  key_index: number;
  state: string;
  fail_count: number;
  cooldown_until: number | null;
}

export interface RateLimitStats {
  global: { tokens: number; capacity: number };
  user: { tokens: number; capacity: number } | null;
  llm_pool: LLMKeyStatus[];
}

export interface MCPTool {
  name: string;
  description: string;
  inputSchema: unknown;
}

export interface KBDocument {
  doc_id: string;
  file_name: string;
  chunks: number;
  total_chars: number;
}

export interface LoRAAdapter {
  adapter_name: string;
  base_model: string;
  epochs: number;
  num_samples: number;
  loss?: number;
}

export interface ApiResponse<T = unknown> {
  code: number;
  msg: string;
  data: T;
  request_id: string;
}

export interface GraphNode {
  id: string;
  label: string;
  description: string;
}

export interface GraphEdge {
  from: string;
  to: string;
  label: string;
  condition?: string;
  style?: string;
}

export interface WorkflowGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export type NodeStatus = 'idle' | 'running' | 'done' | 'error' | 'failed';

export interface SnapshotInfo {
  snapshot_id: string;
  phase: number;
  node: string;
  label: string;
  timestamp: number;
  tags: string[];
  status: string;
  bind_node_id: string;
  session_id?: string;
}
