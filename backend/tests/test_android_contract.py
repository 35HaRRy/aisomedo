from backend.main import create_app


def test_android_wire_responses_are_described():
    schema = create_app().openapi()
    paths = schema["paths"]
    compat = paths["/api/compat"]["get"]["responses"]["200"]["content"]
    assert compat["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CompatInfo"
    }
    pairing = paths["/api/pairing/validate"]["post"]["responses"]["200"]["content"]
    assert pairing["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PairingOut"
    }
    content = paths["/api/meta/instagram/token"]["post"]["requestBody"]["content"]
    body = content["application/json"]["schema"]
    assert body["properties"]["access_token"]["type"] == "string"
    assert body["required"] == ["access_token"]
