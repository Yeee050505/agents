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
    planner: 25, retriever: 50, tool: 80, summarizer: 110, validator: 145, __end__: 145,
  };
  const pos: Record<string, { x: number; y: number }> = {};
  graph.nodes.forEach(n => {
    const layer = LAYER[n.id] ?? 99;
    pos[n.id] = { x: cx(layer), y: yMap[n.id] || 50 };
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
      <svg viewBox="15 10 710 200" className="w-full h-auto cursor-pointer hover:opacity-90 transition-opacity bg-gray-750 border border-gray-700 rounded-lg p-1"
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
  const nodePositions = calcPositions(graph);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div className="bg-gray-900 rounded-xl p-6 border border-gray-700 shadow-2xl w-[95vw] h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3 shrink-0">
          <h3 className="text-base font-semibold text-gray-200">Agent 流程图</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-xl leading-none">&times;</button>
        </div>
        {/* Controls — 定稿版移除调试控件 */}
        <div className="flex-1 min-h-0 overflow-auto flex items-start justify-center">
          <div style={{ transform: 'scale(1.5)', transformOrigin: 'top center' }} className="shrink-0">
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
        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 shrink-0 text-[10px] text-gray-400 justify-center">
          <span className="flex items-center gap-1"><span className="w-3 h-[3px] rounded bg-green-400" /> 分发流</span>
          <span className="flex items-center gap-1"><span className="w-3 h-[3px] rounded bg-purple-400" /> 汇总流</span>
          <span className="flex items-center gap-1"><span className="w-3 h-[3px] rounded bg-yellow-400" /> 迭代回路</span>
          <span className="flex items-center gap-1"><span className="w-3 h-[3px] rounded bg-gray-400" /> 校验流</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-gray-600" /> 空闲</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-yellow-400" /> 运行中</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-green-400" /> 完成</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-400" /> 错误</span>
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

  const sx = from.x + w / 2;
  const sy = from.y;
  const ex = to.x - w / 2;
  const ey = to.y;

  // Branch: 单根绿箭头从规划→框左缘(127,25)分叉，竖向下分别连检索/工具
  if (style === 'branch') {
    const bx = 127;
    if (toId === 'retriever') {
      const pts = [
        { x: sx, y: sy }, { x: bx, y: sy }, { x: bx, y: ey }, { x: ex, y: ey },
      ];
      return { d: roundPath(pts, R), marker, color, dashed: false, lx: bx - 6, ly: sy - 6 };
    }
    // tool分支：共享入口段，无独立箭头
    const pts = [
      { x: sx, y: sy }, { x: bx, y: sy }, { x: bx, y: ey }, { x: ex, y: ey },
    ];
    return { d: roundPath(pts, R), marker: '', color, dashed: false, lx: bx - 6, ly: sy - 6, hideLabel: true };
  }

  // Merge: 检索/工具同时右出至汇聚点(205)下至摘要
  if (style === 'merge') {
    const cx = 205;
    if (fromId === 'retriever') {
      const pts = [
        { x: sx, y: sy }, { x: cx, y: sy }, { x: cx, y: ey }, { x: ex, y: ey },
      ];
      return { d: roundPath(pts, R), marker, color, dashed: false, lx: cx, ly: sy - 6 };
    }
    const pts = [
      { x: sx, y: sy }, { x: cx, y: sy }, { x: cx, y: ey }, { x: ex, y: ey },
    ];
    return { d: roundPath(pts, R), marker, color, dashed: false, lx: cx, ly: sy - 10, hideLabel: true };
  }

  // Loop: validator → summarizer — 标准矩形闭环（竖边对齐汇聚节点 x=205）
  if (isLoop) {
    const sy2 = from.y + h / 2;
    const ey2 = to.y;
    const by = sy2 + 35;
    const leftX = 205;
    const pts = [
      { x: from.x, y: sy2 }, { x: from.x, y: by }, { x: leftX, y: by }, { x: leftX, y: ey2 }, { x: ex, y: ey2 },
    ];
    return { d: roundPath(pts, R), marker, color, dashed: true, lx: (from.x + leftX) / 2, ly: by + 10 };
  }

  // Default: orthogonal L-shape
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
        const rw = (retrieverPos.x + nodeW / 2 + 20) - rx;
        const rh = Math.max(retrieverPos.y, toolPos.y) + nodeH / 2 + 8 - ry;
        return (
          <g>
            <rect x={rx} y={ry} width={rw} height={rh} rx={10}
              fill="none" stroke="#10B981" strokeWidth={1.5}
              strokeDasharray="4,3" opacity={0.6} />
            <text x={rx + rw / 2} y={ry - 4} fill="#34D399" fontSize={9}
              textAnchor="middle" fontWeight={600}>并行执行</text>
          </g>
        );
      })()}
      {graph.edges.map((e, i) => {
        const from = nodePositions[e.from] || { x: 0, y: 0 };
        const to = nodePositions[e.to] || { x: 0, y: 0 };
        const ep = edgePath(from, to, e.from, e.to, nodeW, nodeH, e.style);
        const labelColor = e.style === 'branch' ? '#10B981' : (e.style === 'loop' ? '#FBBF24' : '#D1D5DB');
        return (
          <g key={i}>
            <path d={ep.d} fill="none" stroke={ep.color} strokeWidth={edgeW}
              strokeDasharray={ep.dashed ? '4,3' : 'none'}
              markerEnd={ep.marker || undefined} />
            {e.label && !ep.hideLabel && <text x={ep.lx} y={ep.ly} textAnchor="middle" fill={labelColor} fontSize={labelSize}>{e.label}</text>}
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
              fill="#1F2937"
              stroke={isHighlighted ? '#60A5FA' : color}
              strokeWidth={1.5}
              strokeOpacity={0.7} />
            <text x={pos.x + nodeW / 2} y={pos.y + fontSize / 3} textAnchor="middle" fill="#F3F4F6" fontSize={fontSize} fontWeight={500}>
              {n.label}
            </text>
          </g>
        );
      })}
    </g>
  );
}
