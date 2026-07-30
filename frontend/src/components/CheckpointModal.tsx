import { useState, useEffect, useCallback, useRef } from 'react';
import type { SnapshotInfo } from '../types';

const PAGE_SIZE = 10;

const PHASE_OPTIONS = [
  { value: -1, label: '全部阶段' },
  { value: 0, label: '入口' },
  { value: 1, label: '规划' },
  { value: 2, label: '检索+工具' },
  { value: 3, label: '摘要' },
  { value: 4, label: '校验' },
  { value: 5, label: '手动快照' },
];

interface Props {
  sessionId: string;
  onClose: () => void;
}

export default function CheckpointModal({ sessionId, onClose }: Props) {
  const [snapshots, setSnapshots] = useState<SnapshotInfo[]>([]);
  const [recycleItems, setRecycleItems] = useState<SnapshotInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [filterPhase, setFilterPhase] = useState(-1);
  const [filterTags, setFilterTags] = useState('');
  const [sortAsc, setSortAsc] = useState(false);
  const [selectedId, setSelectedId] = useState('');
  const [rollbackPhase, setRollbackPhase] = useState<number | null>(null);
  const [confirmDel, setConfirmDel] = useState<{ phase: number; permanent?: boolean } | null>(null);
  const [showRecycle, setShowRecycle] = useState(false);
  const [highlightedNode, setHighlightedNode] = useState('');
  const tableRef = useRef<HTMLDivElement>(null);

  // Fetch snapshots
  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [snapR, recycleR] = await Promise.all([
        fetch(`/api/v1/harness/checkpoints/${sessionId}?include_deleted=true`),
        fetch('/api/v1/harness/checkpoints/recycle-bin'),
      ]);
      const snapData = await snapR.json();
      const recycleData = await recycleR.json();
      if (snapData.code === 200) setSnapshots(snapData.data.snapshots || []);
      else setSnapshots([]);
      if (recycleData.code === 200) setRecycleItems(recycleData.data.items || []);
    } catch { setError('加载快照失败'); }
    setLoading(false);
  }, [sessionId]);

  useEffect(() => { loadData(); }, [loadData]);

  // ESC close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  // Listen for dot click from GraphViewer
  useEffect(() => {
    const handler = (e: CustomEvent) => {
      const detail = e.detail;
      if (detail.sessionId === sessionId) {
        setFilterPhase(detail.phase);
        setShowRecycle(false);
        const target = document.getElementById(`cp-row-${detail.phase}`);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    };
    window.addEventListener('checkpoint-dot-click', handler as EventListener);
    return () => window.removeEventListener('checkpoint-dot-click', handler as EventListener);
  }, [sessionId]);

  // Emit highlight when selected row changes
  useEffect(() => {
    if (selectedId) {
      const snap = displaySnapshots.find(s => s.snapshot_id === selectedId);
      if (snap) {
        const nodeId = snap.bind_node_id || snap.node;
        window.dispatchEvent(new CustomEvent('checkpoint-highlight-node', { detail: { nodeId } }));
        setHighlightedNode(nodeId);
      }
    } else {
      window.dispatchEvent(new CustomEvent('checkpoint-highlight-node', { detail: { nodeId: '' } }));
      setHighlightedNode('');
    }
  }, [selectedId]);

  // Filter + sort + paginate
  const filtered = snapshots
    .filter(s => { if (showRecycle) return s.status === 'deleted'; else return s.status !== 'deleted'; })
    .filter(s => filterPhase < 0 || s.phase === filterPhase)
    .filter(s => !filterTags || (s.tags || []).some(t => t.includes(filterTags)))
    .sort((a, b) => sortAsc ? a.timestamp - b.timestamp : b.timestamp - a.timestamp);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const displaySnapshots = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  // Operations
  const handleDelete = async (phase: number, permanent = false) => {
    try {
      await fetch(`/api/v1/harness/checkpoints/${sessionId}?phase=${phase}&permanent=${permanent}`, { method: 'DELETE' });
      loadData();
    } catch { setError('删除失败'); }
    setConfirmDel(null);
  };

  const handleRestore = async (phase: number) => {
    try {
      await fetch(`/api/v1/harness/checkpoints/${sessionId}/${phase}/restore`, { method: 'POST' });
      loadData();
    } catch { setError('恢复失败'); }
  };

  const handleRollback = async (phase: number) => {
    setRollbackPhase(phase);
    try {
      const r = await fetch(`/api/v1/harness/checkpoints/${sessionId}/rollback`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phase }),
      });
      const data = await r.json();
      if (data.code === 200) {
        window.dispatchEvent(new CustomEvent('checkpoint-rollback', { detail: data.data }));
      }
    } catch { setError('回滚失败'); }
    setRollbackPhase(null);
  };

  const currentItems = showRecycle ? recycleItems.filter(r => r.session_id === sessionId) : displaySnapshots;

  const fmtTime = (ts: number) => {
    const d = new Date(ts * 1000);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      {/* Loading overlay during rollback */}
      {rollbackPhase !== null && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/40 rounded">
          <div className="text-white text-sm bg-gray-800 px-4 py-2 rounded shadow">正在回滚阶段 {rollbackPhase}...</div>
        </div>
      )}

      <div className="relative bg-gray-800 rounded-lg shadow-2xl w-[800px] max-h-[80vh] flex flex-col border border-gray-700"
        onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
          <h2 className="text-base font-semibold text-gray-200">
            {showRecycle ? '回收站' : '检查点管理'}
            <span className="ml-2 text-xs text-gray-500 font-normal">{sessionId.slice(0, 16)}...</span>
          </h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-lg leading-none">&times;</button>
        </div>

        {/* Toolbar */}
        <div className="flex items-center gap-3 px-5 py-2 border-b border-gray-700 text-xs">
          <select value={filterPhase} onChange={e => { setFilterPhase(Number(e.target.value)); setPage(1); }}
            className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-gray-300">
            {PHASE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <input value={filterTags} onChange={e => { setFilterTags(e.target.value); setPage(1); }}
            placeholder="筛选标签..." className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-gray-300 w-28" />
          <button onClick={() => { setSortAsc(!sortAsc); setPage(1); }}
            className="px-2 py-1 bg-gray-700 rounded text-gray-400 hover:text-gray-200">
            {sortAsc ? '最早' : '最新'}
          </button>
          <button onClick={() => { setShowRecycle(!showRecycle); setPage(1); }}
            className={`px-2 py-1 rounded ${showRecycle ? 'bg-yellow-700 text-yellow-200' : 'bg-gray-700 text-gray-400 hover:text-gray-200'}`}>
            回收站 ({recycleItems.filter(r => r.session_id === sessionId).length})
          </button>
          <button onClick={loadData} className="px-2 py-1 bg-gray-700 rounded text-gray-400 hover:text-gray-200 ml-auto">
            &#x21bb; 刷新
          </button>
        </div>

        {/* Table */}
        <div ref={tableRef} className="flex-1 overflow-y-auto p-0">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-gray-500 text-sm">加载中...</div>
          ) : error ? (
            <div className="flex items-center justify-center py-16 text-red-400 text-sm">{error}</div>
          ) : currentItems.length === 0 ? (
            <div className="flex items-center justify-center py-16 text-gray-600 text-sm">
              {showRecycle ? '回收站为空' : '暂无快照，请先创建'}
            </div>
          ) : (
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700 sticky top-0 bg-gray-800">
                  <th className="text-left px-3 py-2 font-medium">快照 ID</th>
                  <th className="text-left px-3 py-2 font-medium">阶段</th>
                  <th className="text-left px-3 py-2 font-medium">标签</th>
                  <th className="text-left px-3 py-2 font-medium">创建时间</th>
                  <th className="text-left px-3 py-2 font-medium">绑定节点</th>
                  <th className="text-left px-3 py-2 font-medium">状态</th>
                  <th className="text-left px-3 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {currentItems.map((s, i) => {
                  const isSelected = s.snapshot_id === selectedId;
                  const isDeleted = s.status === 'deleted';
                  const isRolling = rollbackPhase === s.phase;
                  return (
                    <tr key={s.snapshot_id} id={`cp-row-${s.phase}`}
                      onClick={() => setSelectedId(s.snapshot_id)}
                      onMouseEnter={() => {
                        const nodeId = s.bind_node_id || s.node;
                        window.dispatchEvent(new CustomEvent('checkpoint-highlight-node', { detail: { nodeId } }));
                      }}
                      onMouseLeave={() => {
                        if (selectedId !== s.snapshot_id)
                          window.dispatchEvent(new CustomEvent('checkpoint-highlight-node', { detail: { nodeId: '' } }));
                      }}
                      className={`border-b border-gray-750 cursor-pointer transition ${isSelected ? 'bg-blue-900/30 ring-1 ring-blue-500' : 'hover:bg-gray-750'} ${i % 2 === 0 ? 'bg-gray-800/50' : ''}`}>
                      <td className="px-3 py-2 text-gray-400 font-mono">{s.snapshot_id.slice(-16)}</td>
                      <td className="px-3 py-2">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${phaseColor(s.phase)}`}>
                          {s.label}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          {(s.tags || []).length > 0 ? s.tags.map(t => (
                            <span key={t} className="px-1 bg-blue-900/50 text-blue-300 rounded text-[10px]">{t}</span>
                          )) : <span className="text-gray-600">--</span>}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-gray-400">{fmtTime(s.timestamp)}</td>
                      <td className="px-3 py-2 text-gray-400 font-mono text-[10px]">{s.bind_node_id || s.node || '--'}</td>
                      <td className="px-3 py-2">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] ${isDeleted ? 'bg-red-900/40 text-red-300' : 'bg-green-900/40 text-green-300'}`}>
                          {isDeleted ? '已删除' : '正常'}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex gap-1">
                          {isDeleted ? (
                            <>
                              <button onClick={() => handleRestore(s.phase)}
                                className="px-1.5 py-0.5 bg-green-800 hover:bg-green-700 rounded text-[10px] text-green-200">恢复</button>
                              <button onClick={() => setConfirmDel({ phase: s.phase, permanent: true })}
                                className="px-1.5 py-0.5 bg-red-900 hover:bg-red-800 rounded text-[10px] text-red-200">彻底删除</button>
                            </>
                          ) : (
                            <>
                              <button onClick={() => handleRollback(s.phase)} disabled={isRolling}
                                className="px-1.5 py-0.5 bg-blue-700 hover:bg-blue-600 disabled:bg-gray-700 rounded text-[10px] text-blue-200">
                                {isRolling ? '回滚中' : '回滚'}
                              </button>
                              <button onClick={() => setConfirmDel({ phase: s.phase })}
                                className="px-1.5 py-0.5 bg-red-800 hover:bg-red-700 rounded text-[10px] text-red-200">删除</button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between px-5 py-2 border-t border-gray-700 text-xs text-gray-500">
          <span>共 {filtered.length} 条，第 {safePage}/{totalPages} 页</span>
          <div className="flex gap-1">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={safePage <= 1}
              className="px-2 py-1 bg-gray-700 rounded disabled:opacity-40 hover:bg-gray-600">上一页</button>
            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={safePage >= totalPages}
              className="px-2 py-1 bg-gray-700 rounded disabled:opacity-40 hover:bg-gray-600">下一页</button>
          </div>
        </div>
      </div>

      {/* Delete confirmation dialog */}
      {confirmDel && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40" onClick={() => setConfirmDel(null)}>
          <div className="bg-gray-800 rounded-lg p-5 border border-gray-700 w-80 shadow-xl" onClick={e => e.stopPropagation()}>
            <p className="text-sm text-gray-200 mb-3">
              {confirmDel.permanent ? '确定彻底删除此快照？不可恢复。' : '确定将快照移入回收站？'}
            </p>
            <p className="text-xs text-gray-500 mb-4">阶段 {confirmDel.phase}</p>
            <div className="flex gap-2 justify-end">
              <button onClick={() => setConfirmDel(null)} className="px-3 py-1.5 text-xs bg-gray-700 rounded text-gray-300 hover:bg-gray-600">取消</button>
              <button onClick={() => handleDelete(confirmDel.phase, confirmDel.permanent)}
                className="px-3 py-1.5 text-xs bg-red-700 rounded text-red-200 hover:bg-red-600">确认</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function phaseColor(phase: number): string {
  const map: Record<number, string> = {
    0: 'bg-gray-700 text-gray-300',
    1: 'bg-purple-900/50 text-purple-300',
    2: 'bg-blue-900/50 text-blue-300',
    3: 'bg-green-900/50 text-green-300',
    4: 'bg-yellow-900/50 text-yellow-300',
    5: 'bg-teal-900/50 text-teal-300',
  };
  return map[phase] || 'bg-gray-700 text-gray-300';
}
