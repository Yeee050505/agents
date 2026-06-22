import json
import os
from pathlib import Path

ADAPTERS_DIR = Path(__file__).parent.parent.parent / "lora_adapters"


class AdapterManager:
    def __init__(self):
        ADAPTERS_DIR.mkdir(parents=True, exist_ok=True)
        self._loaded: dict[str, str] = {}  # name -> path

    def list_adapters(self) -> list[dict]:
        adapters = []
        for d in ADAPTERS_DIR.iterdir():
            if d.is_dir() and (d / "adapter_config.json").exists():
                config = {}
                meta_path = d / "train_meta.json"
                if meta_path.exists():
                    config = json.loads(meta_path.read_text(encoding="utf-8"))
                adapters.append({
                    "name": d.name,
                    "path": str(d),
                    "base_model": config.get("base_model_name_or_path", ""),
                    "r": config.get("r", 0),
                    "steps": config.get("steps", 0),
                })
        return sorted(adapters, key=lambda x: x["name"])

    def get_adapter_path(self, name: str) -> str | None:
        path = ADAPTERS_DIR / name
        if path.exists() and (path / "adapter_config.json").exists():
            return str(path)
        return None


adapter_manager = AdapterManager()
