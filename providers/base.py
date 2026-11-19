from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MailAccountCredentials:
    """Paramètres de connexion déchiffrés en mémoire uniquement (ne jamais logger)."""

    email_address: str
    provider_type: str = "imap_smtp"
    auth_mode: str = "password"
    username: Optional[str] = None
    password: Optional[str] = None
    oauth_access_token: Optional[str] = None
    oauth_refresh_token: Optional[str] = None
    imap_host: Optional[str] = None
    imap_port: int = 993
    imap_security: str = "ssl"
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_security: str = "starttls"
    timeout: int = 15

    def __repr__(self) -> str:
        return (
            f"MailAccountCredentials(email={self.email_address!r}, "
            f"provider={self.provider_type!r}, imap={self.imap_host}:{self.imap_port}, "
            f"smtp={self.smtp_host}:{self.smtp_port}, auth={self.auth_mode!r})"
        )


@dataclass
class RemoteFolderInfo:
    """Métadonnées d'un dossier distant (IMAP, Gmail Labels, MS Graph MailFolder)."""

    name: str
    remote_name: str
    delimiter: str = "/"
    folder_type: str = "custom"
    sort_order: int = 100
    flags: list[str] = field(default_factory=list)


@dataclass
class ConnectionTestResult:
    """Résultat détaillé d'un diagnostic de connexion entrante et sortante."""

    success: bool
    imap_ok: bool = False
    smtp_ok: bool = False
    imap_message: str = ""
    smtp_message: str = ""
    imap_latency_ms: Optional[int] = None
    smtp_latency_ms: Optional[int] = None
    imap_capabilities: list[str] = field(default_factory=list)
    folders: list[RemoteFolderInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "imap_ok": self.imap_ok,
            "smtp_ok": self.smtp_ok,
            "imap_message": self.imap_message,
            "smtp_message": self.smtp_message,
            "imap_latency_ms": self.imap_latency_ms,
            "smtp_latency_ms": self.smtp_latency_ms,
            "imap_capabilities": self.imap_capabilities,
            "folders_detected": len(self.folders),
        }


@dataclass
class FetchedAttachmentData:
    """Pièce jointe brute extraite d'un message MIME entrant."""

    filename: str
    mime_type: str
    content: bytes
    size_bytes: int
    content_id: Optional[str] = None
    is_inline: bool = False


@dataclass
class FetchedEmailData:
    """Message email normalisé extrait d'un serveur distant."""

    imap_uid: int
    imap_uid_validity: int
    imap_mailbox: str
    rfc_message_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: list[str] = field(default_factory=list)
    from_name: str = ""
    from_email: str = ""
    to: list[dict[str, str]] = field(default_factory=list)
    cc: list[dict[str, str]] = field(default_factory=list)
    reply_to: Optional[str] = None
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    raw_headers: dict[str, str] = field(default_factory=dict)
    is_read: bool = False
    is_starred: bool = False
    is_draft: bool = False
    size_bytes: int = 0
    sent_at: Optional[str] = None
    received_at: Optional[str] = None
    attachments: list[FetchedAttachmentData] = field(default_factory=list)


@dataclass
class FetchBatchResult:
    """Résultat d'un lot de récupération depuis un dossier distant."""

    uid_validity: Optional[int]
    last_uid: int
    messages: list[FetchedEmailData] = field(default_factory=list)


@dataclass
class OutboundAttachmentData:
    """Pièce jointe préparée pour l'envoi sortant."""

    filename: str
    mime_type: str
    content: bytes
    content_id: Optional[str] = None
    is_inline: bool = False


@dataclass
class OutboundEmailData:
    """Enveloppe complète d'un email sortant."""

    from_name: str
    from_email: str
    to: list[str]
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    reply_to: Optional[str] = None
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    in_reply_to: Optional[str] = None
    references: list[str] = field(default_factory=list)
    rfc_message_id: Optional[str] = None
    attachments: list[OutboundAttachmentData] = field(default_factory=list)


class BaseMailProvider(ABC):
    """
    Interface abstraite de fournisseur de messagerie.
    Permet de remplacer IMAP/SMTP par Gmail API ou Microsoft Graph (Phase 6)
    sans modifier les services métier ni la SPA.
    """

    def __init__(self, credentials: MailAccountCredentials):
        self.credentials = credentials

    @abstractmethod
    async def test_connection(
        self, test_imap: bool = True, test_smtp: bool = True
    ) -> ConnectionTestResult:
        """Teste la connectivité et l'authentification entrante et sortante."""

    @abstractmethod
    async def list_folders(self) -> list[RemoteFolderInfo]:
        """Liste les dossiers distants avec détection des dossiers système."""

    @abstractmethod
    async def fetch_messages(
        self,
        mailbox: str = "INBOX",
        last_uid: int = 0,
        limit: int = 50,
    ) -> FetchBatchResult:
        """Récupère les nouveaux messages d'un dossier depuis last_uid."""

    @abstractmethod
    async def send_message(
        self,
        outbound: OutboundEmailData,
        sent_mailbox: Optional[str] = None,
    ) -> str:
        """Envoie un email via le transport sortant et retourne le Message-ID."""

    @abstractmethod
    async def set_message_flags(
        self,
        mailbox: str,
        imap_uid: int,
        flags: list[str],
        add: bool = True,
    ) -> bool:
        """Ajoute ou retire des drapeaux IMAP (ex. \\Seen, \\Flagged)."""

    @abstractmethod
    async def move_message(
        self,
        src_mailbox: str,
        imap_uid: int,
        dst_mailbox: str,
    ) -> bool:
        """Déplace un message d'un dossier distant vers un autre."""
