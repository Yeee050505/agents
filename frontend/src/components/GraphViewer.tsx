import { useState, useEffect, useRef } from 'react';
import type { WorkflowGraph, NodeStatus, SnapshotInfo } from '../types';
import { getGraphWorkflow } from '../api/client';

const NODE_COLORS: Record<NodeStatus, string> = {
  idle: '#4B5563',
  running: '#FBBF24',
  done: '#34D399',
  error: '#EF4444',
  failed: '#F97316',
};

const LAYER: Record<string, number> = {
  planner: 0, retriever: 1, tool: 1, summarizer: 2, validator: 3,
};
const NODE_BY_PHASE: Record<number, string> = { 0: 'planner', 1: 'planner', 2: 'tool', 3: 'summarizer', 4: 'validator' };
const PHASE_BY_NODE: Record<string, number> = { planner: 1, retriever: 2, tool: 2, summarizer: 3, validator: 4 };

interface Props {
  sessionId?: string;
}

function calcPositions(graph: WorkflowGraph) {
  const cx = (layer: number) => 50 + layer * 160;
  const yMap: Record<string, number> = {
    planner: 30, retriever: 65, tool: 65, summarizer: 100, validator: 135, __end__: 135,
  };
  const pos: Record<string, { x: number; y: number }> = {};
  graph.nodes.forEach(n => {
    const layer = LAYER[n.id] ?? 99;
    const x = cx(layer);
    if (n.id === 'retriever') pos[n.id] = { x: x - 50, y: yMap[n.id] || 50 };
    else if (n.id === 'tool') pos[n.id] = { x: x + 50, y: yMap[n.id] || 50 };
    else pos[n.id] = { x, y: yMap[n.id] || 50 };
  });
  pos.__end__ = { x: cx(4), y: yMap.__end__ || 50 };
  return pos;
}

export default function GraphViewer({ sessionId }: Props) {
  const [graph, setGraph] = useState<WorkflowGraph | null>(null);
  const [nodeStatus, setNodeStatus] = useState<Record<string, NodeStatus>>({});
  const [snapshots, setSnapshots] = useState<SnapshotInfo[]>([]);
  const [highlightNode, setHighlightNode] = useState('');
  const [showModal, setShowModal] = useState(false);
  const statusRef = useRef(nodeStatus);

  useEffect(() => {
    getGraphWorkflow().then(r => {
      if (r.code === 200) setGraph(r.data);
    });
  }, []);

  useEffect(() => {
    if (!sessionId) { setSnapshots([]); return; }
    fetch(`/api/v1/harness/checkpoints/${sessionId}?include_deleted=false`)
      .then(r => r.json())
      .then(r => { if (r.code === 200) setSnapshots(r.data.snapshots || []); })
      .catch(() => setSnapshots([]));
  }, [sessionId]);

  useEffect(() => { statusRef.current = nodeStatus; }, [nodeStatus]);

  useEffect(() => {
    const handler = (e: CustomEvent) => {
      const detail = e.detail;
      if (detail.event === 'step') {
        const map: Record<string, string> = {
          retriever_tool: 'retriever_tool', planner: 'planner',
          retriever: 'retriever_tool', tool: 'retriever_tool',
          summarizer: 'summarizer', validator: 'validator',
        };
        const key = map[detail.agent] || detail.agent;
        if (key) setNodeStatus(prev => ({ ...prev, [key]: detail.status === 'running' ? 'running' : 'done' }));
      }
      if (detail.event === 'pause') setNodeStatus(prev => ({ ...prev, [detail.agent]: 'failed' }));
      if (detail.event === 'done' || detail.event === 'error') setNodeStatus({});
    };
    window.addEventListener('agent-step', handler as EventListener);
    return () => window.removeEventListener('agent-step', handler as EventListener);
  }, []);

  useEffect(() => {
    const handler = (e: CustomEvent) => setHighlightNode(e.detail.nodeId || '');
    window.addEventListener('checkpoint-highlight-node', handler as EventListener);
    return () => window.removeEventListener('checkpoint-highlight-node', handler as EventListener);
  }, []);

  const hasSnapshot = (nodeId: string) => snapshots.some(s => s.node === nodeId && s.status !== 'deleted');

  const handleDotClick = (phase: number) => {
    if (!sessionId) return;
    window.dispatchEvent(new CustomEvent('checkpoint-dot-click', {
      detail: { sessionId, phase, nodeId: NODE_BY_PHASE[phase] || '' },
    }));
  };

  const nodeStatusSummary = () => {
    const ids = ['validator', 'summarizer', 'retriever', 'tool', 'planner'] as const;
    for (const n of ids) {
      const s = nodeStatus[n];
      if (s === 'running') return { color: 'bg-yellow-400', text: '运行中' };
      if (s === 'error') return { color: 'bg-red-400', text: '异常' };
      if (s === 'failed') return { color: 'bg-orange-400', text: '待干预' };
      if (s === 'done') return { color: 'bg-green-400', text: '已完成' };
    }
    return { color: 'bg-gray-500', text: '空闲' };
  };
  const status = nodeStatusSummary();

  if (!graph) {
    return <p className="text-gray-600 text-xs">加载流程图...</p>;
  }

  const nodePositions = calcPositions(graph);

  return (
    <>
      <svg viewBox="15 10 710 180" className="w-full h-auto cursor-pointer hover:opacity-90 transition-opacity bg-gray-750 border border-gray-700 rounded-lg p-1"
        onClick={() => setShowModal(true)}>
        {svgGraph(graph, nodePositions, nodeStatus, highlightNode, hasSnapshot, handleDotClick, 1, 1)}
      </svg>

      {showModal && (
        <GraphModal graph={graph}
          nodeStatus={nodeStatus} highlightNode={highlightNode}
          hasSnapshot={hasSnapshot} handleDotClick={handleDotClick}
          onClose={() => setShowModal(false)} />
      )}
    </>
  );
}

function GraphModal({ graph, nodeStatus, highlightNode, hasSnapshot, handleDotClick, onClose }: {
  graph: WorkflowGraph; nodeStatus: Record<string, NodeStatus>; highlightNode: string;
  hasSnapshot: (id: string) => boolean; handleDotClick: (p: number) => void; onClose: () => void;
}) {
  const [zoom, setZoom] = useState(1.5);
  const [uiOpacity, setUiOpacity] = useState(100);
  const nodePositions = calcPositions(graph);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" style={{ opacity: uiOpacity / 100 }} onClick={onClose}>
      <div className="bg-gray-900 rounded-xl p-6 border border-gray-700 shadow-2xl w-[95vw] h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3 shrink-0">
          <h3 className="text-base font-semibold text-gray-200">Agent 流程图</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-xl leading-none">&times;</button>
        </div>
        {/* Controls */}
        <div className="flex items-center gap-6 mb-3 shrink-0 text-[10px] text-gray-500">
          <div className="flex items-center gap-2">
            <span>缩放</span>
            <input type="range" min={1} max={4} step={0.1} value={zoom}
              onChange={e => setZoom(parseFloat(e.target.value))}
              className="w-20 accent-blue-500 h-1 cursor-pointer" />
            <span className="font-mono w-6 text-right">{zoom.toFixed(1)}x</span>
          </div>
          <div className="flex items-center gap-2">
            <span>面板透明度</span>
            <input type="range" min={10} max={100} value={uiOpacity}
              onChange={e => setUiOpacity(parseInt(e.target.value))}
              className="w-20 accent-blue-500 h-1 cursor-pointer" />
            <span className="font-mono w-6 text-right">{uiOpacity}%</span>
          </div>
        </div>
        <div className="flex-1 min-h-0 overflow-auto flex items-start justify-center">
          <div style={{ transform: `scale(${zoom})`, transformOrigin: 'top center' }} className="shrink-0">
            <svg viewBox="0 0 720 240" className="w-[720px] h-auto"
              preserveAspectRatio="xMidYMid meet">
              <defs>
                <marker id="arrowGray" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" orient="auto">
                  <path d="M0,0 L10,5 L0,10 Z" fill="#6B7280" />
                </marker>
                <marker id="arrowYellow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" orient="auto">
                  <path d="M0,0 L10,5 L0,10 Z" fill="#FBBF24" />
                </marker>
              </defs>
              {svgGraph(graph, nodePositions, nodeStatus, highlightNode, hasSnapshot, handleDotClick, 1, 1)}
            </svg>
          </div>
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-1 mt-3 shrink-0 text-[10px] text-gray-500 justify-center">
          <span className="flex items-center gap-1"><span className="w-3 h-[3px] rounded bg-green-400" /> 并行扇出</span>
          <span className="flex items-center gap-1"><span className="w-3 h-[3px] rounded bg-purple-400" /> 并行汇聚</span>
          <span className="flex items-center gap-1"><span className="w-3 h-[3px] rounded bg-yellow-400" /> 条件重写</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-gray-500" /> 空闲</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-yellow-400" /> 运行中</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-green-400" /> 完成</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-400" /> 错误</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-blue-500" /> 有检查点</span>
        </div>
      </div>
    </div>
  );
}

function roundPath(pts: { x: number; y: number }[], r: number): string {
  if (pts.length < 2) return '';
  let d = `M ${pts[0].x},${pts[0].y}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const a = pts[i - 1], b = pts[i], c = pts[i + 1];
    const dxa = b.x - a.x, dya = b.y - a.y;
    const dxc = c.x - b.x, dyc = c.y - b.y;
    const la = Math.sqrt(dxa * dxa + dya * dya);
    const lc = Math.sqrt(dxc * dxc + dyc * dyc);
    const ri = Math.min(r, la / 2, lc / 2);
    d += ` L ${b.x - (dxa / la) * ri},${b.y - (dya / la) * ri}`;
    d += ` Q ${b.x},${b.y} ${b.x + (dxc / lc) * ri},${b.y + (dyc / lc) * ri}`;
  }
  const last = pts[pts.length - 1];
  d += ` L ${last.x},${last.y}`;
  return d;
}

const EDGE_COLORS: Record<string, string> = {
  branch: '#10B981',   // 扇出绿
  merge: '#8B5CF6',    // 汇聚紫
  loop: '#FBBF24',     // 循环黄
  default: '#6B7280',  // 默认灰
};

function edgePath(from: { x: number; y: number }, to: { x: number; y: number }, fromId: string, toId: string, w: number, h: number, style?: string) {
  const R = 6;
  const isLoop = style === 'loop';
  const color = EDGE_COLORS[style || 'default'] || EDGE_COLORS.default;
  const marker = isLoop ? 'url(#arrowYellow)' : 'url(#arrowGray)';

  // Loop: validator → summarizer —绕下穿行，从左侧接入摘要左边缘（箭头朝右）
  if (isLoop) {
    const sx = from.x;
    const sy = from.y + h / 2;
    const ex = to.x - w / 2;
    const ey = to.y;
    const by = sy + 35;
    const leftX = 300;
    const pts = [
      { x: sx, y: sy }, { x: sx, y: by }, { x: leftX, y: by }, { x: leftX, y: ey }, { x: ex, y: ey },
    ];
    return { d: roundPath(pts, R), marker, color, dashed: true, lx: (sx + leftX) / 2, ly: by - 6 };
  }

  const sx = from.x + w / 2;
  const sy = from.y;
  const ex = to.x - w / 2;
  const ey = to.y;

  // Branch / merge: orthogonal Z 形折线
  if (style === 'branch' || style === 'merge') {
    const mid = style === 'branch' ? 120 : 315;
    const pts = [
      { x: sx, y: sy }, { x: mid, y: sy }, { x: mid, y: ey }, { x: ex, y: ey },
    ];
    return { d: roundPath(pts, R), marker, color, dashed: false, lx: mid + 10, ly: sy - 8 };
  }

  // Default: orthogonal L-shape with rounded corner
  const mx = (sx + ex) / 2;
  const pts = [
    { x: sx, y: sy }, { x: mx, y: sy }, { x: mx, y: ey }, { x: ex, y: ey },
  ];
  return { d: roundPath(pts, R), marker, color, dashed: false, lx: mx, ly: sy - 8 };
}

function svgGraph(
  graph: WorkflowGraph,
  nodePositions: Record<string, { x: number; y: number }>,
  nodeStatus: Record<string, NodeStatus>,
  highlightNode: string,
  hasSnapshot: (id: string) => boolean,
  handleDotClick: (p: number) => void,
  scale: number,
  opacity = 1,
) {
  const nodeW = 50 * scale;
  const nodeH = 24 * scale;
  const fontSize = 9 * scale;
  const edgeW = 1.5 * scale;
  const dotR = 6 * scale;
  const labelSize = 8 * scale;

  const retrieverPos = nodePositions['retriever'];
  const toolPos = nodePositions['tool'];

  return (
    <g>
      {/* Parallel execution region */}
      {retrieverPos && toolPos && (() => {
        const rx = retrieverPos.x - nodeW / 2 - 8;
        const ry = Math.min(retrieverPos.y, toolPos.y) - nodeH / 2 - 8;
        const rw = (toolPos.x + nodeW / 2 + 8) - rx;
        const rh = Math.max(retrieverPos.y, toolPos.y) + nodeH / 2 + 8 - ry;
        return (
          <g>
            <rect x={rx} y={ry} width={rw} height={rh} rx={10}
              fill="none" stroke="#10B981" strokeWidth={1}
              strokeDasharray="4,3" opacity={0.5} />
            <text x={rx + 6} y={ry - 4} fill="#10B981" fontSize={9}
              textAnchor="start" fontWeight={600}>并行执行</text>
          </g>
        );
      })()}
      {graph.edges.map((e, i) => {
        const from = nodePositions[e.from] || { x: 0, y: 0 };
        const to = nodePositions[e.to] || { x: 0, y: 0 };
        const ep = edgePath(from, to, e.from, e.to, nodeW, nodeH, e.style);
        return (
          <g key={i}>
            <path d={ep.d} fill="none" stroke={ep.color} strokeWidth={edgeW}
              strokeDasharray={ep.dashed ? '4,3' : 'none'}
              markerEnd={ep.marker} />
            {e.label && <text x={ep.lx} y={ep.ly} textAnchor="middle" fill="#9CA3AF" fontSize={labelSize}>{e.label}</text>}
          </g>
        );
      })}
      {graph.nodes.map(n => {
        const pos = nodePositions[n.id] || { x: 0, y: 0 };
        const status = nodeStatus[n.id] || 'idle';
        const color = NODE_COLORS[status];
        const cp = hasSnapshot(n.id);
        const isHighlighted = highlightNode === n.id;

        return (
          <g key={n.id}>
            {cp && (
              <circle cx={pos.x + nodeW + 6} cy={pos.y - nodeH / 2} r={dotR}
                fill="#3B82F6" stroke="#60A5FA" strokeWidth={1.5}
                className="cursor-pointer hover:fill-blue-400 transition-colors"
                onClick={() => { const p = PHASE_BY_NODE[n.id]; if (p) handleDotClick(p); }}>
                <title>有检查点 - 点击打开管理面板</title>
              </circle>
            )}
            <rect x={pos.x} y={pos.y - nodeH / 2} width={nodeW} height={nodeH} rx={8}
              fill={color + Math.round(opacity * 48).toString(16).padStart(2, '0')}
              stroke={isHighlighted ? '#60A5FA' : color}
              strokeWidth={isHighlighted ? 3 : (status === 'running' ? 2.5 : 1.5)} />
            <text x={pos.x + nodeW / 2} y={pos.y + fontSize / 3} textAnchor="middle" fill="#E5E7EB" fontSize={fontSize} fontWeight={500}>
              {n.label}
            </text>
          </g>
        );
      })}
    </g>
  );
}
