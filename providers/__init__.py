from .base import (
    BaseMailProvider,
    ConnectionTestResult,
    FetchBatchResult,
    FetchedAttachmentData,
    FetchedEmailData,
    MailAccountCredentials,
    OutboundAttachmentData,
    OutboundEmailData,
    RemoteFolderInfo,
)
from .autodiscover import autodiscover_mail_settings
from .imap_smtp_provider import ImapSmtpProvider

__all__ = [
    "BaseMailProvider",
    "ConnectionTestResult",
    "FetchBatchResult",
    "FetchedAttachmentData",
    "FetchedEmailData",
    "MailAccountCredentials",
    "OutboundAttachmentData",
    "OutboundEmailData",
    "RemoteFolderInfo",
    "ImapSmtpProvider",
    "autodiscover_mail_settings",
]
