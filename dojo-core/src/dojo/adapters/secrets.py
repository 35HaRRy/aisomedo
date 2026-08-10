from __future__ import annotations

import base64
import hashlib
import secrets as stdlib_secrets

CODE_ALPHABET = "23456789abcdefghijkmnpqrstuvwxyz"
CODE_LENGTH = 8
TOKEN_BYTES = 32


class Sha256Hasher:
    def hash(self, secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class RandomSecretGenerator:
    def generate_code(self) -> str:
        return "".join(stdlib_secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))

    def generate_token(self) -> str:
        return (
            base64.urlsafe_b64encode(stdlib_secrets.token_bytes(TOKEN_BYTES))
            .decode("ascii")
            .rstrip("=")
        )
