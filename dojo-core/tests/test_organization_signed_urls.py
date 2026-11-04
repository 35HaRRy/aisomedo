import pytest
from dojo.adapters.signed_urls import HmacSignedUrlStore


def test_organization_signed_artifact_resolves_in_an_independent_process_store(tmp_path):
    artifact = tmp_path / "organizations" / "2" / "package" / "render" / "reel.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"approved render")
    issuer = HmacSignedUrlStore(base_url="https://example.test", secret="test-secret",
                                media_root=tmp_path, organization_id=2)
    receiver = HmacSignedUrlStore(base_url="https://example.test", secret="test-secret",
                                  media_root=tmp_path)
    url = issuer.create(artifact)
    assert receiver.token_owner(url) == 2
    assert receiver.resolve(url) == artifact
    wrong_scope = HmacSignedUrlStore(base_url="https://example.test", secret="test-secret",
                                     media_root=tmp_path, organization_id=3)
    with pytest.raises(ValueError):
        wrong_scope.resolve(url)
    with pytest.raises(ValueError):
        receiver.resolve(url[:-1] + ("a" if url[-1] != "a" else "b"))


def test_organization_cannot_sign_another_workspaces_file(tmp_path):
    foreign = tmp_path / "organizations" / "2" / "package" / "render" / "reel.mp4"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"foreign")
    signer = HmacSignedUrlStore(base_url="https://example.test", secret="test-secret",
                                media_root=tmp_path, organization_id=1)
    with pytest.raises(ValueError):
        signer.create(foreign)


def test_revocation_is_shared_by_independent_worker_and_api_instances(tmp_path):
    artifact = tmp_path / "package" / "render" / "reel.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"approved render")
    issuer = HmacSignedUrlStore(base_url="https://example.test", secret="test-secret",
                                media_root=tmp_path, organization_id=1)
    receiver = HmacSignedUrlStore(base_url="https://example.test", secret="test-secret",
                                  media_root=tmp_path)
    url = issuer.create(artifact)
    assert receiver.resolve(url) == artifact
    issuer.revoke(url)
    with pytest.raises(ValueError):
        receiver.resolve(url)
