"""Contract regressions: narrowing requests or widening responses breaks clients."""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/check_openapi_compat.py"


def compare(old, new):
    assert SCRIPT.is_file(), "OpenAPI compatibility gate is missing"
    spec = importlib.util.spec_from_file_location("compat_gate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.breaking_changes(old, new)


def contract(schema=None, *, response=False):
    schema = schema or {"type": "object", "properties": {"name": {"type": "string"}}}
    operation = {"responses": {"200": {"description": "ok", "content": {
        "application/json": {"schema": schema if response else {"type": "string"}},
    }}}}
    if not response:
        operation["requestBody"] = {"content": {"application/json": {"schema": schema}}}
    return {"openapi": "3.1.0", "paths": {"/item": {"post": operation}},
            "components": {"schemas": {}}}


def test_additive_operations_optional_fields_and_docs_pass():
    old = contract()
    new = copy.deepcopy(old)
    new["paths"]["/new"] = {"get": {"responses": {"200": {"description": "new"}}}}
    schema = new["paths"]["/item"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    schema["properties"]["extra"] = {"type": "integer"}
    schema["description"] = "documentation is not a wire constraint"
    assert compare(old, new) == []


@pytest.mark.parametrize("old,new,response,broken", [
    ({"type": "string"}, {"type": "integer"}, False, True),
    ({"type": "string", "enum": ["a", "b"]}, {"type": "string", "enum": ["a"]}, False, True),
    ({"type": "string", "enum": ["a"]}, {"type": "string", "enum": ["a", "b"]}, False, False),
    ({"type": "string", "enum": ["a"]}, {"type": "string", "enum": ["a", "b"]}, True, True),
    ({"type": "string", "enum": ["a", "b"]}, {"type": "string", "enum": ["a"]}, True, False),
    ({"type": "integer", "minimum": 0}, {"type": "integer", "minimum": 1}, False, True),
    ({"type": "integer", "maximum": 5}, {"type": "integer", "maximum": 6}, True, True),
    ({"type": "string", "maxLength": 5}, {"type": "string", "maxLength": 4}, False, True),
    ({"type": "string"}, {"type": "string", "pattern": "^a"}, False, True),
    ({"type": "array", "items": {"type": "string"}},
     {"type": "array", "items": {"type": "integer"}}, True, True),
    ({"type": "string"}, {"anyOf": [{"type": "string"}, {"type": "null"}]}, False, False),
    ({"type": "string"}, {"anyOf": [{"type": "string"}, {"type": "null"}]}, True, True),
    ({"type": "object", "additionalProperties": True},
     {"type": "object", "additionalProperties": False}, False, True),
    ({"type": "object", "additionalProperties": {"type": "string"}},
     {"type": "object", "additionalProperties": {"type": "integer"}}, False, True),
    ({"type": "object", "properties": {"name": {"type": "string"}}},
     {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
     False, True),
    ({"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
     {"type": "object", "properties": {"name": {"type": "string"}}}, True, True),
    ({"type": "object", "properties": {"name": {"type": "string"}}},
     {"type": "object", "properties": {}}, True, True),
])
def test_schema_wire_changes(old, new, response, broken):
    errors = compare(contract(old, response=response), contract(new, response=response))
    assert bool(errors) is broken
    if errors:
        assert all("/item" in error for error in errors)


@pytest.mark.parametrize("mutation", ["operation", "status", "content", "required_body",
                                        "required_parameter", "parameter_type", "security"])
def test_operation_breaks_are_rejected(mutation):
    old = contract()
    old["paths"]["/item"]["parameters"] = [
        {"name": "q", "in": "query", "schema": {"type": "string"}},
    ]
    new = copy.deepcopy(old)
    op = new["paths"]["/item"]["post"]
    if mutation == "operation":
        del new["paths"]["/item"]["post"]
    elif mutation == "status":
        del op["responses"]["200"]
    elif mutation == "content":
        del op["requestBody"]["content"]["application/json"]
    elif mutation == "required_body":
        op["requestBody"]["required"] = True
    elif mutation == "required_parameter":
        new["paths"]["/item"]["parameters"][0]["required"] = True
    elif mutation == "parameter_type":
        new["paths"]["/item"]["parameters"][0]["schema"]["type"] = "integer"
    else:
        op["security"] = [{"bearer": []}]
    assert compare(old, new)


def test_recursive_refs_still_detect_nested_change():
    old = contract({"$ref": "#/components/schemas/Node"}, response=True)
    old["components"]["schemas"]["Node"] = {"type": "object", "properties": {
        "child": {"$ref": "#/components/schemas/Node"}, "value": {"type": "string"},
    }}
    assert compare(old, copy.deepcopy(old)) == []
    new = copy.deepcopy(old)
    new["components"]["schemas"]["Node"]["properties"]["value"] = {"type": "integer"}
    assert compare(old, new)


def test_unsupported_constraint_and_unresolved_ref_fail_closed():
    for schema in ({"not": {"type": "string"}}, {"$ref": "https://example.test/schema"}):
        assert compare(contract(schema), contract(schema))


def test_committed_contract_compares_to_itself():
    doc = json.loads((SCRIPT.parents[1] / "openapi.json").read_text(encoding="utf-8"))
    assert compare(doc, doc) == []


def test_cli_reports_break_and_nonzero(tmp_path):
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(json.dumps(contract()), encoding="utf-8")
    new.write_text(json.dumps({"openapi": "3.1.0", "paths": {}}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), str(old), str(new)],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "/item" in result.stdout


def test_nullable_union_sibling_constraints_fail_closed():
    schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert compare(contract(schema), contract({**schema, "minLength": 5}))


def test_const_constrains_enum_in_request_and_response():
    schema = {"type": "string", "enum": ["a", "b"]}
    narrow = {**schema, "const": "a"}
    assert compare(contract(schema), contract(narrow))
    assert compare(contract(narrow, response=True), contract(schema, response=True))
    assert compare(contract(narrow), contract(schema)) == []


def test_nullable_response_documented_field_cannot_disappear():
    schema = {"anyOf": [{"type": "object", "properties": {"name": {"type": "string"}}},
                        {"type": "null"}]}
    new = {"anyOf": [{"type": "object", "properties": {}}, {"type": "null"}]}
    assert compare(contract(schema, response=True), contract(new, response=True))
    assert compare(contract(schema, response=True), contract(schema, response=True)) == []


def test_nullable_response_can_narrow_without_removing_documented_fields():
    schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert compare(contract(schema, response=True),
                   contract({"type": "string"}, response=True)) == []


def test_referenced_authentication_scheme_wire_changes_fail():
    old = contract()
    old["security"] = [{"key": []}]
    old["components"]["securitySchemes"] = {
        "key": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
    }
    new = copy.deepcopy(old)
    new["components"]["securitySchemes"]["key"]["name"] = "X-Changed-Key"
    assert compare(old, new)
    assert compare(old, copy.deepcopy(old)) == []
