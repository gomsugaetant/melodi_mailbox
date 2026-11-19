from __future__ import annotations

import asyncio
import socket
from typing import Optional

from modules.melodi_mailbox.contracts.payloads import MailAutodiscoverResultDTO

# Base de profils IMAP/SMTP connus des principaux fournisseurs
KNOWN_PROVIDERS: dict[str, dict] = {
    "gmail.com": {
        "provider_label": "Google Gmail",
        "provider_type": "imap_smtp",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "auth_mode": "password",
        "notes": "Utilisez un mot de passe d'application Google (ou OAuth2 en Phase 6).",
    },
    "googlemail.com": {
        "provider_label": "Google Gmail",
        "provider_type": "imap_smtp",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "auth_mode": "password",
        "notes": "Utilisez un mot de passe d'application Google.",
    },
    "outlook.com": {
        "provider_label": "Microsoft Outlook / 365",
        "provider_type": "imap_smtp",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "auth_mode": "password",
        "notes": "Microsoft 365 peut requérir OAuth2 selon la politique du tenant.",
    },
    "hotmail.com": {
        "provider_label": "Microsoft Outlook / Hotmail",
        "provider_type": "imap_smtp",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "auth_mode": "password",
    },
    "live.com": {
        "provider_label": "Microsoft Live / Outlook",
        "provider_type": "imap_smtp",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "auth_mode": "password",
    },
    "yahoo.com": {
        "provider_label": "Yahoo Mail",
        "provider_type": "imap_smtp",
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.mail.yahoo.com",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "auth_mode": "password",
    },
    "yahoo.fr": {
        "provider_label": "Yahoo Mail",
        "provider_type": "imap_smtp",
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.mail.yahoo.com",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "auth_mode": "password",
    },
    "icloud.com": {
        "provider_label": "Apple iCloud Mail",
        "provider_type": "imap_smtp",
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.mail.me.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "auth_mode": "password",
        "notes": "Nécessite un mot de passe spécifique à l'application Apple.",
    },
    "zoho.com": {
        "provider_label": "Zoho Mail",
        "provider_type": "imap_smtp",
        "imap_host": "imap.zoho.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.zoho.com",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "auth_mode": "password",
    },
    "infomaniak.com": {
        "provider_label": "Infomaniak",
        "provider_type": "imap_smtp",
        "imap_host": "mail.infomaniak.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "mail.infomaniak.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "auth_mode": "password",
    },
    "gandi.net": {
        "provider_label": "Gandi Mail",
        "provider_type": "imap_smtp",
        "imap_host": "mail.gandi.net",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "mail.gandi.net",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "auth_mode": "password",
    },
    "ovh.net": {
        "provider_label": "OVHcloud Mail",
        "provider_type": "imap_smtp",
        "imap_host": "ssl0.ovh.net",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "ssl0.ovh.net",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "auth_mode": "password",
    },
    "orange.fr": {
        "provider_label": "Orange",
        "provider_type": "imap_smtp",
        "imap_host": "imap.orange.fr",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.orange.fr",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "auth_mode": "password",
    },
    "free.fr": {
        "provider_label": "Free",
        "provider_type": "imap_smtp",
        "imap_host": "imap.free.fr",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.free.fr",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "auth_mode": "password",
    },
}


async def _host_resolves(hostname: str) -> bool:
    """Vérifie de manière non bloquante si un hôte DNS résout."""
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(
            loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM),
            timeout=2.5,
        )
        return True
    except Exception:
        return False


async def autodiscover_mail_settings(
    email_address: str,
    probe_dns: bool = True,
) -> MailAutodiscoverResultDTO:
    """
    Détecte automatiquement les paramètres IMAP/SMTP à partir d'une adresse email.
    1. Correspondance directe dans la base de fournisseurs connus.
    2. Sondage DNS non bloquant sur les sous-domaines standards (imap.<dom>, mail.<dom>, smtp.<dom>).
    3. Proposition par défaut raisonnable si le domaine est personnalisé.
    """
    cleaned = (email_address or "").strip().lower()
    if "@" not in cleaned:
        return {
            "detected": False,
            "provider_label": "Personnalisé",
            "provider_type": "imap_smtp",
            "imap_host": "",
            "imap_port": 993,
            "imap_security": "ssl",
            "smtp_host": "",
            "smtp_port": 587,
            "smtp_security": "starttls",
            "auth_mode": "password",
            "notes": "Adresse email invalide.",
        }

    domain = cleaned.split("@", 1)[1].strip()
    if domain in KNOWN_PROVIDERS:
        preset = KNOWN_PROVIDERS[domain]
        return {
            "detected": True,
            "provider_label": preset["provider_label"],
            "provider_type": preset["provider_type"],
            "imap_host": preset["imap_host"],
            "imap_port": preset["imap_port"],
            "imap_security": preset["imap_security"],
            "smtp_host": preset["smtp_host"],
            "smtp_port": preset["smtp_port"],
            "smtp_security": preset["smtp_security"],
            "auth_mode": preset["auth_mode"],
            "notes": preset.get("notes"),
        }

    imap_host: Optional[str] = None
    smtp_host: Optional[str] = None
    detected = False

    if probe_dns and domain:
        imap_candidates = [f"imap.{domain}", f"mail.{domain}"]
        smtp_candidates = [f"smtp.{domain}", f"mail.{domain}"]

        imap_checks = await asyncio.gather(*[_host_resolves(h) for h in imap_candidates])
        for host, ok in zip(imap_candidates, imap_checks):
            if ok:
                imap_host = host
                detected = True
                break

        smtp_checks = await asyncio.gather(*[_host_resolves(h) for h in smtp_candidates])
        for host, ok in zip(smtp_candidates, smtp_checks):
            if ok:
                smtp_host = host
                detected = True
                break

    return {
        "detected": detected,
        "provider_label": f"Domaine {domain}" if detected else "Serveur personnalisé",
        "provider_type": "imap_smtp",
        "imap_host": imap_host or f"imap.{domain}",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": smtp_host or f"smtp.{domain}",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "auth_mode": "password",
        "notes": (
            "Paramètres détectés via DNS. Vérifiez les ports si votre hébergeur utilise SSL sur 465."
            if detected
            else "Domaine personnalisé : ajustez les hôtes IMAP/SMTP puis testez la connexion."
        ),
    }
