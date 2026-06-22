import { useAuth } from '../hooks/useAuth';
import type { Session } from '../types';

interface Props {
  sessions: Record<string, Session>;
  currentSid: string;
  onSwitch: (sid: string) => void;
  onNew: () => void;
  onClear: () => void;
  onDelete: (sid: string) => void;
}

export default function Sidebar({ sessions, currentSid, onSwitch, onNew, onClear, onDelete }: Props) {
  const { userId, logout } = useAuth();

  return (
    <div className="w-64 bg-gray-800 border-r border-gray-700 flex flex-col flex-shrink-0">
      {/* Header */}
      <div className="p-3 border-b border-gray-700 flex items-center justify-between">
        <span className="text-xs font-medium text-gray-400">会话列表</span>
        <button onClick={onNew} className="w-6 h-6 flex items-center justify-center text-gray-400 hover:text-white hover:bg-gray-700 rounded transition" title="新建会话">＋</button>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {Object.entries(sessions).map(([sid, session]) => (
          <div
            key={sid}
            className={`group flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer text-sm transition ${
              sid === currentSid ? 'bg-blue-600/20 text-blue-300 border border-blue-600/30' : 'text-gray-400 hover:bg-gray-700 hover:text-gray-200'
            }`}
            onClick={() => onSwitch(sid)}
          >
            <span className="truncate flex-1">{sid === 'default' ? '默认会话' : `会话 ${sid.slice(-6)}`}</span>
            {sid !== 'default' && (
              <button
                onClick={e => { e.stopPropagation(); onDelete(sid); }}
                className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-300 text-xs ml-2"
              >✕</button>
            )}
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-gray-700 space-y-2">
        <button onClick={onClear} className="w-full text-xs text-gray-500 hover:text-gray-300 transition py-1">清空当前会话</button>
        <div className="flex items-center justify-between text-xs text-gray-500">
          <span>{userId || '访客'}</span>
          {userId && <button onClick={logout} className="text-red-400 hover:text-red-300 transition">退出</button>}
        </div>
      </div>
    </div>
  );
}
