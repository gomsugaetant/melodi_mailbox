from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.orm.model import BaseModel
from modules.melodi_mailbox.config import MailTables


class MailAccountModel(BaseModel):
    """Compte de messagerie connecté par un utilisateur au sein d'une organisation."""

    __tablename__ = MailTables.ACCOUNTS

    account_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    owner_user_id: Mapped[str] = mapped_column(String(100), nullable=False)

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email_address: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    provider_type: Mapped[str] = mapped_column(String(32), nullable=False, default="imap_smtp")

    # Configuration IMAP
    imap_host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    imap_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=993)
    imap_security: Mapped[str] = mapped_column(String(20), nullable=False, default="ssl")

    # Configuration SMTP
    smtp_host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=587)
    smtp_security: Mapped[str] = mapped_column(String(20), nullable=False, default="starttls")

    # Authentification & secrets chiffrés (JAMAIS exposés en clair)
    auth_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="password")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    encrypted_password: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    encrypted_oauth_access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    encrypted_oauth_refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    oauth_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # État et synchronisation
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sync_status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Sécurité anti-bruteforce / verrouillage
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "owner_user_id",
            "email_address",
            name=f"uq_{MailTables.ACCOUNTS}_org_owner_email",
        ),
        CheckConstraint(
            "imap_port IS NULL OR (imap_port >= 1 AND imap_port <= 65535)",
            name=f"ck_{MailTables.ACCOUNTS}_imap_port_range",
        ),
        CheckConstraint(
            "smtp_port IS NULL OR (smtp_port >= 1 AND smtp_port <= 65535)",
            name=f"ck_{MailTables.ACCOUNTS}_smtp_port_range",
        ),
        Index(f"ix_{MailTables.ACCOUNTS}_org_active", "organization_id", "is_active"),
        Index(f"ix_{MailTables.ACCOUNTS}_owner_default", "owner_user_id", "is_default"),
    )


class MailAccountAccessModel(BaseModel):
    """Contrôle d'accès délégué par compte email (boîtes partagées contact@, support@)."""

    __tablename__ = MailTables.ACCOUNT_ACCESS

    access_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            f"{MailTables.ACCOUNTS}.account_id",
            name=f"fk_{MailTables.ACCOUNT_ACCESS}_account_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    can_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_send: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_manage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "user_id",
            name=f"uq_{MailTables.ACCOUNT_ACCESS}_account_user",
        ),
        Index(f"ix_{MailTables.ACCOUNT_ACCESS}_user_id", "user_id"),
    )


class MailIdentityModel(BaseModel):
    """Identité d'expéditeur / alias associée à un compte email."""

    __tablename__ = MailTables.IDENTITIES

    identity_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            f"{MailTables.ACCOUNTS}.account_id",
            name=f"fk_{MailTables.IDENTITIES}_account_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email_address: Mapped[str] = mapped_column(String(255), nullable=False)
    reply_to_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    signature_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "email_address",
            name=f"uq_{MailTables.IDENTITIES}_account_email",
        ),
        Index(f"ix_{MailTables.IDENTITIES}_account_default", "account_id", "is_default"),
    )


class MailFolderModel(BaseModel):
    """Dossier IMAP ou personnalisé rattaché à un compte email."""

    __tablename__ = MailTables.FOLDERS

    folder_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            f"{MailTables.ACCOUNTS}.account_id",
            name=f"fk_{MailTables.FOLDERS}_account_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    remote_name: Mapped[str] = mapped_column(String(500), nullable=False)
    delimiter: Mapped[str] = mapped_column(String(10), nullable=False, default="/")
    folder_type: Mapped[str] = mapped_column(String(32), nullable=False, default="custom")
    parent_folder_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey(
            f"{MailTables.FOLDERS}.folder_id",
            name=f"fk_{MailTables.FOLDERS}_parent_folder_id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    uid_validity: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    unread_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_subscribed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "remote_name",
            name=f"uq_{MailTables.FOLDERS}_account_remote_name",
        ),
        Index(f"ix_{MailTables.FOLDERS}_account_type", "account_id", "folder_type"),
    )


class MailSyncStateModel(BaseModel):
    """État de synchronisation incrémentale (UID / UIDVALIDITY / MODSEQ / cursor) par dossier."""

    __tablename__ = MailTables.SYNC_STATES

    sync_state_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            f"{MailTables.ACCOUNTS}.account_id",
            name=f"fk_{MailTables.SYNC_STATES}_account_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    folder_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            f"{MailTables.FOLDERS}.folder_id",
            name=f"fk_{MailTables.SYNC_STATES}_folder_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    uid_validity: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_uid: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    highest_modseq: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sync_cursor: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    last_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    messages_synced_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "folder_id",
            name=f"uq_{MailTables.SYNC_STATES}_account_folder",
        ),
        Index(f"ix_{MailTables.SYNC_STATES}_status_updated", "status", "updated_at"),
    )
