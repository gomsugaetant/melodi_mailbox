from __future__ import annotations

from typing import Any, Optional

from core.module import ApplicationModule, Permission
from modules.melodi_mailbox.controllers.api import MailAPIController
from modules.melodi_mailbox.controllers.web import MailWebController
from modules.melodi_mailbox.models.models import (
    MailAccountAccessModel,
    MailAccountModel,
    MailAttachmentModel,
    MailFolderModel,
    MailIdentityModel,
    MailMessageModel,
    MailSyncStateModel,
    MailThreadModel,
)
from modules.melodi_mailbox.services import (
    CryptoService,
    MailAccountService,
    MailAttachmentService,
    MailConnectionService,
    MailMessageService,
    MailSendService,
    MailSyncService,
    MailThreadService,
)
from modules.melodi_mailbox.tasks import register_mail_tasks


class MelodiMailboxModule(ApplicationModule):
    """Module MELODI Mailbox : client de messagerie professionnel multi-comptes intégré à MELODI ERP."""

    def __init__(self):
        super().__init__(name="melodi_mailbox", router_name="melodi_mailbox")
        self.crypto_service: Optional[CryptoService] = None
        self.connection_service: Optional[MailConnectionService] = None
        self.account_service: Optional[MailAccountService] = None
        self.attachment_service: Optional[MailAttachmentService] = None
        self.thread_service: Optional[MailThreadService] = None
        self.sync_service: Optional[MailSyncService] = None
        self.message_service: Optional[MailMessageService] = None
        self.send_service: Optional[MailSendService] = None

    def _get_permissions(self):
        return [
            Permission(self, "mail:read", "Consulter les boîtes mail et messages"),
            Permission(self, "mail:send", "Composer et envoyer des emails"),
            Permission(self, "mail:manage_accounts", "Configurer et tester les comptes email"),
            Permission(self, "mail:manage_folders", "Créer et organiser les dossiers email"),
            Permission(self, "mail:manage_rules", "Gérer les règles et filtres automatiques"),
            Permission(self, "mail:manage_templates", "Gérer les modèles et signatures"),
            Permission(self, "mail:delete", "Supprimer définitivement des emails"),
            Permission(self, "mail:admin", "Administration complète de MELODI Mailbox"),
        ]

    async def run_dev_migrations(self):
        await self.app.db.create_all(
            [
                MailAccountModel,
                MailAccountAccessModel,
                MailIdentityModel,
                MailFolderModel,
                MailSyncStateModel,
                MailThreadModel,
                MailMessageModel,
                MailAttachmentModel,
            ]
        )

    def _register_actions(self):
        self.add_action("mail.list_accounts", self.action_list_accounts)

    def _register_routes(self):
        # 1. Route Web SPA unique (0 requête SQL)
        self.admin_router.add_route("/", MailWebController.index, methods=["GET"])

        # 2. Routes API REST (publiques JWT/session & admin)
        for router in (self.api_router, self.api_admin_router):
            router.add_route("/accounts", MailAPIController.list_accounts, methods=["GET"])
            router.add_route("/accounts", MailAPIController.create_account, methods=["POST"])
            router.add_route("/accounts/detail", MailAPIController.get_account, methods=["GET"])
            router.add_route("/accounts/update", MailAPIController.update_account, methods=["PUT", "POST"])
            router.add_route("/accounts/delete", MailAPIController.delete_account, methods=["DELETE", "POST"])
            router.add_route("/accounts/autodiscover", MailAPIController.autodiscover, methods=["POST"])
            router.add_route("/accounts/test", MailAPIController.test_connection, methods=["POST"])
            router.add_route("/accounts/sync", MailAPIController.sync_account, methods=["POST"])
            router.add_route("/folders", MailAPIController.list_folders, methods=["GET"])
            router.add_route("/threads", MailAPIController.list_threads, methods=["GET"])
            router.add_route("/threads/detail", MailAPIController.get_thread_detail, methods=["GET"])
            router.add_route("/messages/draft", MailAPIController.save_draft, methods=["POST"])
            router.add_route("/messages/send", MailAPIController.send_message, methods=["POST"])
            router.add_route("/messages/flags", MailAPIController.set_flags, methods=["POST"])
            router.add_route("/messages/move", MailAPIController.move_messages, methods=["POST"])
            router.add_route("/messages/delete", MailAPIController.delete_messages, methods=["DELETE", "POST"])
            router.add_route("/attachments/upload", MailAPIController.upload_attachment, methods=["POST"])
            router.add_route("/attachments/download", MailAPIController.download_attachment, methods=["GET"])

    def _register_navigation(self):
        self.register_navigation(
            id="nav_melodi_mailbox",
            label=self.t("mail.nav_label", "Messagerie"),
            icon="name=mail&fill=white",
            url="/admin/melodi_mailbox/",
            priority=72,
            required_permission="melodi_mailbox.mail:read",
        )

    async def _integrate_with_melodi_media(self):
        """Point d'intégration sécurisé avec melodi_media (utilisé dès la Phase 2 pour les pièces jointes)."""
        return None

    async def _integrate_with_melodi_contacts(self):
        """Point d'intégration sécurisé avec melodi_contacts (correspondance contacts en Phase 5)."""
        return None

    async def load(self):
        # 1. Permissions
        self.permissions = self._get_permissions()

        # 2. Migrations
        await self.run_dev_migrations()

        # 3. Initialisation des services
        self.crypto_service = CryptoService.from_app(self.app)
        self.connection_service = MailConnectionService(self)
        self.account_service = MailAccountService(
            self,
            crypto_service=self.crypto_service,
            connection_service=self.connection_service,
        )
        self.attachment_service = MailAttachmentService(self)
        self.thread_service = MailThreadService(self)
        self.sync_service = MailSyncService(
            self,
            account_service=self.account_service,
            connection_service=self.connection_service,
            thread_service=self.thread_service,
            attachment_service=self.attachment_service,
        )
        self.message_service = MailMessageService(
            self,
            account_service=self.account_service,
            connection_service=self.connection_service,
            thread_service=self.thread_service,
            attachment_service=self.attachment_service,
        )
        self.send_service = MailSendService(
            self,
            account_service=self.account_service,
            connection_service=self.connection_service,
            thread_service=self.thread_service,
            attachment_service=self.attachment_service,
        )
        register_mail_tasks(self)

        # 4. Hooks internes, routes et navigation
        self._register_actions()
        self._register_routes()
        self._register_navigation()

        # 5. Intégrations inter-modules sécurisées (obligatoirement via integration_with_module)
        await self.integration_with_module("melodi_media", self._integrate_with_melodi_media)
        await self.integration_with_module("melodi_contacts", self._integrate_with_melodi_contacts)

    async def action_list_accounts(self, payload: dict | None = None) -> list[dict[str, Any]]:
        data = payload or {}
        org_id = str(data.get("organization_id") or "default")
        user_id = str(data.get("user_id") or "")
        is_sudo = bool(data.get("is_sudo", False))
        return await self.account_service.list_accounts(
            organization_id=org_id,
            user_id=user_id,
            include_inactive=bool(data.get("include_inactive", False)),
            is_sudo=is_sudo,
        )


module = MelodiMailboxModule()
