from __future__ import annotations

from core.tasks.registry import task


def register_mail_tasks(module) -> None:
    """Enregistre les tâches asynchrones melodi_mailbox dans le TaskRegistry central."""

    @task("melodi_mailbox.send_message", module="melodi_mailbox")
    async def send_message_task(message_id: str, organization_id: str = "default"):
        if getattr(module, "send_service", None) is None:
            return {"success": False, "error": "MailSendService non initialisé."}
        return await module.send_service.execute_send_now(message_id, organization_id)

    @task("melodi_mailbox.sync_account", module="melodi_mailbox")
    async def sync_account_task(
        account_id: str,
        organization_id: str = "default",
        user_id: str = "",
        is_sudo: bool = True,
    ):
        if getattr(module, "sync_service", None) is None:
            return {"success": False, "error": "MailSyncService non initialisé."}
        return await module.sync_service.sync_account(
            account_id=account_id,
            organization_id=organization_id,
            user_id=user_id,
            is_sudo=is_sudo,
        )
