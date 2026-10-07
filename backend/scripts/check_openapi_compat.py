"""Conservative compatibility gate for this project's OpenAPI 3.1 schemas.

Requests must accept previous inputs; responses must fit previous client types.
Unknown schema constraints fail closed. This is not a general JSON Schema solver.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
ANNOTATIONS = {"title", "description", "default", "example", "examples", "deprecated", "$id"}
KEYWORDS = {"$ref", "type", "properties", "required", "additionalProperties", "items",
            "anyOf", "enum", "const", "minimum", "maximum", "exclusiveMinimum",
            "exclusiveMaximum", "minLength", "maxLength", "minItems", "maxItems",
            "minProperties", "maxProperties", "pattern", "format", "multipleOf", "uniqueItems",
            "readOnly", "writeOnly", "discriminator"} | ANNOTATIONS


def resolve(node: dict, doc: dict) -> dict:
    seen = set()
    while "$ref" in node:
        ref = node["$ref"]
        if ref in seen or not ref.startswith("#/"):
            raise ValueError(f"unsupported or circular reference: {ref}")
        seen.add(ref)
        siblings = {k: v for k, v in node.items() if k != "$ref" and k not in ANNOTATIONS}
        if siblings:
            raise ValueError("constrained $ref siblings need explicit compatibility review")
        node = doc
        for part in ref[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def subset(a: dict | bool, b: dict | bool, adoc: dict, bdoc: dict,
           path: str, seen: frozenset = frozenset()) -> list[str]:
    """Return reasons why values allowed by a may not fit b."""
    if b is True or a is False:
        return []
    if b is False or a is True:
        return [] if a == b else [f"{path}: additional values no longer fit"]
    try:
        a, b = resolve(a, adoc), resolve(b, bdoc)
    except (ValueError, KeyError, TypeError) as exc:
        return [f"{path}: invalid reference ({exc})"]
    pair = (id(a), id(b))
    if pair in seen:
        return []
    seen = seen | {pair}
    unknown = (set(a) | set(b)) - KEYWORDS
    if unknown:
        return [f"{path}: unsupported schema constraints: {sorted(unknown)}"]
    errors = []
    if "anyOf" in a or "anyOf" in b:
        if any("anyOf" in node and set(node) - {"anyOf"} - ANNOTATIONS for node in (a, b)):
            return [f"{path}: constrained union needs explicit compatibility review"]
        # ponytail: conservative branch matching; use a schema solver if unions
        # need proofs based on several branches jointly covering one branch.
        for branch in a.get("anyOf", [a]):
            if all(subset(branch, target, adoc, bdoc, path, seen - {pair})
                   for target in b.get("anyOf", [b])):
                errors.append(f"{path}: union contains incompatible values")
        return errors
    if b.get("type") is not None and a.get("type") != b["type"]:
        errors.append(f"{path}: type changed")
    for key in ("format", "pattern", "multipleOf", "readOnly", "writeOnly", "discriminator"):
        if b.get(key) is not None and a.get(key) != b[key]:
            errors.append(f"{path}: {key} changed")
    def allowed_values(node):
        if "const" in node:
            return [node["const"]] if node["const"] in node.get("enum", [node["const"]]) else []
        return node.get("enum")
    av, bv = allowed_values(a), allowed_values(b)
    if bv is not None and (av is None or any(value not in bv for value in av)):
        errors.append(f"{path}: accepted values changed")
    for key in ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"):
        if key in b and (key not in a or a[key] < b[key]):
            errors.append(f"{path}: {key} tightened")
    for key in ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties"):
        if key in b and (key not in a or a[key] > b[key]):
            errors.append(f"{path}: {key} tightened")
    if b.get("uniqueItems") and not a.get("uniqueItems"):
        errors.append(f"{path}: uniqueItems tightened")
    if set(b.get("required", [])) - set(a.get("required", [])):
        errors.append(f"{path}: required fields changed")
    ap, bp = a.get("properties", {}), b.get("properties", {})
    for name in ap.keys() | bp.keys():
        # New optional named fields are additive for generated clients, which
        # send documented fields rather than arbitrary unknown properties.
        if name not in ap and a.get("additionalProperties", True) is True and (
            name not in b.get("required", [])
        ):
            continue
        errors += subset(ap.get(name, a.get("additionalProperties", True)),
                         bp.get(name, b.get("additionalProperties", True)),
                         adoc, bdoc, f"{path}/properties/{name}", seen)
    errors += subset(a.get("additionalProperties", True), b.get("additionalProperties", True),
                     adoc, bdoc, f"{path}/additionalProperties", seen)
    if "items" in b:
        errors += subset(a.get("items", True), b["items"], adoc, bdoc, path + "/items", seen)
    return errors


def schema_changes(old: dict, new: dict, previous: dict, current: dict,
                   path: str, *, response: bool) -> list[str]:
    errors = subset(new, old, current, previous, path) if response else subset(
        old, new, previous, current, path,
    )
    # Removal of a documented field is forbidden even when it was optional.
    def removed(a, b, location, visited):
        try:
            a, b = resolve(a, previous), resolve(b, current)
        except (ValueError, KeyError, TypeError):
            return
        pair = (id(a), id(b))
        if pair in visited:
            return
        visited = visited | {pair}
        if "anyOf" in a or "anyOf" in b:
            try:
                for branch in a.get("anyOf", [a]):
                    branch = resolve(branch, previous)
                    if not {"properties", "items", "anyOf"} & branch.keys():
                        continue  # Scalar branch narrowing removes no documented fields.
                    matches = [resolve(target, current) for target in b.get("anyOf", [b])]
                    matches = [target for target in matches
                               if target.get("type") == branch.get("type")]
                    exact = [target for target in matches if target == branch]
                    if len(exact) == 1:
                        matches = exact
                    if len(matches) != 1:
                        errors.append(f"{location}: response union branch removed or ambiguous")
                    else:
                        removed(branch, matches[0], location + "/anyOf", visited)
            except (ValueError, KeyError, TypeError):
                errors.append(f"{location}: invalid response union reference")
            return
        ap, bp = a.get("properties", {}), b.get("properties", {})
        for key in ap.keys() - bp.keys():
            errors.append(f"{location}/properties/{key}: documented field removed")
        for key in ap.keys() & bp.keys():
            removed(ap[key], bp[key], f"{location}/properties/{key}", visited)
        if "items" in a and "items" in b:
            removed(a["items"], b["items"], location + "/items", visited)
    if response:
        removed(old, new, path, frozenset())
    return errors


def breaking_changes(previous: dict, current: dict) -> list[str]:
    errors = []
    if not all(isinstance(doc.get("paths"), dict) and doc.get("openapi", "").startswith("3.")
               for doc in (previous, current)):
        return ["invalid OpenAPI document"]

    def contents(old, new, path, response=False):
        result = []
        for media, value in old.get("content", {}).items():
            if media not in new.get("content", {}):
                result.append(f"{path}: {media} removed")
            else:
                result += schema_changes(value.get("schema", {}),
                                         new["content"][media].get("schema", {}),
                                         previous, current, f"{path}/{media}", response=response)
        if response:
            for media in new.get("content", {}).keys() - old.get("content", {}).keys():
                result.append(f"{path}: response media type {media} added")
        return result

    for path, item in previous["paths"].items():
        new_item = current["paths"].get(path, {})
        for method in METHODS & item.keys():
            location = f"{method.upper()} {path}"
            if method not in new_item:
                errors.append(f"{location}: operation removed")
                continue
            old, new = item[method], new_item[method]
            if new.get("security", current.get("security", [])) != old.get(
                "security", previous.get("security", []),
            ):
                errors.append(f"{location}: security requirements changed")
            for requirement in old.get("security", previous.get("security", [])):
                for scheme in requirement:
                    try:
                        definitions = [resolve(doc["components"]["securitySchemes"][scheme], doc)
                                       for doc in (previous, current)]
                        definitions = [{k: v for k, v in d.items() if k not in ANNOTATIONS}
                                       for d in definitions]
                        if definitions[0] != definitions[1]:
                            errors.append(f"{location}: security scheme {scheme} changed")
                    except (ValueError, KeyError, TypeError):
                        errors.append(f"{location}: missing/invalid security scheme {scheme}")
            def parameters(path_item, op, doc):
                entries = [resolve(p, doc) for p in
                           path_item.get("parameters", []) + op.get("parameters", [])]
                return {(p["in"], p["name"]): p for p in entries}
            try:
                op, np = parameters(item, old, previous), parameters(new_item, new, current)
                for key in op.keys() | np.keys():
                    if key not in np:
                        errors.append(f"{location}: parameter {key} removed")
                    elif key not in op:
                        if np[key].get("required"):
                            errors.append(f"{location}: required parameter {key} added")
                    else:
                        if np[key].get("required") and not op[key].get("required"):
                            errors.append(f"{location}: parameter {key} now required")
                        errors += schema_changes(op[key].get("schema", {}),
                                                 np[key].get("schema", {}), previous, current,
                                                 f"{location}/parameters/{key}", response=False)
                        for option in ("style", "explode", "allowReserved"):
                            if op[key].get(option) != np[key].get(option):
                                errors.append(f"{location}: parameter serialization changed")
                ob = resolve(old.get("requestBody", {}), previous)
                nb = resolve(new.get("requestBody", {}), current)
                if nb.get("required") and not ob.get("required"):
                    errors.append(f"{location}: request body now required")
                errors += contents(ob, nb, location + "/requestBody")
                for status, value in old.get("responses", {}).items():
                    if status not in new.get("responses", {}):
                        errors.append(f"{location}: response {status} removed")
                    else:
                        errors += contents(resolve(value, previous),
                                           resolve(new["responses"][status], current),
                                           f"{location}/responses/{status}", True)
            except (ValueError, KeyError, TypeError) as exc:
                errors.append(f"{location}: invalid contract ({exc})")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous", type=Path)
    parser.add_argument("current", type=Path)
    args = parser.parse_args()
    try:
        errors = breaking_changes(json.loads(args.previous.read_text(encoding="utf-8")),
                                  json.loads(args.current.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        print(f"Invalid contract input: {exc}")
        return 2
    for error in errors:
        print(error)
    print(f"OpenAPI compatibility: {len(errors)} breaking/unproven changes")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
