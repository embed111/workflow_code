from __future__ import annotations

import json
from pathlib import Path


def load_index_page_html() -> str:
    path = Path(__file__).resolve().parent / "templates" / "index.html"
    return path.read_text(encoding="utf-8")


def load_index_page_css() -> str:
    templates_dir = Path(__file__).resolve().parent / "templates"
    manifest_path = templates_dir / "index_css_manifest.json"
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(payload, list) and payload:
            chunks: list[str] = []
            for raw in payload:
                name = str(raw or "").strip()
                if not name:
                    continue
                part_path = templates_dir / name
                if not part_path.exists() or not part_path.is_file():
                    raise FileNotFoundError(f"css part missing: {part_path}")
                chunks.append(part_path.read_text(encoding="utf-8"))
            if chunks:
                return "\n".join(chunks)
    path = templates_dir / "index.css"
    return path.read_text(encoding="utf-8")


HTML_PAGE = load_index_page_html()
CSS_PAGE = load_index_page_css()
