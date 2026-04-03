from __future__ import annotations

def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    if not isinstance(symbols, dict):
        return
    target = globals()
    module_name = str(target.get('__name__') or '')
    for key, value in symbols.items():
        if str(key).startswith('__'):
            continue
        current = target.get(key)
        if callable(current) and getattr(current, '__module__', '') == module_name:
            continue
        target[key] = value

def discover_training_trainers(*, query: str = "", limit: int = 50) -> list[dict[str, str]]:
    source_root = TRAINER_SOURCE_ROOT
    if not source_root.exists() or not source_root.is_dir():
        return []

    query_text = str(query or "").strip().lower()
    candidates: dict[str, dict[str, str]] = {}

    def add_candidate(name: str, rel_path: str, source: str) -> None:
        clean_name = str(name or "").strip()
        clean_path = str(rel_path or "").strip()
        if not clean_name:
            return
        key = clean_name.lower()
        if key in candidates:
            return
        candidates[key] = {
            "trainer_name": clean_name,
            "path": clean_path,
            "source": source,
        }

    for agents_file in source_root.rglob("AGENTS.md"):
        try:
            if not agents_file.is_file():
                continue
            parent = agents_file.parent.resolve(strict=False)
            rel = relative_to_root(source_root, parent)
            add_candidate(parent.name, rel, "agents_md")
        except Exception:
            continue

    roles_root = source_root / ".training" / "trainer" / "roles"
    if roles_root.exists() and roles_root.is_dir():
        for entry in sorted(roles_root.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_dir():
                continue
            rel = relative_to_root(source_root, entry.resolve(strict=False))
            add_candidate(entry.name, rel, "role_dir")

    for entry in sorted(source_root.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith("."):
            continue
        rel = relative_to_root(source_root, entry.resolve(strict=False))
        add_candidate(entry.stem if entry.is_file() else entry.name, rel, "root_entry")

    rows = list(candidates.values())
    if query_text:
        rows = [
            row
            for row in rows
            if query_text in str(row.get("trainer_name") or "").lower()
            or query_text in str(row.get("path") or "").lower()
        ]
    rows.sort(
        key=lambda row: (
            0
            if str(row.get("trainer_name") or "").lower().startswith(query_text or " ")
            else 1,
            str(row.get("trainer_name") or "").lower(),
        )
    )
    return rows[: max(1, int(limit))]


