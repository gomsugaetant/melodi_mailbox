from __future__ import annotations

import hashlib
import io
import mimetypes
import os
import uuid
from typing import Any, Optional

from core.service import Service
from modules.melodi_mailbox.config import MailConfig
from modules.melodi_mailbox.models.models import MailAttachmentModel
from modules.melodi_mailbox.repositories.message_repository import MailMessageRepository


class _MemoryUploadFile:
    """Adaptateur léger compatible avec Storage.save / MediaService.upload_media."""

    def __init__(self, filename: str, content: bytes, content_type: str):
        self.filename = filename
        self.name = filename
        self.content_type = content_type
        self._buf = io.BytesIO(content)

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._buf.seek(offset, whence)


class MailAttachmentError(Exception):
    def __init__(self, message: str, code: str = "ATTACHMENT_ERROR", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class MailAttachmentService(Service):
    """
    Gestion sécurisée des pièces jointes via melodi_media (media_id + MediaResolver) :
    - Contrôle strict des extensions interdites et de la taille max.
    - Déduplication par empreinte SHA-256 au sein de l'organisation.
    - Stockage exclusif via HookManager -> melodi_media.upload_media (zéro URL brute en BDD).
    """

    def __init__(self, module, message_repo: Optional[MailMessageRepository] = None):
        super().__init__(module)
        self.message_repo = message_repo or MailMessageRepository(module)

    @staticmethod
    def validate_attachment(filename: str, size_bytes: int, mime_type: Optional[str] = None) -> str:
        clean_name = os.path.basename((filename or "piece_jointe").strip()) or "piece_jointe"
        _, ext = os.path.splitext(clean_name.lower())
        if ext in MailConfig.BLOCKED_ATTACHMENT_EXTENSIONS:
            raise MailAttachmentError(
                f"Type de fichier interdit pour des raisons de sécurité ({ext}).",
                "BLOCKED_ATTACHMENT_TYPE",
                400,
            )
        if size_bytes > MailConfig.MAX_ATTACHMENT_SIZE_BYTES:
            max_mb = MailConfig.MAX_ATTACHMENT_SIZE_BYTES // (1024 * 1024)
            raise MailAttachmentError(
                f"La pièce jointe '{clean_name}' dépasse la taille maximale autorisée ({max_mb} Mo).",
                "ATTACHMENT_TOO_LARGE",
                400,
            )
        guessed = mime_type or mimetypes.guess_type(clean_name)[0] or "application/octet-stream"
        return guessed.lower()

    async def store_attachment_bytes(
        self,
        organization_id: str,
        message_id: str,
        filename: str,
        content: bytes,
        mime_type: Optional[str] = None,
        content_id: Optional[str] = None,
        is_inline: bool = False,
        user_id: Optional[str] = None,
        session=None,
    ) -> MailAttachmentModel:
        safe_mime = self.validate_attachment(filename, len(content), mime_type)
        sha256_hash = hashlib.sha256(content).hexdigest()

        # Déduplication par organisation : réutiliser le media_id si déjà présent
        existing = await self.message_repo.find_attachment_by_sha256(
            organization_id, sha256_hash, session=session
        )
        media_id: Optional[str] = existing.media_id if existing else None

        if not media_id:
            if not self.app or not hasattr(self.app, "hook_manager"):
                raise MailAttachmentError("Système de hooks média indisponible.", "MEDIA_UNAVAILABLE", 500)

            mem_file = _MemoryUploadFile(filename=filename, content=content, content_type=safe_mime)
            uploaded = await self.app.hook_manager.action.execute(
                "melodi_media",
                "upload_media",
                {
                    "file": mem_file,
                    "title": filename,
                    "module_name": "melodi_mailbox",
                    "entity_type": "mail_message",
                    "entity_id": message_id,
                    "user_id": user_id,
                },
            )
            if not uploaded or not isinstance(uploaded, dict) or not uploaded.get("media_id"):
                raise MailAttachmentError(
                    "Échec de l'enregistrement de la pièce jointe dans melodi_media.",
                    "MEDIA_UPLOAD_FAILED",
                    500,
                )
            media_id = str(uploaded["media_id"])

        att = MailAttachmentModel(
            attachment_id=str(uuid.uuid4()),
            message_id=message_id,
            organization_id=organization_id,
            media_id=media_id,
            filename=os.path.basename(filename) or "piece_jointe",
            mime_type=safe_mime,
            size_bytes=len(content),
            sha256_hash=sha256_hash,
            content_id=content_id,
            is_inline=is_inline,
        )
        if session is not None:
            session.add(att)
            await session.flush()
            return att
        async with self.message_repo.get_session() as s:
            s.add(att)
            await s.commit()
            await s.refresh(att)
            return att

    async def resolve_attachments_dtos(self, attachments: list[MailAttachmentModel]) -> list[dict[str, Any]]:
        if not attachments:
            return []

        dtos = [
            {
                "attachment_id": a.attachment_id,
                "message_id": a.message_id,
                "media_id": a.media_id,
                "filename": a.filename,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
                "content_id": a.content_id,
                "is_inline": bool(a.is_inline),
                "download_url": f"/api/admin/melodi_mailbox/attachments/download?id={a.attachment_id}",
            }
            for a in attachments
        ]

        if self.app and hasattr(self.app, "hook_manager"):
            try:
                await self.app.hook_manager.action.execute(
                    "melodi_media",
                    "resolve_media_batch",
                    {"entities": dtos, "fields": {"media_id": "media_url"}},
                )
            except Exception:
                pass

        return dtos

    async def read_attachment_bytes(self, attachment: MailAttachmentModel) -> tuple[bytes, str, str]:
        """Lit les octets d'une pièce jointe via melodi_media + app.storage."""
        if not self.app or not hasattr(self.app, "hook_manager"):
            raise MailAttachmentError("Stockage média indisponible.", "MEDIA_UNAVAILABLE", 500)

        info = await self.app.hook_manager.action.execute(
            "melodi_media",
            "get_media_info",
            {"media_id": attachment.media_id},
        )
        if not info or not isinstance(info, dict):
            raise MailAttachmentError("Fichier média introuvable.", "NOT_FOUND", 404)

        filename = info.get("filename")
        path_dir = info.get("path_dir", "")
        backend = info.get("storage_backend")
        data = self.app.storage.read(filename, path_dir, backend=backend)
        return data, attachment.filename, attachment.mime_type
