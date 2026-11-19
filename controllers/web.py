from __future__ import annotations

from base.components import admin_layout
from core.page_builder import Component, Page
from core.routing import Request, Response
from core.routing.decorator import require_permission


class MailWebController:
    """
    Contrôleur Web SPA de melodi_mailbox.
    ZÉRO requête SQL ici : sert uniquement la coquille HTML ultra-légère + i18n.
    """

    @staticmethod
    @require_permission("melodi_mailbox.mail:read")
    async def index(request: Request, response: Response):
        mod = getattr(request, "module", None)
        t = mod.t if mod else (lambda k, default="": default or k)

        i18n_bundle = {
            "app_title": t("mail.title", "MELODI Mailbox"),
            "loading": t("mail.loading", "Chargement..."),
            "saving": t("mail.saving", "Enregistrement..."),
            "testing": t("mail.testing", "Test de connexion en cours..."),
            "detecting": t("mail.detecting", "Détection automatique..."),
            "account_created": t("mail.account_created", "Compte email ajouté avec succès."),
            "account_updated": t("mail.account_updated", "Compte email mis à jour."),
            "account_deleted": t("mail.account_deleted", "Compte email supprimé."),
            "confirm_delete_account": t(
                "mail.confirm_delete_account",
                "Voulez-vous vraiment supprimer ce compte email ? Les identifiants chiffrés et dossiers synchronisés seront supprimés.",
            ),
            "connection_ok": t("mail.connection_ok", "Connexion IMAP et SMTP opérationnelle."),
            "connection_failed": t("mail.connection_failed", "Échec du test de connexion."),
            "autodiscover_ok": t("mail.autodiscover_ok", "Paramètres serveur détectés automatiquement."),
            "autodiscover_manual": t(
                "mail.autodiscover_manual",
                "Domaine personnalisé détecté : vérifiez les serveurs IMAP/SMTP.",
            ),
            "status_idle": t("mail.status_idle", "Prêt"),
            "status_syncing": t("mail.status_syncing", "Synchronisation..."),
            "status_error": t("mail.status_error", "Erreur"),
            "status_paused": t("mail.status_paused", "En pause"),
            "default_badge": t("mail.default_badge", "Par défaut"),
            "active_badge": t("mail.active_badge", "Actif"),
            "inactive_badge": t("mail.inactive_badge", "Inactif"),
            "credentials_stored": t("mail.credentials_stored", "Identifiants chiffrés"),
            "credentials_missing": t("mail.credentials_missing", "Identifiants manquants"),
        }

        content = Component(
            module_name="melodi_mailbox",
            name="mail_shell",
            context={"mail_i18n": i18n_bundle},
        )
        content.add_template("spa/mail_shell.html")
        page = Page(t("mail.title", "MELODI Mailbox"), admin_layout(content))
        return await response.render_page(page)
