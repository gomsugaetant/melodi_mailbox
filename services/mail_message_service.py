from __future__ import annotations

import logging
from typing import Any, Optional

from core.service import Service
from modules.melodi_mailbox.models.models import MailMessageModel, MailThreadModel
from modules.melodi_mailbox.repositories import (
    MailAccountRepository,
    MailFolderRepository,
    MailMessageRepository,
)
from modules.melodi_mailbox.services.mail_account_service import MailAccountError, MailAccountService
from modules.melodi_mailbox.services.mail_attachment_service import MailAttachmentService
from modules.melodi_mailbox.services.mail_connection_service import MailConnectionService
from modules.melodi_mailbox.services.mail_thread_service import MailThreadService

logger = logging.getLogger("melodi_mailbox.messages")


class MailMessageService(Service):
    """Consultation des fils de discussion, lecture des messages et actions (lu, favori, déplacer, supprimer)."""

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

    @staticmethod
    def message_to_dict(
        msg: MailMessageModel,
        attachments: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        return {
            "message_id": msg.message_id,
            "account_id": msg.account_id,
            "folder_id": msg.folder_id,
            "thread_id": msg.thread_id,
            "rfc_message_id": msg.rfc_message_id,
            "in_reply_to": msg.in_reply_to,
            "references": msg.references_json or [],
            "direction": msg.direction,
            "status": msg.status,
            "from_name": msg.from_name,
            "from_email": msg.from_email,
            "to": msg.to_json or [],
            "cc": msg.cc_json or [],
            "bcc": msg.bcc_json or [],
            "reply_to": msg.reply_to,
            "subject": msg.subject,
            "snippet": msg.snippet,
            "body_text": msg.body_text,
            "body_html": msg.body_html_sanitized,
            "is_read": bool(msg.is_read),
            "is_starred": bool(msg.is_starred),
            "is_important": bool(msg.is_important),
            "is_draft": bool(msg.is_draft),
            "has_attachments": bool(msg.has_attachments),
            "size_bytes": msg.size_bytes,
            "send_error": msg.send_error,
            "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
            "received_at": msg.received_at.isoformat() if msg.received_at else None,
            "attachments": attachments if attachments is not None else [],
        }

    @staticmethod
    def thread_summary_to_dict(
        th: MailThreadModel,
        latest: Optional[MailMessageModel],
        folder_unread_count: int = 0,
        folder_message_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "thread_id": th.thread_id,
            "account_id": th.account_id,
            "subject": (latest.subject if latest else th.subject_normalized) or "(Sans objet)",
            "snippet": (latest.snippet if latest else th.snippet) or "",
            "participants": th.participants_json or [],
            "message_count": folder_message_count or th.message_count,
            "unread_count": folder_unread_count,
            "has_attachments": bool(th.has_attachments or (latest.has_attachments if latest else False)),
            "is_starred": bool(th.is_starred or (latest.is_starred if latest else False)),
            "last_message_at": (
                latest.received_at.isoformat()
                if latest and latest.received_at
                else th.last_message_at.isoformat()
            ),
            "latest_message_id": latest.message_id if latest else None,
            "latest_from_name": latest.from_name if latest else "",
            "latest_from_email": latest.from_email if latest else "",
            "latest_is_draft": bool(latest.is_draft) if latest else False,
            "latest_status": latest.status if latest else "received",
        }

    async def list_threads(
        self,
        account_id: str,
        organization_id: str,
        user_id: str,
        is_sudo: bool = False,
        folder_id: Optional[str] = None,
        starred_only: bool = False,
        unread_only: bool = False,
        has_attachments_only: bool = False,
        search: Optional[str] = None,
        page: int = 1,
        per_page: int = 30,
    ) -> dict[str, Any]:
        account = await self.account_repo.get_by_id(account_id, organization_id=organization_id)
        await self.account_service._assert_access(account, organization_id, user_id, is_sudo=is_sudo)

        rows, total = await self.message_repo.list_threads_paginated(
            account_id=account_id,
            folder_id=folder_id,
            starred_only=starred_only,
            unread_only=unread_only,
            has_attachments_only=has_attachments_only,
            search=search,
            page=page,
            per_page=per_page,
        )
        items = [
            self.thread_summary_to_dict(
                r["thread"],
                r["latest_message"],
                folder_unread_count=r["folder_unread_count"],
                folder_message_count=r["folder_message_count"],
            )
            for r in rows
        ]
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    async def get_thread_detail(
        self,
        thread_id: str,
        organization_id: str,
        user_id: str,
        is_sudo: bool = False,
    ) -> dict[str, Any]:
        thread = await self.message_repo.get_thread_by_id(thread_id, organization_id=organization_id)
        if not thread:
            raise MailAccountError("Conversation introuvable.", "NOT_FOUND", 404)

        account = await self.account_repo.get_by_id(thread.account_id, organization_id=organization_id)
        await self.account_service._assert_access(account, organization_id, user_id, is_sudo=is_sudo)

        messages = await self.message_repo.list_messages_in_thread(thread_id)
        msg_ids = [m.message_id for m in messages]
        atts = await self.message_repo.list_attachments_for_messages(msg_ids)
        att_dtos = await self.attachment_service.resolve_attachments_dtos(atts)

        atts_by_msg: dict[str, list[dict]] = {}
        for a in att_dtos:
            atts_by_msg.setdefault(a["message_id"], []).append(a)

        return {
            "thread_id": thread.thread_id,
            "account_id": thread.account_id,
            "subject": messages[-1].subject if messages else thread.subject_normalized,
            "participants": thread.participants_json or [],
            "message_count": len(messages),
            "messages": [
                self.message_to_dict(m, atts_by_msg.get(m.message_id, [])) for m in messages
            ],
        }

    async def set_flags(
        self,
        message_ids: list[str],
        organization_id: str,
        user_id: str,
        is_sudo: bool = False,
        is_read: Optional[bool] = None,
        is_starred: Optional[bool] = None,
    ) -> int:
        if not message_ids:
            return 0

        updates: dict[str, Any] = {}
        if is_read is not None:
            updates["is_read"] = bool(is_read)
        if is_starred is not None:
            updates["is_starred"] = bool(is_starred)
        if not updates:
            return 0

        affected_folders: set[str] = set()
        affected_threads: set[str] = set()
        remote_ops: list[tuple[str, str, int]] = []

        async with self.message_repo.get_session() as session:
            authorized_ids: list[str] = []
            for mid in message_ids:
                msg = await self.message_repo.get_message_by_id(
                    mid, organization_id=organization_id, session=session
                )
                if not msg:
                    continue
                acct = await self.account_repo.get_by_id(
                    msg.account_id, organization_id=organization_id, session=session
                )
                await self.account_service._assert_access(
                    acct, organization_id, user_id, is_sudo=is_sudo, session=session
                )
                authorized_ids.append(mid)
                if msg.folder_id:
                    affected_folders.add(msg.folder_id)
                if msg.thread_id:
                    affected_threads.add(msg.thread_id)
                if msg.imap_uid and msg.imap_mailbox:
                    remote_ops.append((msg.account_id, msg.imap_mailbox, msg.imap_uid))

            count = await self.message_repo.update_messages_fields(
                authorized_ids, updates, session=session
            )
            for fid in affected_folders:
                await self.folder_repo.refresh_folder_counts(fid, session=session)
            for tid in affected_threads:
                await self.thread_service.refresh_thread_aggregates(tid, session=session)
            await session.commit()

        # Répercussion IMAP best-effort
        for acct_id, mailbox, uid in remote_ops:
            try:
                acct = await self.account_repo.get_by_id(acct_id, organization_id=organization_id)
                if not acct:
                    continue
                provider = self.connection_service.build_provider(
                    self.account_service.build_credentials(acct)
                )
                if is_read is not None:
                    await provider.set_message_flags(mailbox, uid, ["\\Seen"], add=bool(is_read))
                if is_starred is not None:
                    await provider.set_message_flags(mailbox, uid, ["\\Flagged"], add=bool(is_starred))
            except Exception as exc:
                logger.warning("[melodi_mailbox] Sync flag IMAP ignorée (uid=%s): %s", uid, exc)

        return count

    async def move_messages(
        self,
        message_ids: list[str],
        organization_id: str,
        user_id: str,
        target_folder_id: Optional[str] = None,
        target_folder_type: Optional[str] = None,
        is_sudo: bool = False,
    ) -> int:
        if not message_ids:
            return 0

        moved = 0
        affected_folders: set[str] = set()
        remote_moves: list[tuple[str, str, int, str]] = []

        async with self.message_repo.get_session() as session:
            for mid in message_ids:
                msg = await self.message_repo.get_message_by_id(
                    mid, organization_id=organization_id, session=session
                )
                if not msg:
                    continue
                acct = await self.account_repo.get_by_id(
                    msg.account_id, organization_id=organization_id, session=session
                )
                await self.account_service._assert_access(
                    acct, organization_id, user_id, is_sudo=is_sudo, session=session
                )

                dest_folder = None
                if target_folder_id:
                    dest_folder = await self.folder_repo.get_by_id(target_folder_id, session=session)
                elif target_folder_type:
                    dest_folder = await self.folder_repo.get_by_type(
                        msg.account_id, target_folder_type, session=session
                    )
                if not dest_folder or dest_folder.account_id != msg.account_id:
                    continue

                if msg.folder_id:
                    affected_folders.add(msg.folder_id)
                affected_folders.add(dest_folder.folder_id)

                if msg.imap_uid and msg.imap_mailbox and msg.imap_mailbox != dest_folder.remote_name:
                    remote_moves.append((msg.account_id, msg.imap_mailbox, msg.imap_uid, dest_folder.remote_name))

                msg.folder_id = dest_folder.folder_id
                msg.imap_mailbox = dest_folder.remote_name
                moved += 1

            await session.flush()
            for fid in affected_folders:
                await self.folder_repo.refresh_folder_counts(fid, session=session)
            await session.commit()

        for acct_id, src_box, uid, dst_box in remote_moves:
            try:
                acct = await self.account_repo.get_by_id(acct_id, organization_id=organization_id)
                if acct:
                    provider = self.connection_service.build_provider(
                        self.account_service.build_credentials(acct)
                    )
                    await provider.move_message(src_box, uid, dst_box)
            except Exception as exc:
                logger.warning("[melodi_mailbox] Déplacement IMAP ignoré (uid=%s): %s", uid, exc)

        return moved

    async def delete_messages_permanently(
        self,
        message_ids: list[str],
        organization_id: str,
        user_id: str,
        is_sudo: bool = False,
    ) -> int:
        """
        Suppression définitive avec exécution obligatoire du filtre transactionnel
        `mail.message.before_delete` (règle §3.1 AGENTS.md).
        """
        if not message_ids:
            return 0

        deleted_count = 0
        affected_folders: set[str] = set()
        affected_threads: set[str] = set()

        async with self.message_repo.get_session() as session:
            for mid in message_ids:
                msg = await self.message_repo.get_message_by_id(
                    mid, organization_id=organization_id, session=session
                )
                if not msg:
                    continue
                acct = await self.account_repo.get_by_id(
                    msg.account_id, organization_id=organization_id, session=session
                )
                await self.account_service._assert_access(
                    acct, organization_id, user_id, is_sudo=is_sudo, session=session
                )

                filter_payload = {
                    "entity": msg,
                    "entity_id": mid,
                    "organization_id": organization_id,
                    "session": session,
                    "allowed": True,
                    "reason": None,
                }
                if hasattr(self.module, "execute_filter"):
                    filter_payload = await self.module.execute_filter(
                        "mail.message.before_delete", filter_payload
                    )
                    if isinstance(filter_payload, dict) and not filter_payload.get("allowed", True):
                        await session.rollback()
                        raise MailAccountError(
                            filter_payload.get("reason") or "Suppression bloquée par un module dépendant.",
                            "DELETE_VETOED",
                            409,
                        )

                if msg.folder_id:
                    affected_folders.add(msg.folder_id)
                if msg.thread_id:
                    affected_threads.add(msg.thread_id)

                if await self.message_repo.delete_message_by_id(mid, session=session):
                    deleted_count += 1

            for fid in affected_folders:
                await self.folder_repo.refresh_folder_counts(fid, session=session)
            for tid in affected_threads:
                await self.thread_service.refresh_thread_aggregates(tid, session=session)
            await session.commit()

        return deleted_count
