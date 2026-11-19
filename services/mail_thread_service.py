from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Optional

from core.service import Service
from modules.melodi_mailbox.models.models import MailMessageModel, MailThreadModel
from modules.melodi_mailbox.repositories.message_repository import MailMessageRepository

_SUBJECT_PREFIX_RE = re.compile(r"^\s*((re|fwd?|tr|aw|sv|r)\s*(\[\d+\])?\s*:\s*)+", re.IGNORECASE)


class MailThreadService(Service):
    """Regroupement des messages en fils de discussion (RFC 5322 + sujet normalisé)."""

    def __init__(self, module, message_repo: Optional[MailMessageRepository] = None):
        super().__init__(module)
        self.message_repo = message_repo or MailMessageRepository(module)

    @staticmethod
    def normalize_subject(subject: str) -> str:
        cleaned = _SUBJECT_PREFIX_RE.sub("", (subject or "").strip())
        return re.sub(r"\s+", " ", cleaned).strip().lower()[:450]

    async def resolve_or_create_thread(
        self,
        account_id: str,
        organization_id: str,
        subject: str,
        in_reply_to: Optional[str],
        references: list[str],
        snippet: str,
        participants: list[dict[str, str]],
        message_dt: datetime,
        session,
    ) -> MailThreadModel:
        candidate_rfc_ids = []
        if in_reply_to:
            candidate_rfc_ids.append(in_reply_to)
        if references:
            candidate_rfc_ids.extend(references)

        thread_id: Optional[str] = None
        if candidate_rfc_ids:
            thread_id = await self.message_repo.find_thread_by_rfc_ids(
                account_id, candidate_rfc_ids, session=session
            )

        norm_subject = self.normalize_subject(subject)
        thread: Optional[MailThreadModel] = None

        if thread_id:
            thread = await self.message_repo.get_thread_by_id(thread_id, session=session)
        elif norm_subject:
            # Repli par sujet normalisé dans une fenêtre de 30 jours
            since_dt = message_dt - timedelta(days=30)
            thread = await self.message_repo.find_recent_thread_by_subject(
                account_id, norm_subject, since_dt, session=session
            )

        if thread is None:
            thread = MailThreadModel(
                thread_id=str(uuid.uuid4()),
                account_id=account_id,
                organization_id=organization_id,
                subject_normalized=norm_subject or (subject or "(Sans objet)")[:450],
                snippet=snippet[:500],
                participants_json=participants,
                message_count=0,
                unread_count=0,
                has_attachments=False,
                is_starred=False,
                last_message_at=message_dt,
            )
            session.add(thread)
            await session.flush()

        return thread

    async def refresh_thread_aggregates(self, thread_id: str, session) -> None:
        thread = await self.message_repo.get_thread_by_id(thread_id, session=session)
        if not thread:
            return
        msgs = await self.message_repo.list_messages_in_thread(thread_id, session=session)
        if not msgs:
            thread.message_count = 0
            thread.unread_count = 0
            return

        participants_map: dict[str, dict[str, str]] = {}
        for m in msgs:
            if m.from_email:
                participants_map[m.from_email] = {"name": m.from_name or "", "email": m.from_email}
            for recipient in (m.to_json or []):
                em = (recipient.get("email") or "").lower()
                if em and em not in participants_map:
                    participants_map[em] = {"name": recipient.get("name") or "", "email": em}

        latest = msgs[-1]
        thread.message_count = len(msgs)
        thread.unread_count = sum(1 for m in msgs if not m.is_read)
        thread.has_attachments = any(bool(m.has_attachments) for m in msgs)
        thread.is_starred = any(bool(m.is_starred) for m in msgs)
        thread.snippet = (latest.snippet or "")[:500]
        thread.participants_json = list(participants_map.values())[:20]
        thread.last_message_at = max((m.received_at for m in msgs if m.received_at), default=datetime.utcnow())
        thread.updated_at = datetime.utcnow()
        await session.flush()
