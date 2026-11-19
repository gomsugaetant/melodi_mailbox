from __future__ import annotations

import asyncio
from email.utils import make_msgid
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from core.service import Service
from modules.melodi_mailbox.models.models import MailMessageModel
from modules.melodi_mailbox.providers.base import OutboundAttachmentData, OutboundEmailData
from modules.melodi_mailbox.repositories import (
    MailAccountRepository,
    MailFolderRepository,
    MailMessageRepository,
)
from modules.melodi_mailbox.services.mail_account_service import MailAccountError, MailAccountService
from modules.melodi_mailbox.services.mail_attachment_service import MailAttachmentService
from modules.melodi_mailbox.services.mail_connection_service import MailConnectionService
from modules.melodi_mailbox.services.mail_message_service import MailMessageService
from modules.melodi_mailbox.services.mail_thread_service import MailThreadService
from modules.melodi_mailbox.services.sanitizer_service import SanitizerService

logger = logging.getLogger("melodi_mailbox.send")


class MailSendService(Service):
    """
    Service de composition, brouillons auto-sauvegardés et envoi asynchrone SMTP
    avec gestion des erreurs et tentatives de renvoi via TaskManager.
    """

    MAX_SEND_RETRIES = 3

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
    def _normalize_recipients(raw: Any) -> list[dict[str, str]]:
        if not raw:
            return []
        if isinstance(raw, str):
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            return [{"name": "", "email": p.lower()} for p in parts]
        if isinstance(raw, list):
            out = []
            for item in raw:
                if isinstance(item, str) and item.strip():
                    out.append({"name": "", "email": item.strip().lower()})
                elif isinstance(item, dict) and item.get("email"):
                    out.append(
                        {"name": str(item.get("name") or "").strip(), "email": str(item["email"]).strip().lower()}
                    )
            return out
        return []

    async def save_draft(
        self,
        organization_id: str,
        user_id: str,
        payload: dict[str, Any],
        is_sudo: bool = False,
    ) -> dict[str, Any]:
        account_id = payload.get("account_id")
        if not account_id:
            raise MailAccountError("account_id est requis.", "VALIDATION_FAILED", 400)

        account = await self.account_repo.get_by_id(account_id, organization_id=organization_id)
        account = await self.account_service._assert_access(
            account, organization_id, user_id, is_sudo=is_sudo
        )

        draft_id = payload.get("message_id")
        to_list = self._normalize_recipients(payload.get("to"))
        cc_list = self._normalize_recipients(payload.get("cc"))
        bcc_list = self._normalize_recipients(payload.get("bcc"))
        subject = (payload.get("subject") or "").strip()
        body_text = payload.get("body_text") or ""
        body_html = payload.get("body_html") or ""
        safe_html = (
            SanitizerService.sanitize_html(body_html, block_remote_images=False)
            if body_html
            else SanitizerService.text_to_safe_html(body_text)
        )
        snippet = SanitizerService.make_snippet(body_text, body_html)

        async with self.message_repo.get_session() as session:
            drafts_folder = await self.folder_repo.get_by_type(account_id, "drafts", session=session)
            msg: Optional[MailMessageModel] = None
            if draft_id:
                msg = await self.message_repo.get_message_by_id(
                    draft_id, organization_id=organization_id, session=session
                )

            now = datetime.utcnow()
            if msg is None:
                in_reply_to = payload.get("in_reply_to")
                references = list(payload.get("references") or [])
                thread = await self.thread_service.resolve_or_create_thread(
                    account_id=account_id,
                    organization_id=organization_id,
                    subject=subject or "(Brouillon)",
                    in_reply_to=in_reply_to,
                    references=references,
                    snippet=snippet,
                    participants=[{"name": account.sender_name or account.name, "email": account.email_address}, *to_list],
                    message_dt=now,
                    session=session,
                )
                msg = MailMessageModel(
                    message_id=str(uuid.uuid4()),
                    account_id=account_id,
                    folder_id=drafts_folder.folder_id if drafts_folder else None,
                    thread_id=thread.thread_id,
                    organization_id=organization_id,
                    in_reply_to=in_reply_to,
                    references_json=references,
                    direction="outbound",
                    status="draft",
                    from_name=account.sender_name or account.name,
                    from_email=account.email_address,
                    to_json=to_list,
                    cc_json=cc_list,
                    bcc_json=bcc_list,
                    subject=subject[:1000],
                    snippet=snippet[:500],
                    body_text=body_text,
                    body_html_sanitized=safe_html,
                    is_read=True,
                    is_draft=True,
                    received_at=now,
                )
                session.add(msg)
            else:
                msg.to_json = to_list
                msg.cc_json = cc_list
                msg.bcc_json = bcc_list
                msg.subject = subject[:1000]
                msg.snippet = snippet[:500]
                msg.body_text = body_text
                msg.body_html_sanitized = safe_html
                msg.updated_at = now

            await session.flush()
            if msg.thread_id:
                await self.thread_service.refresh_thread_aggregates(msg.thread_id, session=session)
            if drafts_folder:
                await self.folder_repo.refresh_folder_counts(drafts_folder.folder_id, session=session)
            await session.commit()

            atts = await self.message_repo.list_attachments_for_messages([msg.message_id])
            att_dtos = await self.attachment_service.resolve_attachments_dtos(atts)
            return MailMessageService.message_to_dict(msg, att_dtos)

    async def queue_send(
        self,
        organization_id: str,
        user_id: str,
        payload: dict[str, Any],
        is_sudo: bool = False,
        dispatch_async: bool = True,
    ) -> dict[str, Any]:
        # 1. Créer ou mettre à jour le message comme brouillon prêt à partir
        draft_dict = await self.save_draft(organization_id, user_id, payload, is_sudo=is_sudo)
        message_id = draft_dict["message_id"]

        if not draft_dict.get("to") and not draft_dict.get("cc") and not draft_dict.get("bcc"):
            raise MailAccountError("Au moins un destinataire est requis.", "VALIDATION_FAILED", 400)

        async with self.message_repo.get_session() as session:
            msg = await self.message_repo.get_message_by_id(
                message_id, organization_id=organization_id, session=session
            )
            msg.status = "queued"
            msg.send_error = None
            await session.commit()

        # 2. Exécution asynchrone via TaskManager (ou en arrière-plan asyncio si task_manager absent)
        if dispatch_async and self.app and hasattr(self.app, "task_manager"):
            try:
                task_id = await self.app.task_manager.dispatch(
                    "melodi_mailbox.send_message",
                    message_id=message_id,
                    organization_id=organization_id,
                )
                return {**draft_dict, "status": "queued", "task_id": task_id}
            except Exception as exc:
                logger.warning("[melodi_mailbox] Fallback envoi direct suite erreur TaskManager: %s", exc)

        if dispatch_async:
            asyncio.create_task(self.execute_send_now(message_id, organization_id))
            return {**draft_dict, "status": "queued"}

        return await self.execute_send_now(message_id, organization_id)

    async def execute_send_now(self, message_id: str, organization_id: str) -> dict[str, Any]:
        msg = await self.message_repo.get_message_by_id(message_id, organization_id=organization_id)
        if not msg:
            raise MailAccountError("Message introuvable pour envoi.", "NOT_FOUND", 404)

        account = await self.account_repo.get_by_id(msg.account_id, organization_id=organization_id)
        if not account:
            raise MailAccountError("Compte expéditeur introuvable.", "NOT_FOUND", 404)

        atts = await self.message_repo.list_attachments_for_messages([message_id])
        outbound_atts: list[OutboundAttachmentData] = []
        for att in atts:
            raw_bytes, fname, mime = await self.attachment_service.read_attachment_bytes(att)
            outbound_atts.append(
                OutboundAttachmentData(
                    filename=fname,
                    mime_type=mime,
                    content=raw_bytes,
                    content_id=att.content_id,
                    is_inline=bool(att.is_inline),
                )
            )

        rfc_id = msg.rfc_message_id or make_msgid(domain=account.email_address.split("@")[-1])
        outbound = OutboundEmailData(
            from_name=msg.from_name or account.sender_name or account.name,
            from_email=account.email_address,
            to=[r["email"] for r in (msg.to_json or []) if r.get("email")],
            cc=[r["email"] for r in (msg.cc_json or []) if r.get("email")],
            bcc=[r["email"] for r in (msg.bcc_json or []) if r.get("email")],
            reply_to=msg.reply_to,
            subject=msg.subject,
            body_text=msg.body_text,
            body_html=msg.body_html_sanitized,
            in_reply_to=msg.in_reply_to,
            references=list(msg.references_json or []),
            rfc_message_id=rfc_id,
            attachments=outbound_atts,
        )

        sent_folder = await self.folder_repo.get_by_type(account.account_id, "sent")
        creds = self.account_service.build_credentials(account)
        provider = self.connection_service.build_provider(creds)

        last_err: Optional[Exception] = None
        for attempt in range(1, self.MAX_SEND_RETRIES + 1):
            try:
                sent_rfc_id = await provider.send_message(
                    outbound,
                    sent_mailbox=sent_folder.remote_name if sent_folder else None,
                )
                async with self.message_repo.get_session() as session:
                    db_msg = await self.message_repo.get_message_by_id(
                        message_id, organization_id=organization_id, session=session
                    )
                    old_folder_id = db_msg.folder_id
                    db_msg.status = "sent"
                    db_msg.is_draft = False
                    db_msg.is_read = True
                    db_msg.rfc_message_id = sent_rfc_id
                    db_msg.sent_at = datetime.utcnow()
                    db_msg.send_error = None
                    if sent_folder:
                        db_msg.folder_id = sent_folder.folder_id
                        db_msg.imap_mailbox = sent_folder.remote_name
                    await session.flush()
                    if old_folder_id:
                        await self.folder_repo.refresh_folder_counts(old_folder_id, session=session)
                    if sent_folder:
                        await self.folder_repo.refresh_folder_counts(sent_folder.folder_id, session=session)
                    if db_msg.thread_id:
                        await self.thread_service.refresh_thread_aggregates(db_msg.thread_id, session=session)
                    await session.commit()

                if hasattr(self.module, "notify_event_listener"):
                    await self.module.notify_event_listener(
                        "mail.sent",
                        {
                            "message_id": message_id,
                            "thread_id": msg.thread_id,
                            "account_id": account.account_id,
                            "to": outbound.to,
                            "subject": outbound.subject,
                            "sent_at": datetime.utcnow().isoformat(),
                        },
                    )
                return MailMessageService.message_to_dict(db_msg)
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "[melodi_mailbox] Échec envoi SMTP (tentative %s/%s) msg=%s: %s",
                    attempt,
                    self.MAX_SEND_RETRIES,
                    message_id,
                    exc,
                )

        async with self.message_repo.get_session() as session:
            db_msg = await self.message_repo.get_message_by_id(
                message_id, organization_id=organization_id, session=session
            )
            db_msg.status = "failed"
            db_msg.send_retries = (db_msg.send_retries or 0) + self.MAX_SEND_RETRIES
            db_msg.send_error = str(last_err)
            await session.commit()

        if hasattr(self.module, "notify_event_listener"):
            await self.module.notify_event_listener(
                "mail.failed",
                {
                    "message_id": message_id,
                    "account_id": account.account_id,
                    "error": str(last_err),
                    "retries": self.MAX_SEND_RETRIES,
                },
            )
        raise MailAccountError(f"Échec de l'envoi SMTP : {last_err}", "SMTP_SEND_FAILED", 502)
