import { useState, useEffect, useCallback } from 'react';
import { getRateStats, getMCPTools, getKBDocs, deleteKBDoc, uploadKB } from '../api/client';
import type { RateLimitStats, MCPTool, KBDocument, SnapshotInfo } from '../types';
import GraphViewer from './GraphViewer';
import CheckpointModal from './CheckpointModal';

interface Props {
  currentSid?: string;
}

export default function RightPanel({ currentSid }: Props) {
  const [rateStats, setRateStats] = useState<RateLimitStats | null>(null);
  const [mcpTools, setMcpTools] = useState<MCPTool[]>([]);
  const [kbDocs, setKbDocs] = useState<KBDocument[]>([]);
  const [snapshots, setSnapshots] = useState<SnapshotInfo[]>([]);
  const [saving, setSaving] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [showModal, setShowModal] = useState(false);

  const loadSnapshots = useCallback(async () => {
    if (!currentSid) { setSnapshots([]); return; }
    try {
      const r = await fetch(`/api/v1/harness/checkpoints/${currentSid}`);
      const data = await r.json();
      if (data.code === 200) setSnapshots(data.data.snapshots || []);
    } catch { setSnapshots([]); }
  }, [currentSid]);

  const loadAll = useCallback(async () => {
    getRateStats().then(r => r.code === 200 && setRateStats(r.data)).catch(() => {});
    getMCPTools().then(r => r.code === 200 && setMcpTools(r.data)).catch(() => {});
    getKBDocs().then(r => r.code === 200 && setKbDocs(r.data)).catch(() => {});
  }, []);

  useEffect(() => { loadAll(); const t = setInterval(loadAll, 30000); return () => clearInterval(t); }, [loadAll]);

  useEffect(() => { loadSnapshots(); }, [loadSnapshots]);

  // Open modal when graph dot clicked
  useEffect(() => {
    const handler = (e: CustomEvent) => {
      const detail = e.detail;
      if (detail.sessionId === currentSid) setShowModal(true);
    };
    window.addEventListener('checkpoint-dot-click', handler as EventListener);
    return () => window.removeEventListener('checkpoint-dot-click', handler as EventListener);
  }, [currentSid]);

  const handleSave = async () => {
    if (!currentSid || saving) return;
    setSaving(true);
    try {
      const r = await fetch(`/api/v1/harness/checkpoints/${currentSid}/save`, { method: 'POST' });
      const data = await r.json();
      if (data.code === 200) loadSnapshots();
    } finally { setSaving(false); }
  };

  const handleRestore = async (phase?: number) => {
    if (!currentSid || restoring) return;
    setRestoring(true);
    try {
      const r = await fetch(`/api/v1/harness/checkpoints/${currentSid}/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phase }),
      });
      const data = await r.json();
      if (data.code === 200) {
        window.dispatchEvent(new CustomEvent('checkpoint-rollback', { detail: data.data }));
      }
    } finally { setRestoring(false); }
  };

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
  const latestSnap = snapshots.length > 0 ? snapshots[snapshots.length - 1] : null;

  return (
    <div className="w-72 bg-gray-800 border-l border-gray-700 flex-shrink-0 overflow-y-auto p-4 space-y-5 text-sm">
      {/* Rate Stats */}
      <section>
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">限流状态</h3>
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
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">MCP 工具</h3>
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
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">知识库</h3>
        <div className="flex gap-1 mb-2">
          <button onClick={() => document.getElementById('kb-input')?.click()} className="flex-1 text-xs text-blue-400 hover:text-blue-300 transition">上传文档</button>
          <button onClick={loadAll} className="text-xs text-gray-500 hover:text-gray-300 transition px-1">↻</button>
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
                <button onClick={() => handleDelete(d.doc_id)} className="text-red-400 hover:text-red-300">x</button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Checkpoints */}
      <section>
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">检查点</h3>
        {!currentSid ? (
          <p className="text-gray-600 text-xs">请先创建会话</p>
        ) : (
          <>
            {/* Status DIV */}
            <div className="bg-gray-750 rounded p-2 mb-2 text-xs space-y-1">
              <div className="flex justify-between">
                <span className="text-gray-500">快照数</span>
                <span className="font-mono text-gray-300">{snapshots.length}</span>
              </div>
              {latestSnap ? (
                <div className="flex justify-between">
                  <span className="text-gray-500">最新</span>
                  <span className="text-gray-400">{latestSnap.label} ({new Date(latestSnap.timestamp * 1000).toLocaleTimeString()})</span>
                </div>
              ) : (
                <p className="text-gray-600">无快照</p>
              )}
            </div>

            <button onClick={() => setShowModal(true)}
              className="w-full mb-2 px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs text-gray-300 transition">
              管理快照
            </button>

            {/* Three buttons */}
            <div className="flex gap-1">
              <button onClick={handleSave} disabled={saving}
                className="flex-1 px-2 py-1 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 rounded text-xs text-white transition">
                {saving ? '保存中...' : '存快照'}
              </button>
              <button onClick={() => latestSnap && handleRestore()} disabled={restoring || !latestSnap}
                className="flex-1 px-2 py-1 bg-green-700 hover:bg-green-600 disabled:bg-gray-700 rounded text-xs text-white transition">
                {restoring ? '恢复中...' : '恢复最新'}
              </button>
              <div className="relative">
                <button onClick={() => setShowDropdown(!showDropdown)} disabled={snapshots.length === 0}
                  className="px-2 py-1 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 rounded text-xs text-gray-300 transition">
                  ▼
                </button>
                {showDropdown && snapshots.length > 0 && (
                  <div className="absolute right-0 bottom-full mb-1 w-40 bg-gray-700 border border-gray-600 rounded shadow-lg z-10">
                    {snapshots.map(s => (
                      <button key={s.phase}
                        onClick={() => { handleRestore(s.phase); setShowDropdown(false); }}
                        className="w-full text-left px-2 py-1 text-xs text-gray-300 hover:bg-gray-600 transition">
                        {s.label} ({new Date(s.timestamp * 1000).toLocaleTimeString()})
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </section>

      {/* Workflow Graph */}
      <section>
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Agent 流程图</h3>
        <GraphViewer sessionId={currentSid} />
      </section>

      {/* Checkpoint Modal */}
      {showModal && currentSid && (
        <CheckpointModal sessionId={currentSid} onClose={() => { setShowModal(false); loadSnapshots(); }} />
      )}
    </div>
  );
}
