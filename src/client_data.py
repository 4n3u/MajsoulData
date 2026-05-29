from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path, PurePosixPath
from typing import Any


RAW_ASSET_SUBDIR = Path("assets")
CLIENT_SUBDIR = "client"


def is_repository_support_lua_asset_path(asset_path: str) -> bool:
    if not asset_path.endswith(".lua.bytes"):
        return False
    if asset_path in {
        "LuaByte/Lua/Net/ProtoDeclare.lua.bytes",
        "LuaByte/Lua/Net/ExcelDeclare.lua.bytes",
    }:
        return True
    if asset_path.startswith("LuaByte/Lua/Game/UIData/"):
        return True
    return asset_path.startswith("LuaByte/Lua/Game/") and "/Data/" in asset_path


def is_client_data_asset_path(asset_path: str) -> bool:
    if asset_path == "MyAssets/docs/proto_config.bytes":
        return True
    if asset_path.startswith("MyAssets/docs_version/") and asset_path.endswith(".json"):
        return True
    if asset_path.startswith("MyAssets/docs/"):
        if asset_path.endswith(".json"):
            return True
        if asset_path.startswith("MyAssets/docs/spots/") and asset_path.endswith(".bytes"):
            return True
    if asset_path.startswith("MyAssets/deco/illust_data/") and asset_path.endswith(".json"):
        return True
    if asset_path.startswith("MyAssets/deco/character/") and asset_path.endswith(".json"):
        return True
    if asset_path.startswith("MyAssets/spine/") and asset_path.endswith("/_info_output.csv"):
        return True
    name = PurePosixPath(asset_path).name
    return (
        asset_path.startswith("MyAssets/ui/")
        and name.startswith("atlas_")
        and name.endswith("_config.json")
    )


def parse_spot_script(source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        number, text = line.split(":", 1)
        if not number.isdigit():
            continue
        rows.append({"line": int(number), "text": text})
    return rows


def build_client_data_outputs(output_dir: Path, raw_dir: Path) -> dict[str, int]:
    raw_root = raw_dir / RAW_ASSET_SUBDIR / "MyAssets"
    client_dir = output_dir / CLIENT_SUBDIR
    if client_dir.exists():
        shutil.rmtree(client_dir)
    client_dir.mkdir(parents=True, exist_ok=True)

    counts = {
        "docs_json": 0,
        "docs_version_json": 0,
        "spot_scripts": 0,
        "deco_illust_json": 0,
        "deco_character_json": 0,
        "spine_info_csv": 0,
        "ui_atlas_json": 0,
    }

    if not raw_root.exists():
        return counts

    docs_root = raw_root / "docs"
    docs_version_root = raw_root / "docs_version"
    deco_illust_root = raw_root / "deco" / "illust_data"
    deco_character_root = raw_root / "deco" / "character"
    spine_root = raw_root / "spine"
    ui_root = raw_root / "ui"

    for source_path in sorted(docs_root.rglob("*.json")) if docs_root.exists() else []:
        _copy_json(source_path, client_dir / "docs" / source_path.relative_to(docs_root))
        counts["docs_json"] += 1

    for source_path in (
        sorted(docs_version_root.rglob("*.json")) if docs_version_root.exists() else []
    ):
        _copy_json(
            source_path,
            client_dir / "docs_version" / source_path.relative_to(docs_version_root),
        )
        counts["docs_version_json"] += 1

    spots_root = docs_root / "spots"
    for source_path in sorted(spots_root.rglob("*.bytes")) if spots_root.exists() else []:
        target = (
            client_dir
            / "spot_scripts"
            / source_path.relative_to(spots_root).with_suffix(".json")
        )
        _write_json(
            target,
            parse_spot_script(source_path.read_text(encoding="utf-8", errors="replace")),
        )
        counts["spot_scripts"] += 1

    for source_path in sorted(deco_illust_root.glob("*.json")) if deco_illust_root.exists() else []:
        _copy_json(
            source_path,
            client_dir / "deco" / "illust_data" / source_path.relative_to(deco_illust_root),
        )
        counts["deco_illust_json"] += 1

    for source_path in (
        sorted(deco_character_root.rglob("*.json")) if deco_character_root.exists() else []
    ):
        _copy_json(
            source_path,
            client_dir / "deco" / "character" / source_path.relative_to(deco_character_root),
        )
        counts["deco_character_json"] += 1

    for source_path in (
        sorted(spine_root.rglob("_info_output.csv")) if spine_root.exists() else []
    ):
        target = (
            client_dir
            / "spine"
            / "info"
            / source_path.relative_to(spine_root).with_suffix(".json")
        )
        _write_json(target, _read_csv_rows(source_path))
        counts["spine_info_csv"] += 1

    for source_path in sorted(ui_root.rglob("atlas_*_config.json")) if ui_root.exists() else []:
        _copy_json(
            source_path,
            client_dir / "ui" / "atlas" / source_path.relative_to(ui_root),
        )
        counts["ui_atlas_json"] += 1

    return counts


def _copy_json(source_path: Path, target_path: Path) -> None:
    _write_json(
        target_path,
        json.loads(source_path.read_text(encoding="utf-8", errors="replace")),
    )


def _read_csv_rows(source_path: Path) -> list[dict[str, str]]:
    with source_path.open("r", encoding="utf-8-sig", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
