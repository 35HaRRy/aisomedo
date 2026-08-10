from __future__ import annotations

from dojo.adapters.secrets import (
    CODE_ALPHABET,
    CODE_LENGTH,
    RandomSecretGenerator,
    Sha256Hasher,
)


def test_sha256_hashes_deterministically() -> None:
    hasher = Sha256Hasher()
    assert hasher.hash("abc") == hasher.hash("abc")
    assert hasher.hash("abc") != hasher.hash("abd")
    assert len(hasher.hash("abc")) == 64


def test_generate_code_shape() -> None:
    generator = RandomSecretGenerator()
    code = generator.generate_code()
    assert len(code) == CODE_LENGTH
    assert all(c in CODE_ALPHABET for c in code)
    assert code != generator.generate_code()


def test_generate_token_is_urlsafe_and_long() -> None:
    token = RandomSecretGenerator().generate_token()
    assert len(token) >= 32
    assert token.replace("-", "").replace("_", "").isalnum()
