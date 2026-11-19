from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from core.service import Service
from modules.melodi_mailbox.models.models import MailFolderModel, MailMessageModel
from modules.melodi_mailbox.providers.base import FetchedEmailData
from modules.melodi_mailbox.repositories import (
    MailAccountRepository,
    MailFolderRepository,
    MailMessageRepository,
)
from modules.melodi_mailbox.services.mail_account_service import MailAccountService
from modules.melodi_mailbox.services.mail_attachment_service import MailAttachmentService
from modules.melodi_mailbox.services.mail_connection_service import MailConnectionService
from modules.melodi_mailbox.services.mail_thread_service import MailThreadService
from modules.melodi_mailbox.services.sanitizer_service import SanitizerService

logger = logging.getLogger("melodi_mailbox.sync")


class MailSyncService(Service):
    """
    Moteur de synchronisation IMAP incrémentale (UID + UIDVALIDITY),
    indépendant de l'UI et protégé contre les exécutions concurrentes.
    """

    def __init__(
        self,
        module,
        account_service: Optional[MailAccountService] = None,
        connection_service: Optional[MailConnectionService] = None,
        account_repo: Optional[MailAccountRepository] = None,
        folder_repo: Optional[MailFolderRepository] = None,
        message_repo: Optional[MailMessageRepository] = None,
        thread_service: Optional[MailThreadService] = None,
        attachment_service: Optional[MailAttachmentService] = None,
    ):
        super().__init__(module)
        self.account_repo = account_repo or MailAccountRepository(module)
        self.folder_repo = folder_repo or MailFolderRepository(module)
        self.message_repo = message_repo or MailMessageRepository(module)
        self.connection_service = connection_service or MailConnectionService(module)
        self.account_service = account_service or MailAccountService(
            module,
            account_repo=self.account_repo,
            folder_repo=self.folder_repo,
            connection_service=self.connection_service,
        )
        self.thread_service = thread_service or MailThreadService(module, self.message_repo)
        self.attachment_service = attachment_service or MailAttachmentService(module, self.message_repo)

    def _acquire_lock(self, key: str, ttl_seconds: int = 120) -> bool:
        cache = getattr(self.app, "cache", None)
        if not cache or not hasattr(cache, "get"):
            return True
        now = datetime.utcnow().timestamp()
        existing = cache.get(key)
        if existing and isinstance(existing, (int, float)) and existing > now:
            return False
        cache.set(key, now + ttl_seconds)
        return True

    def _release_lock(self, key: str) -> None:
        cache = getattr(self.app, "cache", None)
        if cache and hasattr(cache, "set"):
            cache.set(key, 0)

    @staticmethod
    def _parse_iso_dt(iso_str: Optional[str]) -> datetime:
        if iso_str:
            try:
                dt = datetime.fromisoformat(iso_str)
                return dt.replace(tzinfo=None)
            except Exception:
                pass
        return datetime.utcnow()

    async def sync_folder(
        self,
        account_id: str,
        folder_id: str,
        organization_id: str,
        user_id: str,
        is_sudo: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        lock_key = f"melodi_mailbox:sync_lock:{account_id}:{folder_id}"
        if not self._acquire_lock(lock_key):
            return {"synced": 0, "skipped": True, "reason": "Synchronisation déjà en cours."}

        try:
            account = await self.account_repo.get_by_id(account_id, organization_id=organization_id)
            account = await self.account_service._assert_access(
                account, organization_id, user_id, is_sudo=is_sudo
            )
            folder = await self.folder_repo.get_by_id(folder_id)
            if not folder or folder.account_id != account_id:
                return {"synced": 0, "skipped": True, "reason": "Dossier introuvable."}

            creds = self.account_service.build_credentials(account)
            provider = self.connection_service.build_provider(creds)

            sync_state = await self.folder_repo.get_sync_state(account_id, folder_id)
            last_uid = int(sync_state.last_uid) if sync_state else 0
            known_uid_validity = sync_state.uid_validity if sync_state else None

            await self.account_repo.update_fields(account_id, {"sync_status": "syncing"})
            await self.folder_repo.upsert_sync_state(
                account_id,
                folder_id,
                organization_id,
                {"status": "running", "last_started_at": datetime.utcnow(), "last_error": None},
            )

            batch = await provider.fetch_messages(
                mailbox=folder.remote_name,
                last_uid=last_uid,
                limit=limit,
            )

            # Détection de changement de UIDVALIDITY -> reset incrémental sans doublons
            if (
                known_uid_validity is not None
                and batch.uid_validity is not None
                and int(known_uid_validity) != int(batch.uid_validity)
            ):
                logger.warning(
                    "[melodi_mailbox] UIDVALIDITY modifié pour %s/%s (%s -> %s)",
                    account_id,
                    folder.remote_name,
                    known_uid_validity,
                    batch.uid_validity,
                )
                last_uid = 0
                batch = await provider.fetch_messages(
                    mailbox=folder.remote_name,
                    last_uid=0,
                    limit=limit,
                )

            imported_count = 0
            emitted_events: list[tuple[str, dict]] = []

            async with self.message_repo.get_session() as session:
                for item in batch.messages:
                    created, events = await self._ingest_fetched_message(
                        account_id=account_id,
                        organization_id=organization_id,
                        folder=folder,
                        item=item,
                        user_id=user_id,
                        session=session,
                    )
                    if created:
                        imported_count += 1
                    emitted_events.extend(events)

                new_last_uid = max(last_uid, batch.last_uid)
                await self.folder_repo.upsert_sync_state(
                    account_id,
                    folder_id,
                    organization_id,
                    {
                        "uid_validity": batch.uid_validity,
                        "last_uid": new_last_uid,
                        "status": "idle",
                        "last_completed_at": datetime.utcnow(),
                        "messages_synced_count": (sync_state.messages_synced_count if sync_state else 0)
                        + imported_count,
                    },
                    session=session,
                )
                await self.folder_repo.refresh_folder_counts(folder_id, session=session)
                await self.account_repo.update_fields(
                    account_id,
                    {"sync_status": "idle", "last_sync_at": datetime.utcnow(), "last_error": None},
                    session=session,
                )
                await session.commit()

            if hasattr(self.module, "notify_event_listener"):
                for evt_name, evt_payload in emitted_events:
                    await self.module.notify_event_listener(evt_name, evt_payload)

            return {
                "synced": imported_count,
                "last_uid": max(last_uid, batch.last_uid),
                "uid_validity": batch.uid_validity,
            }
        except Exception as exc:
            logger.exception("[melodi_mailbox] Erreur synchro dossier %s: %s", folder_id, exc)
            await self.account_repo.update_fields(
                account_id, {"sync_status": "error", "last_error": str(exc)}
            )
            await self.folder_repo.upsert_sync_state(
                account_id,
                folder_id,
                organization_id,
                {"status": "error", "last_error": str(exc)},
            )
            raise
        finally:
            self._release_lock(lock_key)

    async def sync_account(
        self,
        account_id: str,
        organization_id: str,
        user_id: str,
        is_sudo: bool = False,
        folder_id: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        account = await self.account_repo.get_by_id(account_id, organization_id=organization_id)
        account = await self.account_service._assert_access(
            account, organization_id, user_id, is_sudo=is_sudo
        )

        # Rafraîchir la liste des dossiers depuis le serveur distant
        try:
            creds = self.account_service.build_credentials(account)
            provider = self.connection_service.build_provider(creds)
            remote_folders = await provider.list_folders()
            if remote_folders:
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
                        for f in remote_folders
                    ],
                )
        except Exception as exc:
            logger.warning("[melodi_mailbox] Liste dossiers distante ignorée: %s", exc)

        folders = await self.folder_repo.list_by_account(account_id)
        if folder_id:
            target_folders = [f for f in folders if f.folder_id == folder_id]
        else:
            # Synchroniser prioritairement INBOX, Sent, Drafts
            target_folders = [
                f for f in folders if f.folder_type in ("inbox", "sent", "drafts")
            ] or folders[:3]

        total_synced = 0
        details = []
        for f in target_folders:
            res = await self.sync_folder(
                account_id=account_id,
                folder_id=f.folder_id,
                organization_id=organization_id,
                user_id=user_id,
                is_sudo=is_sudo,
                limit=limit,
            )
            total_synced += int(res.get("synced", 0))
            details.append({"folder_id": f.folder_id, "name": f.name, **res})

        return {"synced": total_synced, "folders": details}

    async def _ingest_fetched_message(
        self,
        account_id: str,
        organization_id: str,
        folder: MailFolderModel,
        item: FetchedEmailData,
        user_id: str,
        session,
    ) -> tuple[bool, list[tuple[str, dict]]]:
        events: list[tuple[str, dict]] = []

        # 1. Déduplication par (account, folder, uid_validity, uid)
        existing_uid = await self.message_repo.get_by_imap_uid(
            account_id, folder.folder_id, item.imap_uid_validity, item.imap_uid, session=session
        )
        if existing_uid is not None:
            existing_uid.is_read = bool(item.is_read)
            existing_uid.is_starred = bool(item.is_starred)
            return False, events

        # 2. Déduplication par rfc_message_id (ex. si UIDVALIDITY a changé)
        if item.rfc_message_id:
            existing_rfc = await self.message_repo.get_by_rfc_message_id(
                account_id, item.rfc_message_id, session=session
            )
            if existing_rfc is not None and existing_rfc.folder_id == folder.folder_id:
                existing_rfc.imap_uid = item.imap_uid
                existing_rfc.imap_uid_validity = item.imap_uid_validity
                existing_rfc.is_read = bool(item.is_read)
                existing_rfc.is_starred = bool(item.is_starred)
                return False, events

        msg_dt = self._parse_iso_dt(item.received_at or item.sent_at)
        snippet = SanitizerService.make_snippet(item.body_text, item.body_html)
        safe_html = (
            SanitizerService.sanitize_html(item.body_html, block_remote_images=True)
            if item.body_html
            else SanitizerService.text_to_safe_html(item.body_text)
        )

        participants = []
        if item.from_email:
            participants.append({"name": item.from_name, "email": item.from_email})
        participants.extend(item.to)

        thread = await self.thread_service.resolve_or_create_thread(
            account_id=account_id,
            organization_id=organization_id,
            subject=item.subject,
            in_reply_to=item.in_reply_to,
            references=item.references,
            snippet=snippet,
            participants=participants,
            message_dt=msg_dt,
            session=session,
        )

        message_id = str(uuid.uuid4())
        direction = "outbound" if folder.folder_type == "sent" else "inbound"
        msg = MailMessageModel(
            message_id=message_id,
            account_id=account_id,
            folder_id=folder.folder_id,
            thread_id=thread.thread_id,
            organization_id=organization_id,
            rfc_message_id=item.rfc_message_id,
            in_reply_to=item.in_reply_to,
            references_json=item.references,
            imap_uid=item.imap_uid,
            imap_uid_validity=item.imap_uid_validity,
            imap_mailbox=folder.remote_name,
            direction=direction,
            status="draft" if (folder.folder_type == "drafts" or item.is_draft) else "received",
            from_name=item.from_name[:255],
            from_email=item.from_email[:255],
            to_json=item.to,
            cc_json=item.cc,
            bcc_json=[],
            reply_to=item.reply_to,
            subject=(item.subject or "(Sans objet)")[:1000],
            snippet=snippet[:500],
            body_text=item.body_text,
            body_html_sanitized=safe_html,
            raw_headers_json=item.raw_headers,
            labels_json=[],
            is_read=bool(item.is_read),
            is_starred=bool(item.is_starred),
            is_important=False,
            is_draft=bool(folder.folder_type == "drafts" or item.is_draft),
            has_attachments=len(item.attachments) > 0,
            size_bytes=item.size_bytes,
            sent_at=self._parse_iso_dt(item.sent_at),
            received_at=msg_dt,
        )
        session.add(msg)
        await session.flush()

        # Enregistrement des pièces jointes dans melodi_media
        for att_raw in item.attachments:
            try:
                att_model = await self.attachment_service.store_attachment_bytes(
                    organization_id=organization_id,
                    message_id=message_id,
                    filename=att_raw.filename,
                    content=att_raw.content,
                    mime_type=att_raw.mime_type,
                    content_id=att_raw.content_id,
                    is_inline=att_raw.is_inline,
                    user_id=user_id,
                    session=session,
                )
                events.append(
                    (
                        "mail.attachment.received",
                        {
                            "attachment_id": att_model.attachment_id,
                            "message_id": message_id,
                            "media_id": att_model.media_id,
                            "filename": att_model.filename,
                            "mime_type": att_model.mime_type,
                            "size_bytes": att_model.size_bytes,
                        },
                    )
                )
            except Exception as exc:
                logger.warning("[melodi_mailbox] Pièce jointe ignorée (%s): %s", att_raw.filename, exc)

        await self.thread_service.refresh_thread_aggregates(thread.thread_id, session=session)

        if direction == "inbound":
            events.append(
                (
                    "mail.received",
                    {
                        "message_id": message_id,
                        "thread_id": thread.thread_id,
                        "account_id": account_id,
                        "organization_id": organization_id,
                        "from_email": msg.from_email,
                        "subject": msg.subject,
                        "has_attachments": msg.has_attachments,
                        "received_at": msg.received_at.isoformat(),
                    },
                )
            )
        return True, events
