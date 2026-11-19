from __future__ import annotations

from typing import Optional, TypedDict


class MailAccountDTO(TypedDict, total=False):
    """Représentation publique d'un compte email (JAMAIS de mot de passe ni de token)."""

    account_id: str
    organization_id: str
    owner_user_id: str
    name: str
    email_address: str
    sender_name: Optional[str]
    provider_type: str
    imap_host: Optional[str]
    imap_port: Optional[int]
    imap_security: str
    smtp_host: Optional[str]
    smtp_port: Optional[int]
    smtp_security: str
    auth_mode: str
    username: Optional[str]
    has_credentials: bool
    is_default: bool
    is_active: bool
    sync_status: str
    last_sync_at: Optional[str]
    last_error: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


class MailConnectionTestPayload(TypedDict, total=False):
    """Payload de test de connexion IMAP/SMTP."""

    provider_type: str
    email_address: str
    username: str
    password: str
    imap_host: str
    imap_port: int
    imap_security: str
    smtp_host: str
    smtp_port: int
    smtp_security: str
    auth_mode: str
    test_imap: bool
    test_smtp: bool


class MailConnectionTestResultDTO(TypedDict, total=False):
    """Résultat d'un test de connexion IMAP/SMTP."""

    success: bool
    imap_ok: bool
    smtp_ok: bool
    imap_message: str
    smtp_message: str
    imap_latency_ms: Optional[int]
    smtp_latency_ms: Optional[int]
    imap_capabilities: list[str]
    folders_detected: int


class MailAutodiscoverResultDTO(TypedDict, total=False):
    """Paramètres serveur détectés automatiquement pour une adresse email."""

    detected: bool
    provider_label: str
    provider_type: str
    imap_host: str
    imap_port: int
    imap_security: str
    smtp_host: str
    smtp_port: int
    smtp_security: str
    auth_mode: str
    notes: Optional[str]


class MailAccountDeletedEventPayload(TypedDict):
    """Événement émis après la suppression transactionnelle d'un compte email."""

    account_id: str
    organization_id: str
    owner_user_id: str
    email_address: str
