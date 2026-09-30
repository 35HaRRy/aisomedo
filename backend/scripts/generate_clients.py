"""Generate TypeScript and Kotlin clients from backend/openapi.json (#24).

Run: ``uv run --project backend python backend/scripts/generate_clients.py``

Stdlib only, byte-deterministic output. CI regenerates and fails on drift.
Covers the compatibility contract all clients must honor; endpoint coverage
grows with the schema without changing this script's shape.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
WEB_TARGET = REPO / "web" / "src" / "api" / "openapi.ts"
ANDROID_TARGET = (
    REPO / "android" / "app" / "src" / "main" / "java"
    / "com" / "dojo" / "aisomedo" / "api" / "GeneratedApi.kt"
)


def main() -> None:
    schema = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    version = schema["info"]["version"]
    paths = sorted(schema.get("paths", {}))

    ts_lines = [
        "// GENERATED from backend/openapi.json — do not edit by hand.",
        "// Regenerate: uv run --project backend python backend/scripts/generate_clients.py",
        f'export const CONTRACT_VERSION = "{version}";',
        "",
        "export interface CompatInfo {",
        "  api_version: string;",
        "  android_min_version_code: number;",
        "  android_current_version_code: number;",
        "  update_url: string;",
        "}",
        "",
        "export const ANDROID_VERSION_HEADER = \"X-Android-Version-Code\";",
        "",
        "export async function fetchCompat(baseUrl: string): Promise<CompatInfo> {",
        "  const response = await fetch(`${baseUrl}/api/compat`);",
        "  if (!response.ok) {",
        "    throw new Error(`compat check failed: ${response.status}`);",
        "  }",
        "  return (await response.json()) as CompatInfo;",
        "}",
        "",
        "export const API_PATHS: readonly string[] = [",
        *[f'  "{p}",' for p in paths],
        "];",
        "",
    ]
    WEB_TARGET.parent.mkdir(parents=True, exist_ok=True)
    WEB_TARGET.write_text("\n".join(ts_lines), encoding="utf-8")

    kt_lines = [
        "// GENERATED from backend/openapi.json — do not edit by hand.",
        "// Regenerate: uv run --project backend python backend/scripts/generate_clients.py",
        "package com.dojo.aisomedo.api",
        "",
        "object ApiContract {",
        f'    const val CONTRACT_VERSION = "{version}"',
        '    const val VERSION_HEADER = "X-Android-Version-Code"',
        "}",
        "",
        "data class CompatInfo(",
        "    val apiVersion: String,",
        "    val androidMinVersionCode: Int,",
        "    val androidCurrentVersionCode: Int,",
        "    val updateUrl: String,",
        ")",
        "",
        "object UpdatePolicy {",
        "    fun isOutdated(installedVersionCode: Int, minVersionCode: Int): Boolean =",
        "        installedVersionCode < minVersionCode",
        "}",
        "",
    ]
    ANDROID_TARGET.parent.mkdir(parents=True, exist_ok=True)
    ANDROID_TARGET.write_text("\n".join(kt_lines), encoding="utf-8")
    print(f"wrote {WEB_TARGET} and {ANDROID_TARGET} (contract {version})")


if __name__ == "__main__":
    main()
