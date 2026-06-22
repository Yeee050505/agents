import type { ApiResponse, RateLimitStats, MCPTool, KBDocument, LoRAAdapter } from '../types';

const API_BASE = '/api/v1';

function getToken(): string | null {
  return localStorage.getItem('token');
}

export async function apiPost<T>(path: string, body?: unknown): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(API_BASE + path, { method: 'POST', headers, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 401) { localStorage.removeItem('token'); localStorage.removeItem('userId'); window.location.reload(); }
  return res.json();
}

export async function apiGet<T>(path: string): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(API_BASE + path, { headers });
  if (res.status === 401) { localStorage.removeItem('token'); localStorage.removeItem('userId'); window.location.reload(); }
  return res.json();
}

export async function apiDelete<T>(path: string): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(API_BASE + path, { method: 'DELETE', headers });
  if (res.status === 401) { localStorage.removeItem('token'); localStorage.removeItem('userId'); window.location.reload(); }
  return res.json();
}

// Auth
export const login = (userId: string, password: string) =>
  apiPost<{ token: string; user_id: string }>('/auth/login', { user_id: userId, password });
export const register = (userId: string, password: string) =>
  apiPost<{ token: string; user_id: string }>('/auth/register', { user_id: userId, password });
export const healthCheck = () => apiGet('/health');

// Chat
export const sendChat = (message: string, userId?: string | null, sessionId?: string) =>
  apiPost<{ answer: string; intent: string; session_id: string; loop_count: number }>('/chat', { message, user_id: userId, session_id: sessionId });

// Streaming - returns EventSource-compatible reader
export function streamChat(message: string, userId?: string | null, sessionId?: string): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return fetch(API_BASE + '/chat/stream', {
    method: 'POST',
    headers,
    body: JSON.stringify({ message, user_id: userId, session_id: sessionId }),
  });
}

// Stats
export const getRateStats = () => apiGet<RateLimitStats>('/rate-limit/stats');

// Session
export const clearSession = (sessionId: string) => apiDelete(`/session/${sessionId}`);

// MCP
export const getMCPTools = () => apiGet<MCPTool[]>('/mcp/tools');

// Knowledge Base
export const getKBDocs = () => apiGet<KBDocument[]>('/kb/documents');
export const deleteKBDoc = (docId: string) => apiDelete(`/kb/documents/${docId}`);
export async function uploadKB(file: File): Promise<ApiResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(API_BASE + '/kb/upload', { method: 'POST', headers, body: formData });
  return res.json();
}

// LoRA
export const getLoRAStatus = () => apiGet<{ available: boolean; device: string; base_model: string; adapters: Record<string, LoRAAdapter> }>('/lora/status');
export const getLoRAAdapters = () => apiGet<Record<string, LoRAAdapter>>('/lora/adapters');
