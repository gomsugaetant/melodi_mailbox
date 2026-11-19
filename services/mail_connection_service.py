from __future__ import annotations

import logging
import time
from typing import Optional

from core.service import Service
from modules.melodi_mailbox.config import MailConfig
from modules.melodi_mailbox.contracts.payloads import MailAutodiscoverResultDTO
from modules.melodi_mailbox.providers import (
    BaseMailProvider,
    ConnectionTestResult,
    ImapSmtpProvider,
    MailAccountCredentials,
    autodiscover_mail_settings,
)

logger = logging.getLogger("melodi_mailbox.connection")


class MailConnectionService(Service):
    """
    Service de détection automatique, fabrique de connecteurs (IMAP/SMTP, futurs Gmail/Graph)
    et test de connexion avec limitation de tentatives (rate-limiting).
    """

    def __init__(self, module):
        super().__init__(module)
        self._memory_rate_limit: dict[str, list[float]] = {}

    def build_provider(self, credentials: MailAccountCredentials) -> BaseMailProvider:
        ptype = (credentials.provider_type or "imap_smtp").lower()
        if ptype == "imap_smtp":
            return ImapSmtpProvider(credentials)
        raise ValueError(
            f"Le connecteur '{ptype}' n'est pas encore activé (prévu en Phase 6 : OAuth2 / Gmail / Graph)."
        )

    def _check_rate_limit(self, key: str) -> Optional[int]:
        """
        Limite les tests de connexion échoués par utilisateur/compte pour prévenir le bruteforce.
        Retourne le nombre de secondes restantes si bloqué, sinon None.
        """
        now = time.time()
        window = MailConfig.AUTH_LOCKOUT_SECONDS
        attempts = [ts for ts in self._memory_rate_limit.get(key, []) if now - ts < window]
        self._memory_rate_limit[key] = attempts
        if len(attempts) >= MailConfig.MAX_FAILED_AUTH_ATTEMPTS:
            retry_after = int(window - (now - attempts[0]))
            return max(retry_after, 1)
        return None

    def _record_failed_attempt(self, key: str) -> None:
        now = time.time()
        attempts = self._memory_rate_limit.setdefault(key, [])
        attempts.append(now)

    def _clear_failed_attempts(self, key: str) -> None:
        self._memory_rate_limit.pop(key, None)

    async def autodiscover(
        self, email_address: str, probe_dns: bool = True
    ) -> MailAutodiscoverResultDTO:
        return await autodiscover_mail_settings(email_address, probe_dns=probe_dns)

    async def test_connection(
        self,
        credentials: MailAccountCredentials,
        rate_limit_key: str,
        test_imap: bool = True,
        test_smtp: bool = True,
    ) -> ConnectionTestResult:
        retry_after = self._check_rate_limit(rate_limit_key)
        if retry_after is not None:
            logger.warning("[melodi_mailbox] Rate-limit atteint pour %s (%ss)", rate_limit_key, retry_after)
            return ConnectionTestResult(
                success=False,
                imap_ok=False,
                smtp_ok=False,
                imap_message=f"Trop de tentatives échouées. Réessayez dans {retry_after}s.",
                smtp_message=f"Trop de tentatives échouées. Réessayez dans {retry_after}s.",
            )

        provider = self.build_provider(credentials)
        result = await provider.test_connection(test_imap=test_imap, test_smtp=test_smtp)

        if result.success:
            self._clear_failed_attempts(rate_limit_key)
            logger.info(
                "[melodi_mailbox] Test connexion réussi pour %s (imap=%sms, smtp=%sms, folders=%s)",
                credentials.email_address,
                result.imap_latency_ms,
                result.smtp_latency_ms,
                len(result.folders),
            )
        else:
            self._record_failed_attempt(rate_limit_key)
            logger.warning(
                "[melodi_mailbox] Échec test connexion pour %s (imap_ok=%s, smtp_ok=%s)",
                credentials.email_address,
                result.imap_ok,
                result.smtp_ok,
            )

        return result
