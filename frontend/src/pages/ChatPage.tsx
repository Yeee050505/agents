import { useState, useRef, useEffect } from 'react';
import { useAuth } from '../hooks/useAuth';
import { useChat } from '../hooks/useChat';
import Sidebar from '../components/Sidebar';
import ChatMessages from '../components/ChatMessage';
import RightPanel from '../components/RightPanel';

interface Props {
  onLogout: () => void;
}

export default function ChatPage({ onLogout }: Props) {
  const { userId } = useAuth();
  const {
    sessions, currentSid, currentMessages, streaming,
    sendMessage, newSession, switchSession, clearCurrentSession, deleteSession,
  } = useChat(userId);
  const [input, setInput] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput('');
    sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 120) + 'px';
    }
  }, [input]);

  // Quick action handler
  const handleQuickAction = (msg: string) => {
    setInput(msg);
    setTimeout(() => {
      const text = msg;
      setInput('');
      sendMessage(text);
    }, 50);
  };

  return (
    <div className="h-screen flex flex-col bg-gray-900">
      {/* Topbar */}
      <header className="h-12 bg-gray-800 border-b border-gray-700 flex items-center px-4 flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-lg">🤖</span>
          <span className="text-sm font-semibold">Multi-Agent Platform</span>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-3 text-xs">
          <span className="text-gray-500">{userId || '访客'}</span>
        </div>
      </header>

      {/* Main Layout */}
      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          sessions={sessions}
          currentSid={currentSid}
          onSwitch={switchSession}
          onNew={newSession}
          onClear={clearCurrentSession}
          onDelete={deleteSession}
        />

        {/* Chat Area */}
        <div className="flex-1 flex flex-col">
          <ChatMessages messages={currentMessages} streaming={streaming} />

          {/* Input Area */}
          {currentMessages.length === 0 && (
            <div className="flex flex-wrap gap-2 justify-center px-4 pb-3">
              {[
                { label: '📝 写文案', msg: '帮我写一段小红书文案' },
                { label: '🔥 热点分析', msg: '分析一下今天的热点话题' },
                { label: '🎨 生成提示词', msg: '帮我生成一张图片的提示词' },
                { label: 'ℹ️ 平台介绍', msg: '我想了解这个平台的功能' },
              ].map(({ label, msg }) => (
                <button
                  key={label}
                  onClick={() => handleQuickAction(msg)}
                  className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-full text-xs cursor-pointer hover:bg-gray-700 transition text-gray-300"
                >{label}</button>
              ))}
            </div>
          )}

          <div className="border-t border-gray-700 p-4">
            <div className="max-w-4xl mx-auto relative">
              <textarea
                ref={inputRef}
                rows={1}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入消息，Enter 发送，Shift+Enter 换行"
                maxLength={4096}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 pr-12 text-sm resize-none outline-none focus:border-blue-500 transition placeholder-gray-500"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || streaming}
                className="absolute right-2 bottom-2 w-8 h-8 flex items-center justify-center bg-blue-600 hover:bg-blue-700 disabled:opacity-40 rounded-lg transition text-sm"
              >➤</button>
            </div>
            <div className="max-w-4xl mx-auto text-right mt-1">
              <span className="text-xs text-gray-600">{input.length} / 4096</span>
            </div>
          </div>
        </div>

        <RightPanel />
      </div>
    </div>
  );
}
