import importlib.util
from pathlib import Path

import pytest


def generator():
    spec = importlib.util.spec_from_file_location(
        "generate_clients", Path(__file__).parents[1] / "scripts/generate_clients.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_types_follow_schema_properties_and_references():
    schema = {"components": {"schemas": {
        "Root": {"type": "object", "required": ["child", "items"], "properties": {
            "child": {"$ref": "#/components/schemas/Child"},
            "items": {"type": "array", "items": {"type": "integer"}},
            "maybe": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "labels": {"type": "object", "additionalProperties": {"type": "string"}},
        }},
        "Child": {"type": "string", "enum": ["yes", "no"]},
    }}}
    output = generator().typescript_models(schema, ["Root"])
    assert '"child": Child;' in output
    assert '"items": Array<number>;' in output
    assert '"maybe"?: string | null;' in output
    assert 'Record<string, string>' in output
    assert 'export type Child = "yes" | "no";' in output
    schema["components"]["schemas"]["Root"]["properties"]["items"]["items"] = {"type": "boolean"}
    assert 'Array<boolean>' in generator().typescript_models(schema, ["Root"])


def test_unsupported_schema_fails_instead_of_wrong_type():
    with pytest.raises(ValueError):
        generator().typescript_models({"components": {"schemas": {
            "Root": {"allOf": [{"type": "string"}, {"type": "integer"}]},
        }}}, ["Root"])
