from .base import (
    BaseMailProvider,
    ConnectionTestResult,
    MailAccountCredentials,
    RemoteFolderInfo,
)
from .autodiscover import autodiscover_mail_settings
from .imap_smtp_provider import ImapSmtpProvider

__all__ = [
    "BaseMailProvider",
    "ConnectionTestResult",
    "MailAccountCredentials",
    "RemoteFolderInfo",
    "ImapSmtpProvider",
    "autodiscover_mail_settings",
]
