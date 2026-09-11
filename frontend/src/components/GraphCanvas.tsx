import { useRef, useEffect, useCallback } from "react";
import type { GraphNode, GraphEdge } from "../types";

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  highlightPath: string[] | null;
  onSelect: (id: string) => void;
}

export function GraphCanvas({ nodes, edges, selectedId, highlightPath, onSelect }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef({ scale: 1, ox: 0, oy: 0, dragging: false, lx: 0, ly: 0 });

  const getNode = useCallback((id: string) => nodes.find(n => n.id === id), [nodes]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const { scale, ox, oy } = stateRef.current;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.translate(ox, oy);
    ctx.scale(scale, scale);

    // Draw edges
    edges.forEach(edge => {
      const from = getNode(edge.from);
      const to = getNode(edge.to);
      if (!from || !to) return;

      const dx = to.x - from.x, dy = to.y - from.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const ux = dx / dist, uy = dy / dist;
      const x1 = from.x + ux * from.r, y1 = from.y + uy * from.r;
      const x2 = to.x - ux * to.r, y2 = to.y - uy * to.r;

      const highlighted = highlightPath?.includes(edge.from) && highlightPath?.includes(edge.to);

      ctx.save();
      ctx.strokeStyle = highlighted ? "#58a6ff" : (edge.dashed ? "#484f58" : "#30363d");
      ctx.lineWidth = highlighted ? 2.5 : 1.2;
      ctx.setLineDash(edge.dashed ? [4, 4] : []);
      ctx.beginPath();
      if (edge.label && from.id === "router") {
        const mx = (x1 + x2) / 2, my = (y1 + y2) / 2 - 8;
        ctx.moveTo(x1, y1);
        ctx.quadraticCurveTo(mx, my, x2, y2);
      } else {
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      // Arrow
      const angle = Math.atan2(y2 - y1, x2 - x1);
      ctx.fillStyle = highlighted ? "#58a6ff" : (edge.dashed ? "#484f58" : "#30363d");
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(x2 - 7 * Math.cos(angle - 0.35), y2 - 7 * Math.sin(angle - 0.35));
      ctx.lineTo(x2 - 7 * Math.cos(angle + 0.35), y2 - 7 * Math.sin(angle + 0.35));
      ctx.closePath();
      ctx.fill();

      if (edge.label) {
        ctx.fillStyle = highlighted ? "#58a6ff" : "#6e7681";
        ctx.font = "10px -apple-system, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(edge.label, (x1 + x2) / 2, (y1 + y2) / 2 - 4);
      }
      ctx.restore();
    });

    // Draw nodes
    nodes.forEach(node => {
      const highlighted = highlightPath?.includes(node.id);
      const selected = selectedId === node.id;

      ctx.save();
      if (highlighted) { ctx.shadowColor = node.color; ctx.shadowBlur = 16; }

      ctx.fillStyle = node.color + (highlighted || selected ? "" : "66");
      ctx.strokeStyle = node.color;
      ctx.lineWidth = selected ? 2.5 : 1.5;
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.shadowBlur = 0;

      ctx.fillStyle = "#fff";
      ctx.font = "bold 10px -apple-system, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const lines = node.label.split("\n");
      lines.forEach((line, i) => {
        ctx.fillText(line, node.x, node.y - (lines.length - 1) * 5 + i * 11);
      });
      ctx.restore();
    });

    ctx.restore();
  }, [nodes, edges, selectedId, highlightPath, getNode]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const resize = () => {
      const parent = canvas.parentElement;
      if (parent) {
        canvas.width = parent.clientWidth;
        canvas.height = Math.max(parent.clientHeight, 600);
        draw();
      }
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [draw]);

  useEffect(() => { draw(); }, [draw]);

  const getNodeAt = (mx: number, my: number) => {
    const { scale, ox, oy } = stateRef.current;
    const x = (mx - ox) / scale, y = (my - oy) / scale;
    for (const n of nodes) {
      const dx = x - n.x, dy = y - n.y;
      if (dx * dx + dy * dy <= n.r * n.r) return n.id;
    }
    return null;
  };

  return (
    <canvas
      ref={canvasRef}
      onMouseDown={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        const id = getNodeAt(e.clientX - rect.left, e.clientY - rect.top);
        if (id) { onSelect(id); draw(); }
        else { stateRef.current.dragging = true; stateRef.current.lx = e.clientX; stateRef.current.ly = e.clientY; }
      }}
      onMouseMove={(e) => {
        const s = stateRef.current;
        if (s.dragging) {
          s.ox += e.clientX - s.lx;
          s.oy += e.clientY - s.ly;
          s.lx = e.clientX; s.ly = e.clientY;
          draw();
        }
      }}
      onMouseUp={() => { stateRef.current.dragging = false; }}
      onWheel={(e) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        stateRef.current.scale = Math.max(0.3, Math.min(3, stateRef.current.scale * delta));
        draw();
      }}
    />
  );
}
