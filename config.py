from __future__ import annotations

from core import get_prefix_table
from core.db.base_module_tables import BaseModuleTables

MODULE_NAME = "melodi_mailbox"
PREFIX_TABLE = get_prefix_table(MODULE_NAME)


class MailTables(BaseModuleTables):
    """Noms de tables dynamiquement préfixés pour le module melodi_mailbox."""

    ACCOUNTS = f"{PREFIX_TABLE}accounts"
    ACCOUNT_ACCESS = f"{PREFIX_TABLE}account_access"
    IDENTITIES = f"{PREFIX_TABLE}identities"
    FOLDERS = f"{PREFIX_TABLE}folders"
    THREADS = f"{PREFIX_TABLE}threads"
    MESSAGES = f"{PREFIX_TABLE}messages"
    ATTACHMENTS = f"{PREFIX_TABLE}attachments"
    SYNC_STATES = f"{PREFIX_TABLE}sync_states"
    SIGNATURES = f"{PREFIX_TABLE}signatures"
    TEMPLATES = f"{PREFIX_TABLE}templates"
    RULES = f"{PREFIX_TABLE}rules"


class MailConfig:
    """Paramètres par défaut et garde-fous de sécurité de melodi_mailbox."""

    DEFAULT_CONNECTION_TIMEOUT: int = 15
    MAX_CONCURRENT_IMAP_CONNECTIONS: int = 20
    MAX_FAILED_AUTH_ATTEMPTS: int = 5
    AUTH_LOCKOUT_SECONDS: int = 300
    MAX_ATTACHMENT_SIZE_BYTES: int = 25 * 1024 * 1024  # 25 Mo
    BLOCKED_ATTACHMENT_EXTENSIONS: tuple[str, ...] = (
        ".exe",
        ".bat",
        ".cmd",
        ".com",
        ".msi",
        ".scr",
        ".pif",
        ".vbs",
        ".vbe",
        ".js",
        ".jse",
        ".wsf",
        ".wsh",
        ".ps1",
        ".sh",
        ".dll",
        ".cpl",
        ".hta",
    )
    ALLOWED_SECURITY_MODES: tuple[str, ...] = ("ssl", "starttls", "none")
    ALLOWED_AUTH_MODES: tuple[str, ...] = ("password", "oauth2")
    ALLOWED_PROVIDER_TYPES: tuple[str, ...] = ("imap_smtp", "gmail", "msgraph")
