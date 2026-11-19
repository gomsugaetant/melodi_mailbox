from __future__ import annotations

import asyncio
import imaplib
import re
import smtplib
import ssl
import time
from typing import Optional

from modules.melodi_mailbox.providers.base import (
    BaseMailProvider,
    ConnectionTestResult,
    MailAccountCredentials,
    RemoteFolderInfo,
)

# Regex pour parser les lignes IMAP LIST : (<flags>) "<delimiter>" "<mailbox>"
_IMAP_LIST_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+"?(?P<delim>[^"\s]+|NIL)"?\s+(?P<name>.+)$')

_SPECIAL_USE_MAP: dict[str, tuple[str, int]] = {
    "\\inbox": ("inbox", 10),
    "\\flagged": ("starred", 20),
    "\\sent": ("sent", 30),
    "\\drafts": ("drafts", 40),
    "\\archive": ("archive", 50),
    "\\all": ("archive", 55),
    "\\junk": ("spam", 60),
    "\\spam": ("spam", 60),
    "\\trash": ("trash", 70),
}

_NAME_FALLBACK_MAP: dict[str, tuple[str, int]] = {
    "inbox": ("inbox", 10),
    "boîte de réception": ("inbox", 10),
    "sent": ("sent", 30),
    "sent items": ("sent", 30),
    "sent messages": ("sent", 30),
    "envoyés": ("sent", 30),
    "messages envoyés": ("sent", 30),
    "drafts": ("drafts", 40),
    "brouillons": ("drafts", 40),
    "archive": ("archive", 50),
    "archives": ("archive", 50),
    "spam": ("spam", 60),
    "junk": ("spam", 60),
    "junk e-mail": ("spam", 60),
    "courrier indésirable": ("spam", 60),
    "trash": ("trash", 70),
    "deleted items": ("trash", 70),
    "deleted messages": ("trash", 70),
    "corbeille": ("trash", 70),
}


def _classify_folder(raw_name: str, flags: list[str], delimiter: str) -> tuple[str, str, int]:
    """Détermine le type fonctionnel, le nom affichable et l'ordre de tri d'un dossier IMAP."""
    cleaned_remote = raw_name.strip().strip('"')
    display_name = cleaned_remote.split(delimiter)[-1] if delimiter and delimiter != "NIL" else cleaned_remote

    lower_flags = {f.lower() for f in flags}
    for flag, (ftype, order) in _SPECIAL_USE_MAP.items():
        if flag in lower_flags:
            return ftype, display_name, order

    lower_name = display_name.lower()
    if lower_name in _NAME_FALLBACK_MAP:
        ftype, order = _NAME_FALLBACK_MAP[lower_name]
        return ftype, display_name, order

    return "custom", display_name, 100


def parse_imap_list_line(line: bytes | str) -> Optional[RemoteFolderInfo]:
    """Parse une ligne de réponse IMAP LIST en RemoteFolderInfo."""
    text = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else str(line)
    m = _IMAP_LIST_RE.match(text.strip())
    if not m:
        return None

    flags = [f.strip() for f in m.group("flags").split() if f.strip()]
    if "\\noselect" in {f.lower() for f in flags}:
        return None

    delimiter = m.group("delim")
    if delimiter.upper() == "NIL":
        delimiter = "/"

    remote_name = m.group("name").strip()
    if remote_name.startswith('"') and remote_name.endswith('"'):
        remote_name = remote_name[1:-1]

    folder_type, display_name, sort_order = _classify_folder(remote_name, flags, delimiter)
    return RemoteFolderInfo(
        name=display_name,
        remote_name=remote_name,
        delimiter=delimiter,
        folder_type=folder_type,
        sort_order=sort_order,
        flags=flags,
    )


class ImapSmtpProvider(BaseMailProvider):
    """
    Connecteur IMAP + SMTP asynchrone (non bloquant).
    Exécute les appels IMAP/SMTP dans un executor dédié avec SSL/TLS ou STARTTLS,
    timeout strict, et zéro journalisation des mots de passe.
    """

    def __init__(self, credentials: MailAccountCredentials):
        super().__init__(credentials)

    def _ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        return ctx

    # ── IMAP synchrone exécuté via asyncio.to_thread ──────────────────────────

    def _connect_imap_sync(self) -> imaplib.IMAP4:
        c = self.credentials
        if not c.imap_host:
            raise ValueError("Hôte IMAP requis.")

        security = (c.imap_security or "ssl").lower()
        timeout = int(c.timeout or 15)

        if security == "ssl":
            client = imaplib.IMAP4_SSL(
                c.imap_host,
                int(c.imap_port or 993),
                ssl_context=self._ssl_context(),
                timeout=timeout,
            )
        else:
            client = imaplib.IMAP4(c.imap_host, int(c.imap_port or 143), timeout=timeout)
            if security == "starttls":
                client.starttls(ssl_context=self._ssl_context())

        username = c.username or c.email_address
        if c.auth_mode == "oauth2" and c.oauth_access_token:
            auth_str = f"user={username}\x01auth=Bearer {c.oauth_access_token}\x01\x01"
            client.authenticate("XOAUTH2", lambda _: auth_str.encode("utf-8"))
        elif c.password is not None:
            client.login(username, c.password)

        return client

    def _test_imap_sync(self) -> tuple[bool, str, int, list[str], list[RemoteFolderInfo]]:
        t0 = time.perf_counter()
        client: Optional[imaplib.IMAP4] = None
        try:
            client = self._connect_imap_sync()
            caps: list[str] = []
            try:
                _, cap_data = client.capability()
                if cap_data and cap_data[0]:
                    caps = cap_data[0].decode("utf-8", errors="replace").split()
            except Exception:
                pass

            folders = self._extract_folders_sync(client)
            latency = int((time.perf_counter() - t0) * 1000)
            return True, "Connexion IMAP réussie.", latency, caps, folders
        except imaplib.IMAP4.error as exc:
            latency = int((time.perf_counter() - t0) * 1000)
            return False, f"Erreur d'authentification ou protocole IMAP : {exc}", latency, [], []
        except Exception as exc:
            latency = int((time.perf_counter() - t0) * 1000)
            return False, f"Impossible de joindre le serveur IMAP : {exc}", latency, [], []
        finally:
            if client is not None:
                try:
                    client.logout()
                except Exception:
                    pass

    def _extract_folders_sync(self, client: imaplib.IMAP4) -> list[RemoteFolderInfo]:
        folders: list[RemoteFolderInfo] = []
        status, data = client.list()
        if status == "OK" and data:
            for item in data:
                if not item:
                    continue
                if isinstance(item, tuple):
                    item = item[0]
                parsed = parse_imap_list_line(item)
                if parsed:
                    folders.append(parsed)
        folders.sort(key=lambda f: (f.sort_order, f.name.lower()))
        return folders

    # ── SMTP synchrone exécuté via asyncio.to_thread ──────────────────────────

    def _test_smtp_sync(self) -> tuple[bool, str, int]:
        t0 = time.perf_counter()
        c = self.credentials
        if not c.smtp_host:
            return False, "Hôte SMTP requis.", 0

        security = (c.smtp_security or "starttls").lower()
        timeout = int(c.timeout or 15)
        client: Optional[smtplib.SMTP] = None
        try:
            if security == "ssl":
                client = smtplib.SMTP_SSL(
                    c.smtp_host,
                    int(c.smtp_port or 465),
                    timeout=timeout,
                    context=self._ssl_context(),
                )
            else:
                client = smtplib.SMTP(c.smtp_host, int(c.smtp_port or 587), timeout=timeout)
                client.ehlo()
                if security == "starttls":
                    client.starttls(context=self._ssl_context())
                    client.ehlo()

            username = c.username or c.email_address
            if c.auth_mode == "password" and c.password is not None:
                client.login(username, c.password)

            latency = int((time.perf_counter() - t0) * 1000)
            return True, "Connexion SMTP réussie.", latency
        except smtplib.SMTPAuthenticationError:
            latency = int((time.perf_counter() - t0) * 1000)
            return False, "Authentification SMTP refusée (identifiant ou mot de passe incorrect).", latency
        except Exception as exc:
            latency = int((time.perf_counter() - t0) * 1000)
            return False, f"Impossible de joindre le serveur SMTP : {exc}", latency
        finally:
            if client is not None:
                try:
                    client.quit()
                except Exception:
                    pass

    # ── Interface asynchrone BaseMailProvider ─────────────────────────────────

    async def test_connection(
        self, test_imap: bool = True, test_smtp: bool = True
    ) -> ConnectionTestResult:
        imap_ok = not test_imap
        smtp_ok = not test_smtp
        imap_msg = "Non testé."
        smtp_msg = "Non testé."
        imap_latency: Optional[int] = None
        smtp_latency: Optional[int] = None
        caps: list[str] = []
        folders: list[RemoteFolderInfo] = []

        tasks = []
        if test_imap:
            tasks.append(("imap", asyncio.to_thread(self._test_imap_sync)))
        if test_smtp:
            tasks.append(("smtp", asyncio.to_thread(self._test_smtp_sync)))

        if tasks:
            results = await asyncio.gather(*(t[1] for t in tasks))
            for (kind, _), res in zip(tasks, results):
                if kind == "imap":
                    imap_ok, imap_msg, imap_latency, caps, folders = res
                elif kind == "smtp":
                    smtp_ok, smtp_msg, smtp_latency = res

        return ConnectionTestResult(
            success=bool(imap_ok and smtp_ok),
            imap_ok=imap_ok,
            smtp_ok=smtp_ok,
            imap_message=imap_msg,
            smtp_message=smtp_msg,
            imap_latency_ms=imap_latency,
            smtp_latency_ms=smtp_latency,
            imap_capabilities=caps,
            folders=folders,
        )

    async def list_folders(self) -> list[RemoteFolderInfo]:
        def _run() -> list[RemoteFolderInfo]:
            client = self._connect_imap_sync()
            try:
                return self._extract_folders_sync(client)
            finally:
                try:
                    client.logout()
                except Exception:
                    pass

        return await asyncio.to_thread(_run)
