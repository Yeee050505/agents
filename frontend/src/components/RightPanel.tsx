import { useState, useEffect, useCallback } from 'react';
import { getRateStats, getMCPTools, getKBDocs, deleteKBDoc, uploadKB } from '../api/client';
import type { RateLimitStats, MCPTool, KBDocument } from '../types';

export default function RightPanel() {
  const [rateStats, setRateStats] = useState<RateLimitStats | null>(null);
  const [mcpTools, setMcpTools] = useState<MCPTool[]>([]);
  const [kbDocs, setKbDocs] = useState<KBDocument[]>([]);

  const loadAll = useCallback(async () => {
    getRateStats().then(r => r.code === 200 && setRateStats(r.data)).catch(() => {});
    getMCPTools().then(r => r.code === 200 && setMcpTools(r.data)).catch(() => {});
    getKBDocs().then(r => r.code === 200 && setKbDocs(r.data)).catch(() => {});
  }, []);

  useEffect(() => { loadAll(); const t = setInterval(loadAll, 30000); return () => clearInterval(t); }, [loadAll]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadKB(file);
    loadAll();
    e.target.value = '';
  };

  const handleDelete = async (docId: string) => {
    await deleteKBDoc(docId);
    loadAll();
  };

  const poolStats = rateStats?.llm_pool ?? [];
  const alive = poolStats.filter(k => k.state === 'closed').length;
  const degraded = poolStats.filter(k => k.state !== 'closed').length;
  const poolColor = degraded === 0 ? 'text-green-400' : alive === 0 ? 'text-red-400' : 'text-yellow-400';

  return (
    <div className="w-72 bg-gray-800 border-l border-gray-700 flex-shrink-0 overflow-y-auto p-4 space-y-5 text-sm">
      {/* Rate Stats */}
      <section>
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">⚡ 限流状态</h3>
        <div className="space-y-2">
          <div className="flex justify-between">
            <span className="text-gray-500">全局速率</span>
            <span className="font-mono text-xs">{rateStats ? `${rateStats.global.tokens}/${rateStats.global.capacity}` : '--'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">用户速率</span>
            <span className="font-mono text-xs">{rateStats?.user ? `${rateStats.user.tokens}/${rateStats.user.capacity}` : '--'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">API 熔断</span>
            <span className={`font-mono text-xs ${poolColor}`}>{poolStats.length > 0 ? `${alive}正常 ${degraded > 0 ? `${degraded}熔断` : ''}` : '--'}</span>
          </div>
        </div>
      </section>

      {/* MCP Tools */}
      <section>
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">🔧 MCP 工具</h3>
        {mcpTools.length === 0 ? (
          <p className="text-gray-600 text-xs">加载中...</p>
        ) : (
          <div className="space-y-1">
            {mcpTools.map(t => (
              <div key={t.name} className="flex justify-between text-xs">
                <span className="text-gray-300">{t.name}</span>
                <span className="text-gray-600 truncate max-w-[120px]">{t.description.slice(0, 20)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Knowledge Base */}
      <section>
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">📚 知识库</h3>
        <div className="flex gap-1 mb-2">
          <button onClick={() => document.getElementById('kb-input')?.click()} className="flex-1 text-xs text-blue-400 hover:text-blue-300 transition">📄 上传文档</button>
          <button onClick={loadAll} className="text-xs text-gray-500 hover:text-gray-300 transition px-1">🔄</button>
        </div>
        <input id="kb-input" type="file" accept=".txt,.md,.pdf" className="hidden" onChange={handleUpload} />
        {kbDocs.length === 0 ? (
          <p className="text-gray-600 text-xs">暂无文档</p>
        ) : (
          <div className="space-y-1">
            {kbDocs.map(d => (
              <div key={d.doc_id} className="flex items-center justify-between text-xs">
                <span className="text-gray-400 truncate flex-1">{d.file_name}</span>
                <span className="text-gray-600 mx-1">{d.chunks}块</span>
                <button onClick={() => handleDelete(d.doc_id)} className="text-red-400 hover:text-red-300">✕</button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Session Info */}
      <section>
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">📊 会话信息</h3>
        <div className="space-y-1 text-xs">
          <div className="flex justify-between">
            <span className="text-gray-500">节点数</span>
            <span className="text-gray-300">7</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">引擎</span>
            <span className="text-gray-300">LangGraph</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">缓存</span>
            <span className="text-green-400">✓</span>
          </div>
        </div>
      </section>
    </div>
  );
}
