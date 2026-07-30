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

interface Props {
  sessionId?: string;
}

export default function GraphViewer({ sessionId }: Props) {
  const [graph, setGraph] = useState<WorkflowGraph | null>(null);
  const [nodeStatus, setNodeStatus] = useState<Record<string, NodeStatus>>({});
  const [snapshots, setSnapshots] = useState<SnapshotInfo[]>([]);
  const [highlightNode, setHighlightNode] = useState('');
  const statusRef = useRef(nodeStatus);

  useEffect(() => {
    getGraphWorkflow().then(r => {
      if (r.code === 200) setGraph(r.data);
    });
  }, []);

  // Fetch snapshots for dot indicators
  useEffect(() => {
    if (!sessionId) { setSnapshots([]); return; }
    fetch(`/api/v1/harness/checkpoints/${sessionId}?include_deleted=false`)
      .then(r => r.json())
      .then(r => { if (r.code === 200) setSnapshots(r.data.snapshots || []); })
      .catch(() => setSnapshots([]));
  }, [sessionId]);

  useEffect(() => { statusRef.current = nodeStatus; }, [nodeStatus]);

  // Listen for step events from chat
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

  // Listen for highlight events from CheckpointModal
  useEffect(() => {
    const handler = (e: CustomEvent) => {
      setHighlightNode(e.detail.nodeId || '');
    };
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

  if (!graph) {
    return <p className="text-gray-600 text-xs">加载流程图...</p>;
  }

  const nodePositions: Record<string, { x: number; y: number }> = {};
  const LAYER: Record<string, number> = {
    planner: 0, retriever_tool: 1, summarizer: 2, validator: 3,
  };
  const NODE_BY_PHASE: Record<number, string> = { 0: 'planner', 1: 'planner', 2: 'retriever_tool', 3: 'summarizer', 4: 'validator' };
  const PHASE_BY_NODE: Record<string, number> = { planner: 1, retriever_tool: 2, summarizer: 3, validator: 4 };

  graph.nodes.forEach(n => {
    const layer = LAYER[n.id] ?? 99;
    nodePositions[n.id] = { x: 50 + layer * 140, y: 50 + (n.id === 'retriever_tool' ? 70 : 0) };
  });
  nodePositions.__end__ = { x: 50 + 4 * 140, y: 50 };

  return (
    <svg viewBox="0 0 640 220" className="w-full h-auto max-h-56">
      {graph.edges.map((e, i) => {
        const from = nodePositions[e.from] || { x: 0, y: 0 };
        const to = nodePositions[e.to] || { x: 0, y: 0 };
        const isLoop = e.from === 'validator' && e.to === 'summarizer';
        const midX = (from.x + to.x) / 2;
        const midY = (from.y + to.y) / 2;
        return (
          <g key={i}>
            <line x1={from.x + 25} y1={from.y} x2={to.x - 25} y2={to.y}
              stroke={isLoop ? '#FBBF24' : '#6B7280'} strokeWidth={1.5}
              strokeDasharray={isLoop ? '4,3' : 'none'}
              markerEnd={isLoop ? 'url(#arrowYellow)' : 'url(#arrowGray)'} />
            {e.label && <text x={midX} y={midY - 8} textAnchor="middle" fill="#9CA3AF" fontSize={8}>{e.label}</text>}
          </g>
        );
      })}
      <defs>
        <marker id="arrowGray" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,0 L10,5 L0,10 Z" fill="#6B7280" />
        </marker>
        <marker id="arrowYellow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,0 L10,5 L0,10 Z" fill="#FBBF24" />
        </marker>
      </defs>

      {graph.nodes.map(n => {
        const pos = nodePositions[n.id] || { x: 0, y: 0 };
        const status = nodeStatus[n.id] || 'idle';
        const color = NODE_COLORS[status];
        const cp = hasSnapshot(n.id);
        const isHighlighted = highlightNode === n.id;

        return (
          <g key={n.id}>
            {/* Checkpoint dot - clickable */}
            {cp && (
              <circle cx={pos.x + 50} cy={pos.y - 12} r={6}
                fill="#3B82F6" stroke="#60A5FA" strokeWidth={1.5}
                className="cursor-pointer hover:fill-blue-400 transition-colors"
                onClick={() => {
                  const phase = PHASE_BY_NODE[n.id];
                  if (phase) handleDotClick(phase);
                }}>
                <title>有检查点 - 点击打开管理面板</title>
              </circle>
            )}
            <rect x={pos.x} y={pos.y - 12} width={50} height={24} rx={6}
              fill={color + '30'} stroke={isHighlighted ? '#60A5FA' : color}
              strokeWidth={isHighlighted ? 2.5 : (status === 'running' ? 2 : 1)} />
            <text x={pos.x + 25} y={pos.y + 4} textAnchor="middle" fill="#E5E7EB" fontSize={9} fontWeight={500}>
              {n.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
