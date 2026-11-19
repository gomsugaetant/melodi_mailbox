from __future__ import annotations

import json
from typing import Any

from core.routing import Request, Response
from core.routing.decorator import require_permission
from modules.melodi_mailbox.services.mail_account_service import MailAccountError, MailAccountService


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
