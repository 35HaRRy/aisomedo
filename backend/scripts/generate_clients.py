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


def typescript_models(schema: dict, roots: list[str]) -> str:
    """Emit the browser DTO closure from OpenAPI, rejecting unsupported shapes."""
    components = schema["components"]["schemas"]
    pending = set(roots)
    emitted: dict[str, str] = {}

    def convert(node: dict) -> str:
        if "$ref" in node:
            prefix = "#/components/schemas/"
            ref = node["$ref"]
            if not ref.startswith(prefix):
                raise ValueError(f"Unsupported reference: {ref}")
            name = ref[len(prefix):]
            pending.add(name)
            return name
        if "allOf" in node or "not" in node:
            raise ValueError(f"Unsupported schema: {node}")
        if "enum" in node:
            return " | ".join(json.dumps(value, ensure_ascii=False) for value in node["enum"])
        if "const" in node:
            return json.dumps(node["const"], ensure_ascii=False)
        for union in ("anyOf", "oneOf"):
            if union in node:
                return " | ".join(convert(part) for part in node[union])
        kind = node.get("type")
        scalars = {"string": "string", "integer": "number", "number": "number",
                   "boolean": "boolean", "null": "null"}
        if kind in scalars:
            return scalars[kind]
        if kind == "array":
            return f"Array<{convert(node['items'])}>"
        if kind == "object":
            if "properties" in node:
                required = node.get("required", [])
                lines = ["{"]
                for name, value in sorted(node["properties"].items()):
                    optional = "" if name in required else "?"
                    lines.append(f"  {json.dumps(name)}{optional}: {convert(value)};")
                lines.append("}")
                return "\n".join(lines)
            extra = node.get("additionalProperties", True)
            value = convert(extra) if isinstance(extra, dict) else "unknown" if extra else "never"
            return f"Record<string, {value}>"
        if not node or set(node).issubset({"title", "description"}):
            return "unknown"
        raise ValueError(f"Unsupported schema: {node}")

    while pending - emitted.keys():
        name = min(pending - emitted.keys())
        emitted[name] = f"export type {name} = {convert(components[name])};"
    return "\n\n".join(emitted[name] for name in sorted(emitted)) + "\n"


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
    ts_lines.append(typescript_models(schema, [
        "DashboardOut", "ClientOut", "ValidateIn", "ActivityPageOut",
        "SetupOut", "ConsentOut", "AcceptanceIn", "AcceptanceOut",
        "BrandingDefaultsOut", "BrandingPatchIn", "BrandingAssetOut",
        "PlanIn", "PlanOut", "StatusOut", "StartIn", "StartOut", "AttemptOut", "SelectIn",
        "UploadLimitsOut", "UploadInitIn", "UploadOut", "ResolveConflictIn",
        "ActiveEditorOut", "CompletedPackageOut", "SelectionIn", "MontageOut",
    ]))
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
