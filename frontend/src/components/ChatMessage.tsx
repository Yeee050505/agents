import type { Message } from '../types';
import { useEffect, useRef } from 'react';

interface Props {
  messages: Message[];
  streaming: boolean;
}

export default function ChatMessage({ messages, streaming }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-center p-8">
        <div>
          <div className="text-6xl mb-4">🤖</div>
          <h2 className="text-xl font-semibold mb-2">欢迎使用多智能体平台</h2>
          <p className="text-gray-400 text-sm mb-6">基于 LangGraph + DeepSeek 构建，支持意图识别、多轮对话、流式输出</p>
          <div className="flex flex-wrap gap-2 justify-center">
            {[
              { label: '📝 写文案', msg: '帮我写一段小红书文案' },
              { label: '🔥 热点分析', msg: '分析一下今天的热点话题' },
              { label: '🎨 生成提示词', msg: '帮我生成一张图片的提示词' },
              { label: 'ℹ️ 平台介绍', msg: '我想了解这个平台的功能' },
            ].map(({ label, msg }) => (
              <span key={label} className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-full text-xs cursor-pointer hover:bg-gray-700 transition">{label}</span>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {messages.map((msg, i) => (
        <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : ''}`}>
          {msg.role === 'assistant' && <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-sm flex-shrink-0">🤖</div>}
          <div className={`max-w-[70%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words ${
            msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-800 border border-gray-700 text-gray-100'
          }`}>
            {msg.content || (i === messages.length - 1 && streaming && <span className="inline-block w-2 h-4 bg-blue-400 animate-pulse" />)}
          </div>
          {msg.role === 'user' && <div className="w-8 h-8 rounded-full bg-green-600 flex items-center justify-center text-sm flex-shrink-0">👤</div>}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
