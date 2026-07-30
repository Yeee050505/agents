import { useState, useRef, useCallback } from 'react';
import type { Message, Session } from '../types';
import { streamChat, flowChat, clearSession as apiClearSession } from '../api/client';

export function useChat(userId: string | null) {
  const [sessions, setSessions] = useState<Record<string, Session>>({
    default: { id: 'default', messages: [] },
  });
  const [currentSid, setCurrentSid] = useState('default');
  const [streaming, setStreaming] = useState(false);
  const [flowMode, setFlowMode] = useState(false);
  const [paused, setPaused] = useState(false);
  const [pauseInfo, setPauseInfo] = useState<{ requestId: string; agent: string; output: string; feedback: string } | null>(null);
  const aborterRef = useRef<AbortController | null>(null);

  const currentMessages = sessions[currentSid]?.messages ?? [];

  const sendMessage = useCallback(async (text: string, humanReview = false) => {
    const sid = currentSid;
    const userMsg: Message = { role: 'user', content: text };
    setSessions(prev => ({
      ...prev,
      [sid]: { ...prev[sid], messages: [...(prev[sid]?.messages ?? []), userMsg] },
    }));

    setStreaming(true);
    setFlowMode(humanReview);
    const assistantMsg: Message = { role: 'assistant', content: '' };
    setSessions(prev => ({
      ...prev,
      [sid]: { ...prev[sid], messages: [...prev[sid].messages, assistantMsg] },
    }));

    try {
      const resp = humanReview ? await flowChat(text, userId, sid, true) : await streamChat(text, userId, sid);
      if (!resp.ok || !resp.body) {
        setSessions(prev => {
          const msgs = [...prev[sid].messages];
          msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], content: `请求失败 (${resp.status})` };
          return { ...prev, [sid]: { ...prev[sid], messages: msgs } };
        });
        setStreaming(false);
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let fullText = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') continue;
            try {
              const parsed = JSON.parse(data);
              if (parsed.event) {
                // Flow mode events
                const event = parsed.event;
                if (event === 'step') {
                  setSessions(prev => {
                    const msgs = [...prev[sid].messages];
                    const statusLine = `[${parsed.agent}] ${parsed.status}`;
                    const last = msgs[msgs.length - 1];
                    if (!last || last.role !== 'assistant') return prev;
                    const lines = last.content.split('\n');
                    if (lines[0].startsWith('[') && lines[0].includes(']')) {
                      lines[0] = statusLine;
                    } else {
                      lines.unshift(statusLine);
                    }
                    msgs[msgs.length - 1] = { ...last, content: lines.join('\n') };
                    return { ...prev, [sid]: { ...prev[sid], messages: msgs } };
                  });
                  window.dispatchEvent(new CustomEvent('agent-step', { detail: parsed }));
                } else if (event === 'token') {
                  fullText += parsed.token;
                  setSessions(prev => {
                    const msgs = [...prev[sid].messages];
                    msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], content: fullText };
                    return { ...prev, [sid]: { ...prev[sid], messages: msgs } };
                  });
                } else if (event === 'pause') {
                  setPaused(true);
                  setPauseInfo({
                    requestId: parsed.request_id,
                    agent: parsed.agent,
                    output: parsed.output || '',
                    feedback: '',
                  });
                } else if (event === 'done') {
                  setPaused(false);
                  setPauseInfo(null);
                } else if (event === 'error') {
                  fullText += `\n[错误] ${parsed.error || '未知错误'}`;
                  setSessions(prev => {
                    const msgs = [...prev[sid].messages];
                    msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], content: fullText };
                    return { ...prev, [sid]: { ...prev[sid], messages: msgs } };
                  });
                }
              } else if (parsed.token) {
                // Simple stream mode
                fullText += parsed.token;
                setSessions(prev => {
                  const msgs = [...prev[sid].messages];
                  msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], content: fullText };
                  return { ...prev, [sid]: { ...prev[sid], messages: msgs } };
                });
              }
            } catch { /* skip parse errors */ }
          }
        }
      }
    } catch (e: unknown) {
      if ((e as Error)?.name !== 'AbortError') {
        setSessions(prev => {
          const msgs = [...prev[sid].messages];
          msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], content: '请求失败，请检查服务状态' };
          return { ...prev, [sid]: { ...prev[sid], messages: msgs } };
        });
      }
    }
    setStreaming(false);
    setFlowMode(false);
    setPaused(false);
    setPauseInfo(null);
  }, [currentSid, userId]);

  const resumeWithAction = useCallback(async (action: string, feedback = '') => {
    if (!pauseInfo) return;
    try {
      const { resumeChat } = await import('../api/client');
      await resumeChat(pauseInfo.requestId, action, feedback);
      setPaused(false);
      setPauseInfo(null);
    } catch {
      // ignore
    }
  }, [pauseInfo]);

  const newSession = useCallback(() => {
    const sid = 'session_' + Date.now();
    setSessions(prev => ({ ...prev, [sid]: { id: sid, messages: [] } }));
    setCurrentSid(sid);
  }, []);

  const switchSession = useCallback((sid: string) => {
    setCurrentSid(sid);
  }, []);

  const clearCurrentSession = useCallback(() => {
    apiClearSession(currentSid).catch(() => {});
    setSessions(prev => ({ ...prev, [currentSid]: { id: currentSid, messages: [] } }));
  }, [currentSid]);

  const deleteSession = useCallback((sid: string) => {
    apiClearSession(sid).catch(() => {});
    setSessions(prev => {
      const next = { ...prev };
      delete next[sid];
      return next;
    });
    if (currentSid === sid) {
      const remaining = Object.keys(sessions).filter(k => k !== sid);
      setCurrentSid(remaining[0] || 'default');
    }
  }, [currentSid, sessions]);

  return {
    sessions, currentSid, currentMessages, streaming, flowMode, paused, pauseInfo,
    sendMessage, resumeWithAction,
    newSession, switchSession, clearCurrentSession, deleteSession,
  };
}
