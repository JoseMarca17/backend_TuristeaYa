"""Genera ``app/core/schema_map.py`` desde ``db.json``.

Mantiene el backend sincronizado con la base de datos real: tras cualquier
cambio de esquema en Supabase, regenera el dump ``db.json`` y ejecuta::

    python3 tools/generate_schema_map.py

El módulo generado contiene, por cada tabla del esquema ``public``:

- ``TABLE_COLUMNS``       columnas válidas (validación de payloads POST/PATCH)
- ``FOREIGN_KEY_COLUMNS`` columnas FK existentes (filtros permitidos en GET)
- ``READONLY_COLUMNS``    columnas gestionadas por el servidor (id, created_at)
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUMP = ROOT / "db.json"
TARGET = ROOT / "app" / "core" / "schema_map.py"


def _dedupe_fk_columns(info: dict) -> list[str]:
    """Nombres de columna FK únicos (la metadata puede repetir la misma FK)."""
    seen: list[str] = []
    for fk in info.get("foreign_keys") or []:
        col = fk["column"]
        if col not in seen:
            seen.append(col)
    return seen


def main() -> None:
    raw = json.loads(DUMP.read_text(encoding="utf-8"))
    meta = json.loads(raw[0]["full_db_metadata"])
    tables = meta["tables_summary"]

    lines: list[str] = [
        '"""Mapeo generado desde db.json — NO editar a mano.',
        "",
        "Regenerar con: python3 tools/generate_schema_map.py",
        "",
        f'Contiene las {len(tables)} tablas del esquema "public" de PostgreSQL/Supabase.',
        '"""',
        "",
        "# Columnas válidas por tabla (validación de payloads de POST/PATCH).",
        "TABLE_COLUMNS: dict[str, tuple[str, ...]] = {",
    ]
    for table in sorted(tables):
        cols = ", ".join(f'"{c["name"]}"' for c in tables[table]["columns"])
        lines.append(f'    "{table}": ({cols}),')
    lines += [
        "}",
        "",
        "# Columnas FK por tabla (filtros permitidos en listas GET).",
        "FOREIGN_KEY_COLUMNS: dict[str, tuple[str, ...]] = {",
    ]
    for table in sorted(tables):
        fk_cols = _dedupe_fk_columns(tables[table])
        if fk_cols:
            literal = ", ".join(f'"{c}"' for c in fk_cols)
            if len(fk_cols) == 1:
                literal += ","  # tupla de un elemento necesita coma final
            lines.append(f'    "{table}": ({literal}),')
    lines += [
        "}",
        "",
        "# Columnas gestionadas por la base de datos: nunca llegan en payloads.",
        "READONLY_COLUMNS: frozenset[str] = frozenset((",
        '    "id",',
        '    "created_at",',
        "))",
        "",
        f"TABLE_COUNT: int = {len(tables)}",
        "",
    ]

    TARGET.write_text("\n".join(lines), encoding="utf-8")
    print(f"escrito: {TARGET} ({len(tables)} tablas)")


if __name__ == "__main__":
    main()
