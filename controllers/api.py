from __future__ import annotations

import json
from typing import Any

from core.routing import Request, Response
from core.routing.decorator import require_permission
from modules.melodi_mailbox.services.mail_account_service import MailAccountError, MailAccountService
from modules.melodi_mailbox.services.mail_attachment_service import MailAttachmentError
from modules.melodi_mailbox.services.mail_message_service import MailMessageService
from modules.melodi_mailbox.services.mail_send_service import MailSendService
from modules.melodi_mailbox.services.mail_sync_service import MailSyncService


def _extract_user_context(request: Request) -> tuple[str, str, bool]:
    """Extrait (user_id, organization_id, is_sudo) depuis la session ou le contexte JWT."""
    user_raw = request.get_session("user_payload") or request.data_context.get("user_payload")
    user = json.loads(user_raw) if isinstance(user_raw, str) else (user_raw or {})

    user_id = str(user.get("user_id") or user.get("id") or "")
    is_sudo = bool(user.get("is_sudo"))

    headers = getattr(request, "headers", {}) or {}
    query = getattr(request, "query", {}) or {}
    data_context = getattr(request, "data_context", {}) or {}

    org_id = str(
        (headers.get("X-Organization-Id") if hasattr(headers, "get") else None)
        or (query.get("org_id") if hasattr(query, "get") else None)
        or user.get("organization_id")
        or (data_context.get("active_organization_id") if hasattr(data_context, "get") else None)
        or "default"
    )
    return user_id, org_id, is_sudo


async def _parse_json_body(request: Request) -> dict[str, Any]:
    if hasattr(request, "get_json"):
        data = await request.get_json()
        if isinstance(data, dict):
            return data
    body = getattr(request, "body", None)
    if isinstance(body, dict):
        return body
    if isinstance(body, (bytes, str)) and body:
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _get_account_service(request: Request) -> MailAccountService:
    mod = (
        request.app.module_manager.get_module("melodi_mailbox")
        if hasattr(request.app, "module_manager")
        else getattr(request, "module", None)
    )
    if mod is not None and getattr(mod, "account_service", None) is not None:
        return mod.account_service
    return MailAccountService(mod or request.app)


def _get_mailbox_module(request: Request):
    return (
        request.app.module_manager.get_module("melodi_mailbox")
        if hasattr(request.app, "module_manager")
        else getattr(request, "module", None)
    )


def _get_sync_service(request: Request) -> MailSyncService:
    mod = _get_mailbox_module(request)
    if mod is not None and getattr(mod, "sync_service", None) is not None:
        return mod.sync_service
    return MailSyncService(mod or request.app)


def _get_message_service(request: Request) -> MailMessageService:
    mod = _get_mailbox_module(request)
    if mod is not None and getattr(mod, "message_service", None) is not None:
        return mod.message_service
    return MailMessageService(mod or request.app)


def _get_send_service(request: Request) -> MailSendService:
    mod = _get_mailbox_module(request)
    if mod is not None and getattr(mod, "send_service", None) is not None:
        return mod.send_service
    return MailSendService(mod or request.app)


class MailAPIController:
    """API REST JSON pour melodi_mailbox (Phase 1 : Comptes, Autodiscover, Test IMAP/SMTP, Dossiers)."""

    @staticmethod
    @require_permission("melodi_mailbox.mail:read")
    async def list_accounts(request: Request, response: Response):
        try:
            user_id, org_id, is_sudo = _extract_user_context(request)
            service = _get_account_service(request)
            accounts = await service.list_accounts(
                organization_id=org_id,
                user_id=user_id,
                include_inactive=True,
                is_sudo=is_sudo,
            )
            return response.send_json(
                {
                    "success": True,
                    "data": accounts,
                    "meta": {"total": len(accounts)},
                }
            )
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:read")
    async def get_account(request: Request, response: Response):
        try:
            query = getattr(request, "query", {}) or {}
            account_id = query.get("id") or query.get("account_id")
            if not account_id:
                response.set_status(400)
                return response.send_json(
                    {"success": False, "error": {"code": "MISSING_ID", "message": "Paramètre id requis."}}
                )

            user_id, org_id, is_sudo = _extract_user_context(request)
            service = _get_account_service(request)
            account = await service.get_account(account_id, org_id, user_id, is_sudo=is_sudo)
            return response.send_json({"success": True, "data": account})
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:manage_accounts")
    async def create_account(request: Request, response: Response):
        try:
            user_id, org_id, _ = _extract_user_context(request)
            payload = await _parse_json_body(request)
            service = _get_account_service(request)
            account = await service.create_account(org_id, user_id, payload)
            response.set_status(201)
            return response.send_json({"success": True, "data": account})
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:manage_accounts")
    async def update_account(request: Request, response: Response):
        try:
            query = getattr(request, "query", {}) or {}
            payload = await _parse_json_body(request)
            account_id = query.get("id") or query.get("account_id") or payload.get("account_id")
            if not account_id:
                response.set_status(400)
                return response.send_json(
                    {"success": False, "error": {"code": "MISSING_ID", "message": "Paramètre id requis."}}
                )

            user_id, org_id, is_sudo = _extract_user_context(request)
            service = _get_account_service(request)
            updated = await service.update_account(account_id, org_id, user_id, payload, is_sudo=is_sudo)
            return response.send_json({"success": True, "data": updated})
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:manage_accounts")
    async def delete_account(request: Request, response: Response):
        try:
            query = getattr(request, "query", {}) or {}
            payload = await _parse_json_body(request)
            account_id = query.get("id") or query.get("account_id") or payload.get("account_id")
            if not account_id:
                response.set_status(400)
                return response.send_json(
                    {"success": False, "error": {"code": "MISSING_ID", "message": "Paramètre id requis."}}
                )

            user_id, org_id, is_sudo = _extract_user_context(request)
            service = _get_account_service(request)
            deleted = await service.delete_account(account_id, org_id, user_id, is_sudo=is_sudo)
            return response.send_json({"success": True, "data": {"deleted": deleted}})
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:manage_accounts")
    async def autodiscover(request: Request, response: Response):
        try:
            payload = await _parse_json_body(request)
            email_address = (payload.get("email_address") or "").strip()
            if not email_address:
                response.set_status(400)
                return response.send_json(
                    {"success": False, "error": {"code": "VALIDATION_FAILED", "message": "email_address requis."}}
                )

            service = _get_account_service(request)
            result = await service.connection_service.autodiscover(
                email_address=email_address,
                probe_dns=bool(payload.get("probe_dns", True)),
            )
            return response.send_json({"success": True, "data": result})
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:manage_accounts")
    async def test_connection(request: Request, response: Response):
        try:
            query = getattr(request, "query", {}) or {}
            payload = await _parse_json_body(request)
            user_id, org_id, is_sudo = _extract_user_context(request)
            service = _get_account_service(request)

            account_id = query.get("id") or query.get("account_id") or payload.get("account_id")
            if account_id:
                result = await service.test_saved_account_connection(
                    account_id=account_id,
                    organization_id=org_id,
                    user_id=user_id,
                    is_sudo=is_sudo,
                    test_imap=bool(payload.get("test_imap", True)),
                    test_smtp=bool(payload.get("test_smtp", True)),
                )
            else:
                result = await service.test_ad_hoc_connection(user_id=user_id, payload=payload)

            return response.send_json({"success": True, "data": result.to_dict()})
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:read")
    async def list_folders(request: Request, response: Response):
        try:
            query = getattr(request, "query", {}) or {}
            account_id = query.get("account_id") or query.get("id")
            if not account_id:
                response.set_status(400)
                return response.send_json(
                    {"success": False, "error": {"code": "MISSING_ID", "message": "Paramètre account_id requis."}}
                )

            user_id, org_id, is_sudo = _extract_user_context(request)
            service = _get_account_service(request)
            folders = await service.list_account_folders(account_id, org_id, user_id, is_sudo=is_sudo)
            return response.send_json(
                {"success": True, "data": folders, "meta": {"total": len(folders)}}
            )
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    # ── Phase 2 : Synchronisation, Fils, Messages, Envoi, Brouillons, PJ ─────

    @staticmethod
    @require_permission("melodi_mailbox.mail:read")
    async def sync_account(request: Request, response: Response):
        try:
            query = getattr(request, "query", {}) or {}
            payload = await _parse_json_body(request)
            account_id = query.get("id") or query.get("account_id") or payload.get("account_id")
            if not account_id:
                response.set_status(400)
                return response.send_json(
                    {"success": False, "error": {"code": "MISSING_ID", "message": "account_id requis."}}
                )

            user_id, org_id, is_sudo = _extract_user_context(request)
            sync_svc = _get_sync_service(request)
            res = await sync_svc.sync_account(
                account_id=account_id,
                organization_id=org_id,
                user_id=user_id,
                is_sudo=is_sudo,
                folder_id=query.get("folder_id") or payload.get("folder_id"),
                limit=int(payload.get("limit") or 50),
            )
            return response.send_json({"success": True, "data": res})
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "SYNC_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:read")
    async def list_threads(request: Request, response: Response):
        try:
            query = getattr(request, "query", {}) or {}
            account_id = query.get("account_id")
            if not account_id:
                response.set_status(400)
                return response.send_json(
                    {"success": False, "error": {"code": "MISSING_ID", "message": "account_id requis."}}
                )

            user_id, org_id, is_sudo = _extract_user_context(request)
            msg_svc = _get_message_service(request)
            page = int(query.get("page") or 1)
            per_page = min(int(query.get("per_page") or 30), 100)
            res = await msg_svc.list_threads(
                account_id=account_id,
                organization_id=org_id,
                user_id=user_id,
                is_sudo=is_sudo,
                folder_id=query.get("folder_id") or None,
                starred_only=str(query.get("starred", "")).lower() in ("1", "true"),
                unread_only=str(query.get("unread", "")).lower() in ("1", "true"),
                has_attachments_only=str(query.get("has_attachments", "")).lower() in ("1", "true"),
                search=query.get("search") or None,
                page=page,
                per_page=per_page,
            )
            return response.send_json(
                {
                    "success": True,
                    "data": res["items"],
                    "meta": {"total": res["total"], "page": res["page"], "per_page": res["per_page"]},
                }
            )
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:read")
    async def get_thread_detail(request: Request, response: Response):
        try:
            query = getattr(request, "query", {}) or {}
            thread_id = query.get("id") or query.get("thread_id")
            if not thread_id:
                response.set_status(400)
                return response.send_json(
                    {"success": False, "error": {"code": "MISSING_ID", "message": "thread_id requis."}}
                )

            user_id, org_id, is_sudo = _extract_user_context(request)
            msg_svc = _get_message_service(request)
            detail = await msg_svc.get_thread_detail(thread_id, org_id, user_id, is_sudo=is_sudo)
            return response.send_json({"success": True, "data": detail})
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:send")
    async def save_draft(request: Request, response: Response):
        try:
            user_id, org_id, is_sudo = _extract_user_context(request)
            payload = await _parse_json_body(request)
            send_svc = _get_send_service(request)
            draft = await send_svc.save_draft(org_id, user_id, payload, is_sudo=is_sudo)
            return response.send_json({"success": True, "data": draft})
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:send")
    async def send_message(request: Request, response: Response):
        try:
            user_id, org_id, is_sudo = _extract_user_context(request)
            payload = await _parse_json_body(request)
            send_svc = _get_send_service(request)
            result = await send_svc.queue_send(
                org_id,
                user_id,
                payload,
                is_sudo=is_sudo,
                dispatch_async=bool(payload.get("async", True)),
            )
            return response.send_json({"success": True, "data": result})
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "SEND_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:read")
    async def set_flags(request: Request, response: Response):
        try:
            user_id, org_id, is_sudo = _extract_user_context(request)
            payload = await _parse_json_body(request)
            message_ids = list(payload.get("message_ids") or [])
            msg_svc = _get_message_service(request)
            updated = await msg_svc.set_flags(
                message_ids=message_ids,
                organization_id=org_id,
                user_id=user_id,
                is_sudo=is_sudo,
                is_read=payload.get("is_read"),
                is_starred=payload.get("is_starred"),
            )
            return response.send_json({"success": True, "data": {"updated": updated}})
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:read")
    async def move_messages(request: Request, response: Response):
        try:
            user_id, org_id, is_sudo = _extract_user_context(request)
            payload = await _parse_json_body(request)
            msg_svc = _get_message_service(request)
            moved = await msg_svc.move_messages(
                message_ids=list(payload.get("message_ids") or []),
                organization_id=org_id,
                user_id=user_id,
                target_folder_id=payload.get("target_folder_id"),
                target_folder_type=payload.get("target_folder_type"),
                is_sudo=is_sudo,
            )
            return response.send_json({"success": True, "data": {"moved": moved}})
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:delete")
    async def delete_messages(request: Request, response: Response):
        try:
            user_id, org_id, is_sudo = _extract_user_context(request)
            payload = await _parse_json_body(request)
            query = getattr(request, "query", {}) or {}
            ids = list(payload.get("message_ids") or [])
            if not ids and query.get("id"):
                ids = [str(query["id"])]
            msg_svc = _get_message_service(request)
            deleted = await msg_svc.delete_messages_permanently(
                message_ids=ids,
                organization_id=org_id,
                user_id=user_id,
                is_sudo=is_sudo,
            )
            return response.send_json({"success": True, "data": {"deleted": deleted}})
        except MailAccountError as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:send")
    async def upload_attachment(request: Request, response: Response):
        try:
            user_id, org_id, is_sudo = _extract_user_context(request)
            files = getattr(request, "files", None) or {}
            form = getattr(request, "form", None) or {}
            file_obj = files.get("file") if hasattr(files, "get") else None
            message_id = form.get("message_id") if hasattr(form, "get") else None
            account_id = form.get("account_id") if hasattr(form, "get") else None

            if not file_obj or not account_id:
                response.set_status(400)
                return response.send_json(
                    {"success": False, "error": {"code": "VALIDATION_FAILED", "message": "file et account_id requis."}}
                )

            send_svc = _get_send_service(request)
            if not message_id:
                draft = await send_svc.save_draft(org_id, user_id, {"account_id": account_id}, is_sudo=is_sudo)
                message_id = draft["message_id"]

            raw_bytes = file_obj.read()
            att = await send_svc.attachment_service.store_attachment_bytes(
                organization_id=org_id,
                message_id=message_id,
                filename=getattr(file_obj, "filename", "piece_jointe"),
                content=raw_bytes,
                mime_type=getattr(file_obj, "content_type", None),
                user_id=user_id,
            )
            dtos = await send_svc.attachment_service.resolve_attachments_dtos([att])
            return response.send_json({"success": True, "data": {"message_id": message_id, "attachment": dtos[0]}})
        except (MailAccountError, MailAttachmentError) as exc:
            response.set_status(exc.status_code)
            return response.send_json(
                {"success": False, "error": {"code": exc.code, "message": exc.message}}
            )
        except Exception as exc:
            response.set_status(500)
            return response.send_json(
                {"success": False, "error": {"code": "UPLOAD_ERROR", "message": str(exc)}}
            )

    @staticmethod
    @require_permission("melodi_mailbox.mail:read")
    async def download_attachment(request: Request, response: Response):
        try:
            query = getattr(request, "query", {}) or {}
            attachment_id = query.get("id") or query.get("attachment_id")
            if not attachment_id:
                return await response.abort(400, "attachment_id requis")

            user_id, org_id, is_sudo = _extract_user_context(request)
            msg_svc = _get_message_service(request)
            att = await msg_svc.message_repo.get_attachment_by_id(attachment_id, organization_id=org_id)
            if not att:
                return await response.abort(404, "Pièce jointe introuvable")

            msg = await msg_svc.message_repo.get_message_by_id(att.message_id, organization_id=org_id)
            if not msg:
                return await response.abort(404, "Message parent introuvable")

            acct = await msg_svc.account_repo.get_by_id(msg.account_id, organization_id=org_id)
            await msg_svc.account_service._assert_access(acct, org_id, user_id, is_sudo=is_sudo)

            raw_bytes, fname, mime = await msg_svc.attachment_service.read_attachment_bytes(att)
            headers = {
                "Content-Type": mime,
                "Content-Disposition": f'attachment; filename="{fname}"',
                "X-Content-Type-Options": "nosniff",
            }
            return await response.make_response(raw_bytes, 200, headers)
        except MailAccountError as exc:
            return await response.abort(exc.status_code, exc.message)
        except Exception as exc:
            return await response.abort(500, str(exc))
