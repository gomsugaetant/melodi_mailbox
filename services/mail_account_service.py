from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from core.service import Service
from modules.melodi_mailbox.config import MailConfig
from modules.melodi_mailbox.contracts.payloads import MailAccountDTO
from modules.melodi_mailbox.models.models import MailAccountModel, MailFolderModel, MailIdentityModel
from modules.melodi_mailbox.providers import ConnectionTestResult, MailAccountCredentials
from modules.melodi_mailbox.repositories import MailAccountRepository, MailFolderRepository
from modules.melodi_mailbox.services.crypto_service import CryptoService
from modules.melodi_mailbox.services.mail_connection_service import MailConnectionService

logger = logging.getLogger("melodi_mailbox.accounts")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MailAccountError(Exception):
    """Erreur métier contrôlée sur la gestion des comptes email."""

    def __init__(self, message: str, code: str = "MAIL_ACCOUNT_ERROR", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class MailAccountService(Service):
    """
    Service de gestion des comptes email, identités, dossiers découverts,
    permissions par compte et chiffrement des identifiants.
    """

    def __init__(
        self,
        module,
        account_repo: Optional[MailAccountRepository] = None,
        folder_repo: Optional[MailFolderRepository] = None,
        crypto_service: Optional[CryptoService] = None,
        connection_service: Optional[MailConnectionService] = None,
    ):
        super().__init__(module)
        self.account_repo = account_repo or MailAccountRepository(module)
        self.folder_repo = folder_repo or MailFolderRepository(module)
        self.crypto = crypto_service or CryptoService.from_app(getattr(module, "app", None))
        self.connection_service = connection_service or MailConnectionService(module)

    # ── Sérialisation sécurisée (ZÉRO exposition de secret) ───────────────────

    @staticmethod
    def to_dto(account: MailAccountModel) -> MailAccountDTO:
        return {
            "account_id": account.account_id,
            "organization_id": account.organization_id,
            "owner_user_id": account.owner_user_id,
            "name": account.name,
            "email_address": account.email_address,
            "sender_name": account.sender_name,
            "provider_type": account.provider_type,
            "imap_host": account.imap_host,
            "imap_port": account.imap_port,
            "imap_security": account.imap_security,
            "smtp_host": account.smtp_host,
            "smtp_port": account.smtp_port,
            "smtp_security": account.smtp_security,
            "auth_mode": account.auth_mode,
            "username": account.username,
            "has_credentials": bool(
                account.encrypted_password or account.encrypted_oauth_access_token
            ),
            "is_default": bool(account.is_default),
            "is_active": bool(account.is_active),
            "sync_status": account.sync_status,
            "last_sync_at": account.last_sync_at.isoformat() if account.last_sync_at else None,
            "last_error": account.last_error,
            "created_at": account.created_at.isoformat() if account.created_at else None,
            "updated_at": account.updated_at.isoformat() if account.updated_at else None,
        }

    @staticmethod
    def folder_to_dict(folder: MailFolderModel) -> dict[str, Any]:
        return {
            "folder_id": folder.folder_id,
            "account_id": folder.account_id,
            "name": folder.name,
            "remote_name": folder.remote_name,
            "delimiter": folder.delimiter,
            "folder_type": folder.folder_type,
            "unread_count": folder.unread_count,
            "total_count": folder.total_count,
            "sort_order": folder.sort_order,
        }

    # ── Validation & Contrôle d'accès ─────────────────────────────────────────

    def _validate_account_payload(self, data: dict, is_create: bool = True) -> None:
        if is_create:
            name = (data.get("name") or "").strip()
            email_address = (data.get("email_address") or "").strip().lower()
            if not name:
                raise MailAccountError("Le nom du compte est obligatoire.", "VALIDATION_FAILED", 400)
            if not email_address or not _EMAIL_RE.match(email_address):
                raise MailAccountError("L'adresse email est invalide.", "VALIDATION_FAILED", 400)

        provider_type = (data.get("provider_type") or "imap_smtp").lower()
        if provider_type not in MailConfig.ALLOWED_PROVIDER_TYPES:
            raise MailAccountError("Type de fournisseur non supporté.", "VALIDATION_FAILED", 400)

        auth_mode = (data.get("auth_mode") or "password").lower()
        if auth_mode not in MailConfig.ALLOWED_AUTH_MODES:
            raise MailAccountError("Mode d'authentification non supporté.", "VALIDATION_FAILED", 400)

        for field_name in ("imap_security", "smtp_security"):
            if field_name in data and data[field_name]:
                if str(data[field_name]).lower() not in MailConfig.ALLOWED_SECURITY_MODES:
                    raise MailAccountError(
                        f"Mode de sécurité invalide pour {field_name}.", "VALIDATION_FAILED", 400
                    )

        for port_field in ("imap_port", "smtp_port"):
            if port_field in data and data[port_field] is not None and data[port_field] != "":
                try:
                    port_val = int(data[port_field])
                except (TypeError, ValueError) as exc:
                    raise MailAccountError(f"Port invalide pour {port_field}.", "VALIDATION_FAILED", 400) from exc
                if not (1 <= port_val <= 65535):
                    raise MailAccountError(
                        f"Le port {port_field} doit être compris entre 1 et 65535.",
                        "VALIDATION_FAILED",
                        400,
                    )

    async def _assert_access(
        self,
        account: Optional[MailAccountModel],
        organization_id: str,
        user_id: str,
        require_manage: bool = False,
        is_sudo: bool = False,
        session=None,
    ) -> MailAccountModel:
        if account is None or account.organization_id != organization_id:
            raise MailAccountError("Compte email introuvable.", "NOT_FOUND", 404)

        if is_sudo or account.owner_user_id == user_id:
            return account

        access = await self.account_repo.get_access_for_user(account.account_id, user_id, session=session)
        if not access:
            raise MailAccountError("Accès refusé à ce compte email.", "FORBIDDEN", 403)
        if require_manage and not access.can_manage:
            raise MailAccountError("Permission de gestion requise sur ce compte.", "FORBIDDEN", 403)
        if not require_manage and not access.can_read:
            raise MailAccountError("Permission de lecture requise sur ce compte.", "FORBIDDEN", 403)
        return account

    def build_credentials(self, account: MailAccountModel) -> MailAccountCredentials:
        return MailAccountCredentials(
            email_address=account.email_address,
            provider_type=account.provider_type,
            auth_mode=account.auth_mode,
            username=account.username or account.email_address,
            password=self.crypto.decrypt(account.encrypted_password),
            oauth_access_token=self.crypto.decrypt(account.encrypted_oauth_access_token),
            oauth_refresh_token=self.crypto.decrypt(account.encrypted_oauth_refresh_token),
            imap_host=account.imap_host,
            imap_port=account.imap_port or 993,
            imap_security=account.imap_security or "ssl",
            smtp_host=account.smtp_host,
            smtp_port=account.smtp_port or 587,
            smtp_security=account.smtp_security or "starttls",
            timeout=MailConfig.DEFAULT_CONNECTION_TIMEOUT,
        )

    # ── Opérations CRUD ───────────────────────────────────────────────────────

    async def list_accounts(
        self,
        organization_id: str,
        user_id: str,
        include_inactive: bool = True,
        is_sudo: bool = False,
    ) -> list[MailAccountDTO]:
        accounts = await self.account_repo.list_accessible_accounts(
            organization_id=organization_id,
            user_id=user_id,
            include_inactive=include_inactive,
            is_sudo=is_sudo,
        )
        return [self.to_dto(a) for a in accounts]

    async def get_account(
        self,
        account_id: str,
        organization_id: str,
        user_id: str,
        is_sudo: bool = False,
    ) -> MailAccountDTO:
        account = await self.account_repo.get_by_id(account_id, organization_id=organization_id)
        account = await self._assert_access(account, organization_id, user_id, is_sudo=is_sudo)
        return self.to_dto(account)

    async def create_account(
        self,
        organization_id: str,
        user_id: str,
        data: dict[str, Any],
    ) -> MailAccountDTO:
        self._validate_account_payload(data, is_create=True)
        email_address = data["email_address"].strip().lower()

        async with self.account_repo.get_session() as session:
            existing = await self.account_repo.get_by_org_owner_email(
                organization_id, user_id, email_address, session=session
            )
            if existing is not None:
                raise MailAccountError(
                    "Un compte avec cette adresse email existe déjà pour cet utilisateur.",
                    "DUPLICATE_ACCOUNT",
                    409,
                )

            existing_accounts = await self.account_repo.list_accessible_accounts(
                organization_id=organization_id,
                user_id=user_id,
                include_inactive=True,
                session=session,
            )
            is_default = bool(data.get("is_default")) or len(existing_accounts) == 0
            if is_default:
                await self.account_repo.clear_default_for_owner(
                    organization_id, user_id, session=session
                )

            account_id = str(uuid.uuid4())
            account = MailAccountModel(
                account_id=account_id,
                organization_id=organization_id,
                owner_user_id=user_id,
                name=data["name"].strip(),
                email_address=email_address,
                sender_name=(data.get("sender_name") or data["name"]).strip(),
                provider_type=(data.get("provider_type") or "imap_smtp").lower(),
                imap_host=(data.get("imap_host") or "").strip() or None,
                imap_port=int(data.get("imap_port") or 993),
                imap_security=(data.get("imap_security") or "ssl").lower(),
                smtp_host=(data.get("smtp_host") or "").strip() or None,
                smtp_port=int(data.get("smtp_port") or 587),
                smtp_security=(data.get("smtp_security") or "starttls").lower(),
                auth_mode=(data.get("auth_mode") or "password").lower(),
                username=(data.get("username") or email_address).strip(),
                encrypted_password=self.crypto.encrypt(data.get("password")),
                encrypted_oauth_access_token=self.crypto.encrypt(data.get("oauth_access_token")),
                encrypted_oauth_refresh_token=self.crypto.encrypt(data.get("oauth_refresh_token")),
                is_default=is_default,
                is_active=bool(data.get("is_active", True)),
                sync_status="idle",
            )
            await self.account_repo.create(account, session=session)

            # Créer automatiquement l'identité principale par défaut
            identity = MailIdentityModel(
                identity_id=str(uuid.uuid4()),
                account_id=account_id,
                organization_id=organization_id,
                display_name=account.sender_name or account.name,
                email_address=email_address,
                is_default=True,
            )
            await self.account_repo.create_identity(identity, session=session)

            # Initialiser les dossiers système par défaut (seront enrichis lors du 1er test/sync IMAP)
            default_folders = [
                {"name": "Boîte de réception", "remote_name": "INBOX", "folder_type": "inbox", "sort_order": 10},
                {"name": "Messages envoyés", "remote_name": "Sent", "folder_type": "sent", "sort_order": 30},
                {"name": "Brouillons", "remote_name": "Drafts", "folder_type": "drafts", "sort_order": 40},
                {"name": "Archives", "remote_name": "Archive", "folder_type": "archive", "sort_order": 50},
                {"name": "Spam", "remote_name": "Spam", "folder_type": "spam", "sort_order": 60},
                {"name": "Corbeille", "remote_name": "Trash", "folder_type": "trash", "sort_order": 70},
            ]
            await self.folder_repo.upsert_folders(
                account_id, organization_id, default_folders, session=session
            )

            await session.commit()
            logger.info("[melodi_mailbox] Compte créé: %s (%s) par user=%s", account_id, email_address, user_id)
            return self.to_dto(account)

    async def update_account(
        self,
        account_id: str,
        organization_id: str,
        user_id: str,
        data: dict[str, Any],
        is_sudo: bool = False,
    ) -> MailAccountDTO:
        self._validate_account_payload(data, is_create=False)

        async with self.account_repo.get_session() as session:
            account = await self.account_repo.get_by_id(
                account_id, organization_id=organization_id, session=session
            )
            account = await self._assert_access(
                account, organization_id, user_id, require_manage=True, is_sudo=is_sudo, session=session
            )

            updates: dict[str, Any] = {}
            for key in (
                "name",
                "sender_name",
                "provider_type",
                "imap_host",
                "imap_security",
                "smtp_host",
                "smtp_security",
                "auth_mode",
                "username",
            ):
                if key in data and data[key] is not None:
                    updates[key] = str(data[key]).strip()

            for port_key in ("imap_port", "smtp_port"):
                if port_key in data and data[port_key] is not None and data[port_key] != "":
                    updates[port_key] = int(data[port_key])

            if "is_active" in data:
                updates["is_active"] = bool(data["is_active"])

            # Ne remplacer le mot de passe que s'il est explicitement fourni non vide
            if data.get("password"):
                updates["encrypted_password"] = self.crypto.encrypt(str(data["password"]))
                updates["failed_attempts"] = 0
                updates["last_error"] = None

            if data.get("oauth_access_token"):
                updates["encrypted_oauth_access_token"] = self.crypto.encrypt(
                    str(data["oauth_access_token"])
                )
            if data.get("oauth_refresh_token"):
                updates["encrypted_oauth_refresh_token"] = self.crypto.encrypt(
                    str(data["oauth_refresh_token"])
                )

            if data.get("is_default") is True:
                await self.account_repo.clear_default_for_owner(
                    organization_id, account.owner_user_id, exclude_account_id=account_id, session=session
                )
                updates["is_default"] = True
            elif data.get("is_default") is False:
                updates["is_default"] = False

            updated = await self.account_repo.update_fields(account_id, updates, session=session)
            await session.commit()
            logger.info("[melodi_mailbox] Compte mis à jour: %s par user=%s", account_id, user_id)
            return self.to_dto(updated)

    async def delete_account(
        self,
        account_id: str,
        organization_id: str,
        user_id: str,
        is_sudo: bool = False,
    ) -> bool:
        """
        Suppression transactionnelle avec exécution obligatoire du filtre
        `mail.account.before_delete` avant suppression SQL (règle §3.1 AGENTS.md).
        """
        async with self.account_repo.get_session() as session:
            account = await self.account_repo.get_by_id(
                account_id, organization_id=organization_id, session=session
            )
            account = await self._assert_access(
                account, organization_id, user_id, require_manage=True, is_sudo=is_sudo, session=session
            )

            filter_payload = {
                "entity": account,
                "entity_id": account_id,
                "organization_id": organization_id,
                "session": session,
                "allowed": True,
                "reason": None,
            }
            if hasattr(self.module, "execute_filter"):
                filter_payload = await self.module.execute_filter(
                    "mail.account.before_delete", filter_payload
                )
                if isinstance(filter_payload, dict) and not filter_payload.get("allowed", True):
                    await session.rollback()
                    raise MailAccountError(
                        filter_payload.get("reason") or "Suppression bloquée par un module dépendant.",
                        "DELETE_VETOED",
                        409,
                    )

            email_address = account.email_address
            owner_user_id = account.owner_user_id
            deleted = await self.account_repo.delete_by_id(account_id, session=session)
            await session.commit()

        # Événement asynchrone émis uniquement APRÈS le commit réussi
        if deleted and hasattr(self.module, "notify_event_listener"):
            await self.module.notify_event_listener(
                "mail.account.deleted",
                {
                    "account_id": account_id,
                    "organization_id": organization_id,
                    "owner_user_id": owner_user_id,
                    "email_address": email_address,
                },
            )
        logger.info("[melodi_mailbox] Compte supprimé: %s par user=%s", account_id, user_id)
        return deleted

    # ── Test de connexion & découverte des dossiers ───────────────────────────

    async def test_saved_account_connection(
        self,
        account_id: str,
        organization_id: str,
        user_id: str,
        is_sudo: bool = False,
        test_imap: bool = True,
        test_smtp: bool = True,
    ) -> ConnectionTestResult:
        account = await self.account_repo.get_by_id(account_id, organization_id=organization_id)
        account = await self._assert_access(
            account, organization_id, user_id, require_manage=False, is_sudo=is_sudo
        )

        credentials = self.build_credentials(account)
        result = await self.connection_service.test_connection(
            credentials=credentials,
            rate_limit_key=f"acct:{account_id}:{user_id}",
            test_imap=test_imap,
            test_smtp=test_smtp,
        )

        async with self.account_repo.get_session() as session:
            if result.success:
                await self.account_repo.update_fields(
                    account_id,
                    {
                        "sync_status": "idle",
                        "last_error": None,
                        "failed_attempts": 0,
                        "last_sync_at": datetime.utcnow(),
                    },
                    session=session,
                )
                if result.folders:
                    await self.folder_repo.upsert_folders(
                        account_id,
                        organization_id,
                        [
                            {
                                "name": f.name,
                                "remote_name": f.remote_name,
                                "delimiter": f.delimiter,
                                "folder_type": f.folder_type,
                                "sort_order": f.sort_order,
                            }
                            for f in result.folders
                        ],
                        session=session,
                    )
            else:
                error_summary = " | ".join(
                    m for m in (result.imap_message if not result.imap_ok else "", result.smtp_message if not result.smtp_ok else "") if m
                )
                await self.account_repo.update_fields(
                    account_id,
                    {
                        "sync_status": "error",
                        "last_error": error_summary or "Échec du test de connexion.",
                        "failed_attempts": (account.failed_attempts or 0) + 1,
                    },
                    session=session,
                )
            await session.commit()

        return result

    async def test_ad_hoc_connection(
        self,
        user_id: str,
        payload: dict[str, Any],
    ) -> ConnectionTestResult:
        email_address = (payload.get("email_address") or "").strip().lower()
        if not email_address or not _EMAIL_RE.match(email_address):
            raise MailAccountError("Adresse email invalide.", "VALIDATION_FAILED", 400)

        credentials = MailAccountCredentials(
            email_address=email_address,
            provider_type=(payload.get("provider_type") or "imap_smtp").lower(),
            auth_mode=(payload.get("auth_mode") or "password").lower(),
            username=(payload.get("username") or email_address).strip(),
            password=payload.get("password"),
            imap_host=(payload.get("imap_host") or "").strip() or None,
            imap_port=int(payload.get("imap_port") or 993),
            imap_security=(payload.get("imap_security") or "ssl").lower(),
            smtp_host=(payload.get("smtp_host") or "").strip() or None,
            smtp_port=int(payload.get("smtp_port") or 587),
            smtp_security=(payload.get("smtp_security") or "starttls").lower(),
            timeout=MailConfig.DEFAULT_CONNECTION_TIMEOUT,
        )
        return await self.connection_service.test_connection(
            credentials=credentials,
            rate_limit_key=f"adhoc:{user_id}:{email_address}",
            test_imap=bool(payload.get("test_imap", True)),
            test_smtp=bool(payload.get("test_smtp", True)),
        )

    async def list_account_folders(
        self,
        account_id: str,
        organization_id: str,
        user_id: str,
        is_sudo: bool = False,
    ) -> list[dict[str, Any]]:
        account = await self.account_repo.get_by_id(account_id, organization_id=organization_id)
        await self._assert_access(account, organization_id, user_id, is_sudo=is_sudo)
        folders = await self.folder_repo.list_by_account(account_id)
        return [self.folder_to_dict(f) for f in folders]
