from __future__ import annotations

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class CryptoService:
    """
    Service de chiffrement symétrique au repos pour les mots de passe IMAP/SMTP
    et tokens OAuth2 (Fernet AES-128-CBC + HMAC-SHA256 avec dérivation HKDF-SHA256).
    """

    _HKDF_SALT = b"melodi_mailbox_credential_vault_v1"
    _HKDF_INFO = b"melodi-mail-fernet-key"

    def __init__(self, master_secret: Optional[str] = None):
        raw_secret = (
            master_secret
            or os.environ.get("MELODI_MAILBOX_ENCRYPTION_KEY")
            or "melodi_default_fallback_secret_key"
        )
        self._fernet = self._build_fernet(raw_secret)

    @classmethod
    def from_app(cls, app) -> "CryptoService":
        env_key = os.environ.get("MELODI_MAILBOX_ENCRYPTION_KEY")
        if env_key:
            return cls(env_key)
        app_secret = getattr(getattr(app, "config", None), "secret_key", None)
        return cls(app_secret)

    def _build_fernet(self, secret: str) -> Fernet:
        # Si la clé fournie est déjà une clé Fernet valide (32 octets encodés en urlsafe base64)
        secret_bytes = secret.encode("utf-8")
        try:
            decoded = base64.urlsafe_b64decode(secret_bytes)
            if len(decoded) == 32:
                return Fernet(secret_bytes)
        except Exception:
            pass

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._HKDF_SALT,
            info=self._HKDF_INFO,
        )
        derived_key = base64.urlsafe_b64encode(hkdf.derive(secret_bytes))
        return Fernet(derived_key)

    def encrypt(self, plaintext: Optional[str]) -> Optional[str]:
        if plaintext is None or plaintext == "":
            return None
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, ciphertext: Optional[str]) -> Optional[str]:
        if not ciphertext:
            return None
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(
                "Impossible de déchiffrer les identifiants du compte (clé de chiffrement modifiée ou donnée corrompue)."
            ) from exc
