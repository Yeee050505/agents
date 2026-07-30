from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any
from app.utils.logger import logger

CHECKPOINT_DIR = Path(__file__).parent.parent.parent / "data" / "checkpoints"

_REQUIRED_FIELDS = {"question", "session_id", "request_id", "sub_queries", "retrieved",
                    "tool_results", "context_ctx", "draft", "human_review"}

PHASE_LABELS = {0: "入口", 1: "规划", 2: "检索+工具", 3: "摘要", 4: "校验", 5: "手动快照"}
NODE_BY_PHASE = {0: "planner", 1: "planner", 2: "retriever_tool", 3: "summarizer", 4: "validator", 5: "manual"}


def _ensure_dir():
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def _phase_path(session_id: str, phase: int) -> Path:
    return CHECKPOINT_DIR / f"{session_id}_phase{phase}.json"


def _manifest_path(session_id: str) -> Path:
    return CHECKPOINT_DIR / f"{session_id}_manifest.json"


def _load_manifest(session_id: str) -> dict:
    path = _manifest_path(session_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_manifest(session_id: str, manifest: dict):
    _ensure_dir()
    _manifest_path(session_id).write_text(
        json.dumps(manifest, ensure_ascii=False, default=str), encoding="utf-8"
    )


def save(state: dict, tags: list[str] | None = None, bind_node_id: str = "") -> str:
    _ensure_dir()
    phase = state.get("_phase", 0)
    session_id = state.get("session_id", "_unknown")
    path = _phase_path(session_id, phase)
    ts = time.time()
    payload = {
        "timestamp": ts,
        "_phase": phase,
        "state": {k: v for k, v in state.items() if not k.startswith("_") or k in ("_phase", "_paused")},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")

    # Update manifest
    manifest = _load_manifest(session_id)
    entry = manifest.get(str(phase), {})
    entry.update({
        "phase": phase,
        "timestamp": ts,
        "tags": tags or entry.get("tags", []),
        "bind_node_id": bind_node_id or entry.get("bind_node_id", ""),
        "status": "normal",
    })
    manifest[str(phase)] = entry
    _save_manifest(session_id, manifest)

    logger.debug(f"Checkpoint saved: {path.name} (phase {phase})")
    return str(path)


def load(session_id: str, phase: int | None = None) -> dict | None:
    if phase is not None:
        return _load_phase(session_id, phase)
    for p in range(max(PHASE_LABELS.keys()), -1, -1):
        result = _load_phase(session_id, p)
        if result:
            return result
    return None


def _load_phase(session_id: str, phase: int) -> dict | None:
    path = _phase_path(session_id, phase)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        state = payload.get("state", {})
        state["_phase"] = payload.get("_phase", phase)
        for field in _REQUIRED_FIELDS:
            state.setdefault(field, "" if field in ("question", "draft", "context_ctx") else [])
        logger.info(f"Checkpoint loaded: {path.name} (phase {phase})")
        return state
    except Exception as e:
        logger.warning(f"Checkpoint load failed: {path.name} - {e}")
        return None


def delete(session_id: str, phase: int | None = None, permanent: bool = False):
    """Delete checkpoint(s). If permanent=True, delete file + manifest entry."""
    if permanent:
        if phase is not None:
            p = _phase_path(session_id, phase)
            if p.exists():
                p.unlink()
            # Remove from manifest
            manifest = _load_manifest(session_id)
            manifest.pop(str(phase), None)
            _save_manifest(session_id, manifest)
            logger.debug(f"Checkpoint permanently deleted: {session_id} phase {phase}")
        else:
            for p in CHECKPOINT_DIR.glob(f"{session_id}_phase*.json"):
                p.unlink()
            m = _manifest_path(session_id)
            if m.exists():
                m.unlink()
            logger.debug(f"All checkpoints permanently deleted: {session_id}")
        return

    # Soft delete
    if phase is not None:
        manifest = _load_manifest(session_id)
        entry = manifest.get(str(phase))
        if entry:
            entry["status"] = "deleted"
            _save_manifest(session_id, manifest)
            logger.debug(f"Checkpoint soft-deleted: {session_id} phase {phase}")
        return
    # Soft delete all
    manifest = _load_manifest(session_id)
    for entry in manifest.values():
        entry["status"] = "deleted"
    _save_manifest(session_id, manifest)
    logger.debug(f"All checkpoints soft-deleted: {session_id}")


def restore(session_id: str, phase: int) -> bool:
    """Restore a soft-deleted checkpoint."""
    manifest = _load_manifest(session_id)
    entry = manifest.get(str(phase))
    if entry and entry.get("status") == "deleted":
        entry["status"] = "normal"
        _save_manifest(session_id, manifest)
        logger.debug(f"Checkpoint restored: {session_id} phase {phase}")
        return True
    return False


def update_metadata(session_id: str, phase: int, tags: list[str] | None = None,
                    bind_node_id: str | None = None) -> bool:
    """Update tags and/or bind_node_id for a snapshot."""
    manifest = _load_manifest(session_id)
    entry = manifest.get(str(phase))
    if not entry:
        return False
    if tags is not None:
        entry["tags"] = tags
    if bind_node_id is not None:
        entry["bind_node_id"] = bind_node_id
    _save_manifest(session_id, manifest)
    return True


def list_checkpoints() -> list[dict]:
    _ensure_dir()
    seen: dict[str, list[dict]] = {}
    for p in sorted(CHECKPOINT_DIR.glob("*_phase*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            sid = p.stem.rsplit("_phase", 1)[0]
            phase = payload.get("_phase", 0)
            manifest = _load_manifest(sid)
            meta = manifest.get(str(phase), {})
            entry = {
                "phase": phase,
                "node": NODE_BY_PHASE.get(phase, ""),
                "label": PHASE_LABELS.get(phase, f"阶段{phase}"),
                "timestamp": payload.get("timestamp", 0),
                "question": (payload.get("state", {}) or {}).get("question", "")[:60],
                "tags": meta.get("tags", []),
                "status": meta.get("status", "normal"),
                "bind_node_id": meta.get("bind_node_id", ""),
            }
            seen.setdefault(sid, []).append(entry)
        except Exception:
            continue
    return [{"session_id": sid, "snapshots": snaps} for sid, snaps in seen.items()]


def list_session_snapshots(session_id: str, include_deleted: bool = False) -> list[dict]:
    _ensure_dir()
    manifest = _load_manifest(session_id)
    results = []
    for p in sorted(CHECKPOINT_DIR.glob(f"{session_id}_phase*.json"), key=lambda f: f.stat().st_mtime):
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            phase = payload.get("_phase", 0)
            meta = manifest.get(str(phase), {})
            if meta.get("status") == "deleted" and not include_deleted:
                continue
            results.append({
                "snapshot_id": f"{session_id}_phase{phase}",
                "phase": phase,
                "node": NODE_BY_PHASE.get(phase, ""),
                "label": PHASE_LABELS.get(phase, f"阶段{phase}"),
                "timestamp": payload.get("timestamp", 0),
                "tags": meta.get("tags", []),
                "status": meta.get("status", "normal"),
                "bind_node_id": meta.get("bind_node_id", ""),
            })
        except Exception:
            continue
    return results


def list_recycle_bin() -> list[dict]:
    """List all soft-deleted snapshots across sessions."""
    _ensure_dir()
    items = []
    for mf in CHECKPOINT_DIR.glob("*_manifest.json"):
        try:
            session_id = mf.stem.rsplit("_manifest", 1)[0]
            manifest = json.loads(mf.read_text(encoding="utf-8"))
            for phase_str, meta in manifest.items():
                if meta.get("status") == "deleted":
                    phase = int(phase_str)
                    p = _phase_path(session_id, phase)
                    items.append({
                        "session_id": session_id,
                        "snapshot_id": f"{session_id}_phase{phase}",
                        "phase": phase,
                        "node": NODE_BY_PHASE.get(phase, ""),
                        "label": PHASE_LABELS.get(phase, f"阶段{phase}"),
                        "timestamp": meta.get("timestamp", 0),
                        "tags": meta.get("tags", []),
                        "status": "deleted",
                        "bind_node_id": meta.get("bind_node_id", ""),
                    })
        except Exception:
            continue
    return sorted(items, key=lambda x: x["timestamp"], reverse=True)


def cleanup(max_age: int = 86400):
    _ensure_dir()
    now = time.time()
    removed = 0
    for p in CHECKPOINT_DIR.glob("*.json"):
        if now - p.stat().st_mtime > max_age:
            p.unlink()
            removed += 1
    if removed:
        logger.info(f"Checkpoint cleanup: removed {removed} expired files")
