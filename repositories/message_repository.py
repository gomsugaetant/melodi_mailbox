from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import delete as sqla_delete
from sqlalchemy import or_, update as sqla_update

from core.db import Repository
from core.orm import func, select
from modules.melodi_mailbox.models.models import (
    MailAttachmentModel,
    MailMessageModel,
    MailThreadModel,
)


class MailMessageRepository(Repository):
    """Accès aux données pour les fils de discussion, messages et pièces jointes."""

    async def get_message_by_id(
        self,
        message_id: str,
        organization_id: Optional[str] = None,
        session=None,
    ) -> Optional[MailMessageModel]:
        async def _run(s):
            stmt = select(MailMessageModel).where(MailMessageModel.message_id == message_id)
            if organization_id is not None:
                stmt = stmt.where(MailMessageModel.organization_id == organization_id)
            res = await s.execute(stmt)
            return res.scalar_one_or_none()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def get_by_imap_uid(
        self,
        account_id: str,
        folder_id: str,
        imap_uid_validity: int,
        imap_uid: int,
        session=None,
    ) -> Optional[MailMessageModel]:
        async def _run(s):
            stmt = select(MailMessageModel).where(
                MailMessageModel.account_id == account_id,
                MailMessageModel.folder_id == folder_id,
                MailMessageModel.imap_uid_validity == imap_uid_validity,
                MailMessageModel.imap_uid == imap_uid,
            )
            res = await s.execute(stmt)
            return res.scalar_one_or_none()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def get_by_rfc_message_id(
        self,
        account_id: str,
        rfc_message_id: str,
        session=None,
    ) -> Optional[MailMessageModel]:
        async def _run(s):
            stmt = select(MailMessageModel).where(
                MailMessageModel.account_id == account_id,
                MailMessageModel.rfc_message_id == rfc_message_id,
            )
            res = await s.execute(stmt)
            return res.scalars().first()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def find_thread_by_rfc_ids(
        self,
        account_id: str,
        rfc_ids: list[str],
        session=None,
    ) -> Optional[str]:
        cleaned = [r.strip() for r in rfc_ids if r and r.strip()]
        if not cleaned:
            return None

        async def _run(s):
            stmt = (
                select(MailMessageModel.thread_id)
                .where(
                    MailMessageModel.account_id == account_id,
                    MailMessageModel.rfc_message_id.in_(cleaned),
                    MailMessageModel.thread_id.is_not(None),
                )
                .order_by(MailMessageModel.received_at.desc())
            )
            res = await s.execute(stmt)
            return res.scalars().first()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def find_recent_thread_by_subject(
        self,
        account_id: str,
        subject_normalized: str,
        since_dt: datetime,
        session=None,
    ) -> Optional[MailThreadModel]:
        if not subject_normalized:
            return None

        async def _run(s):
            stmt = (
                select(MailThreadModel)
                .where(
                    MailThreadModel.account_id == account_id,
                    MailThreadModel.subject_normalized == subject_normalized,
                    MailThreadModel.last_message_at >= since_dt,
                )
                .order_by(MailThreadModel.last_message_at.desc())
            )
            res = await s.execute(stmt)
            return res.scalars().first()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def get_thread_by_id(
        self,
        thread_id: str,
        organization_id: Optional[str] = None,
        session=None,
    ) -> Optional[MailThreadModel]:
        async def _run(s):
            stmt = select(MailThreadModel).where(MailThreadModel.thread_id == thread_id)
            if organization_id is not None:
                stmt = stmt.where(MailThreadModel.organization_id == organization_id)
            res = await s.execute(stmt)
            return res.scalar_one_or_none()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def list_messages_in_thread(
        self,
        thread_id: str,
        session=None,
    ) -> list[MailMessageModel]:
        async def _run(s):
            stmt = (
                select(MailMessageModel)
                .where(MailMessageModel.thread_id == thread_id)
                .order_by(MailMessageModel.received_at.asc(), MailMessageModel.created_at.asc())
            )
            res = await s.execute(stmt)
            return list(res.scalars().all())

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def list_threads_paginated(
        self,
        account_id: str,
        folder_id: Optional[str] = None,
        starred_only: bool = False,
        unread_only: bool = False,
        has_attachments_only: bool = False,
        search: Optional[str] = None,
        page: int = 1,
        per_page: int = 30,
        session=None,
    ) -> tuple[list[dict], int]:
        """
        Retourne les fils de discussion contenant au moins un message correspondant aux filtres,
        avec le dernier message représentatif de ce dossier pour l'affichage liste.
        """
        async def _run(s):
            msg_filter = [MailMessageModel.account_id == account_id]
            if folder_id:
                msg_filter.append(MailMessageModel.folder_id == folder_id)
            if starred_only:
                msg_filter.append(MailMessageModel.is_starred.is_(True))
            if unread_only:
                msg_filter.append(MailMessageModel.is_read.is_(False))
            if has_attachments_only:
                msg_filter.append(MailMessageModel.has_attachments.is_(True))
            if search and search.strip():
                term = f"%{search.strip()}%"
                msg_filter.append(
                    or_(
                        MailMessageModel.subject.ilike(term),
                        MailMessageModel.snippet.ilike(term),
                        MailMessageModel.from_email.ilike(term),
                        MailMessageModel.from_name.ilike(term),
                    )
                )

            matching_threads_subq = (
                select(MailMessageModel.thread_id)
                .where(*msg_filter, MailMessageModel.thread_id.is_not(None))
                .distinct()
                .scalar_subquery()
            )

            base_stmt = select(MailThreadModel).where(
                MailThreadModel.thread_id.in_(matching_threads_subq)
            )
            count_stmt = select(func.count()).select_from(base_stmt.subquery())
            total = int((await s.execute(count_stmt)).scalar() or 0)

            offset = max(page - 1, 0) * per_page
            threads_stmt = (
                base_stmt.order_by(MailThreadModel.last_message_at.desc())
                .limit(per_page)
                .offset(offset)
            )
            threads = list((await s.execute(threads_stmt)).scalars().all())
            if not threads:
                return [], total

            thread_ids = [t.thread_id for t in threads]
            msgs_stmt = (
                select(MailMessageModel)
                .where(
                    MailMessageModel.thread_id.in_(thread_ids),
                    *( [MailMessageModel.folder_id == folder_id] if folder_id else [] ),
                )
                .order_by(MailMessageModel.received_at.desc())
            )
            msgs = list((await s.execute(msgs_stmt)).scalars().all())
            by_thread: dict[str, list[MailMessageModel]] = {}
            for m in msgs:
                if m.thread_id:
                    by_thread.setdefault(m.thread_id, []).append(m)

            items = []
            for th in threads:
                t_msgs = by_thread.get(th.thread_id, [])
                latest = t_msgs[0] if t_msgs else None
                items.append(
                    {
                        "thread": th,
                        "latest_message": latest,
                        "folder_unread_count": sum(1 for m in t_msgs if not m.is_read),
                        "folder_message_count": len(t_msgs),
                    }
                )
            return items, total

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def list_attachments_for_messages(
        self, message_ids: list[str], session=None
    ) -> list[MailAttachmentModel]:
        if not message_ids:
            return []

        async def _run(s):
            stmt = (
                select(MailAttachmentModel)
                .where(MailAttachmentModel.message_id.in_(message_ids))
                .order_by(MailAttachmentModel.created_at.asc())
            )
            res = await s.execute(stmt)
            return list(res.scalars().all())

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def get_attachment_by_id(
        self, attachment_id: str, organization_id: Optional[str] = None, session=None
    ) -> Optional[MailAttachmentModel]:
        async def _run(s):
            stmt = select(MailAttachmentModel).where(MailAttachmentModel.attachment_id == attachment_id)
            if organization_id is not None:
                stmt = stmt.where(MailAttachmentModel.organization_id == organization_id)
            res = await s.execute(stmt)
            return res.scalar_one_or_none()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def find_attachment_by_sha256(
        self, organization_id: str, sha256_hash: str, session=None
    ) -> Optional[MailAttachmentModel]:
        async def _run(s):
            stmt = select(MailAttachmentModel).where(
                MailAttachmentModel.organization_id == organization_id,
                MailAttachmentModel.sha256_hash == sha256_hash,
            )
            res = await s.execute(stmt)
            return res.scalars().first()

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            return await _run(s)

    async def delete_message_by_id(self, message_id: str, session=None) -> bool:
        async def _run(s):
            stmt = sqla_delete(MailMessageModel).where(MailMessageModel.message_id == message_id)
            res = await s.execute(stmt)
            return (res.rowcount or 0) > 0

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            deleted = await _run(s)
            await s.commit()
            return deleted

    async def update_messages_fields(
        self, message_ids: list[str], values: dict, session=None
    ) -> int:
        if not message_ids:
            return 0
        payload = {**values, "updated_at": datetime.utcnow()}

        async def _run(s):
            stmt = (
                sqla_update(MailMessageModel)
                .where(MailMessageModel.message_id.in_(message_ids))
                .values(**payload)
            )
            res = await s.execute(stmt)
            return int(res.rowcount or 0)

        if session is not None:
            return await _run(session)
        async with self.get_session() as s:
            cnt = await _run(s)
            await s.commit()
            return cnt
