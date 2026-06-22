import { useState, useRef, useCallback } from 'react';
import type { Message, Session } from '../types';
import { streamChat, clearSession as apiClearSession } from '../api/client';

export function useChat(userId: string | null) {
  const [sessions, setSessions] = useState<Record<string, Session>>({
    default: { id: 'default', messages: [] },
  });
  const [currentSid, setCurrentSid] = useState('default');
  const [streaming, setStreaming] = useState(false);
  const aborterRef = useRef<AbortController | null>(null);

  const currentMessages = sessions[currentSid]?.messages ?? [];

  const sendMessage = useCallback(async (text: string) => {
    const sid = currentSid;
    const userMsg: Message = { role: 'user', content: text };
    setSessions(prev => ({
      ...prev,
      [sid]: { ...prev[sid], messages: [...(prev[sid]?.messages ?? []), userMsg] },
    }));

    setStreaming(true);
    const assistantMsg: Message = { role: 'assistant', content: '' };
    setSessions(prev => ({
      ...prev,
      [sid]: { ...prev[sid], messages: [...prev[sid].messages, assistantMsg] },
    }));

    try {
      const resp = await streamChat(text, userId, sid);
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
              if (parsed.token) {
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
  }, [currentSid, userId]);

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
    sessions, currentSid, currentMessages, streaming,
    sendMessage, newSession, switchSession, clearCurrentSession, deleteSession,
  };
}
