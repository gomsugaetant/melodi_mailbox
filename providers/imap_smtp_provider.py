from __future__ import annotations

import asyncio
import email
import email.policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parsedate_to_datetime
import imaplib
import re
import smtplib
import ssl
import time
from typing import Optional

from modules.melodi_mailbox.providers.base import (
    BaseMailProvider,
    ConnectionTestResult,
    FetchBatchResult,
    FetchedAttachmentData,
    FetchedEmailData,
    MailAccountCredentials,
    OutboundEmailData,
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

    # ── Récupération, parsing MIME, envoi & flags (Phase 2) ───────────────────

    @staticmethod
    def _decode_mime_header(raw_val: Optional[str]) -> str:
        if not raw_val:
            return ""
        try:
            return str(make_header(decode_header(raw_val))).strip()
        except Exception:
            return str(raw_val).strip()

    @staticmethod
    def _parse_addr_list(raw_headers: list[str]) -> list[dict[str, str]]:
        parsed = []
        for name, addr in getaddresses(raw_headers):
            clean_addr = (addr or "").strip().lower()
            if clean_addr:
                parsed.append({"name": ImapSmtpProvider._decode_mime_header(name), "email": clean_addr})
        return parsed

    @staticmethod
    def _extract_uid_validity(client: imaplib.IMAP4) -> int:
        try:
            resp = client.response("UIDVALIDITY")
            if resp and resp[1] and resp[1][0]:
                val = resp[1][0]
                return int(val.decode() if isinstance(val, bytes) else val)
        except Exception:
            pass
        return 1

    @staticmethod
    def _parse_rfc_message(
        raw_bytes: bytes,
        imap_uid: int,
        uid_validity: int,
        mailbox: str,
        flags_bytes: bytes = b"",
    ) -> FetchedEmailData:
        msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)

        from_list = ImapSmtpProvider._parse_addr_list(msg.get_all("From", []))
        from_name = from_list[0]["name"] if from_list else ""
        from_email = from_list[0]["email"] if from_list else ""

        to_list = ImapSmtpProvider._parse_addr_list(msg.get_all("To", []))
        cc_list = ImapSmtpProvider._parse_addr_list(msg.get_all("Cc", []))
        reply_to_list = ImapSmtpProvider._parse_addr_list(msg.get_all("Reply-To", []))

        rfc_msg_id = (msg.get("Message-ID") or "").strip() or None
        in_reply_to = (msg.get("In-Reply-To") or "").strip() or None
        refs_raw = (msg.get("References") or "").strip()
        references = [r.strip() for r in refs_raw.split() if r.strip()] if refs_raw else []
        subject = ImapSmtpProvider._decode_mime_header(msg.get("Subject")) or "(Sans objet)"

        sent_iso: Optional[str] = None
        date_raw = msg.get("Date")
        if date_raw:
            try:
                dt = parsedate_to_datetime(date_raw)
                sent_iso = dt.isoformat()
            except Exception:
                sent_iso = None

        text_parts: list[str] = []
        html_parts: list[str] = []
        attachments: list[FetchedAttachmentData] = []

        if msg.is_multipart():
            for part in msg.walk():
                if part.is_multipart():
                    continue
                ctype = (part.get_content_type() or "application/octet-stream").lower()
                disp = (part.get_content_disposition() or "").lower()
                filename = part.get_filename()
                cid = (part.get("Content-ID") or "").strip().strip("<>") or None

                payload_bytes = part.get_payload(decode=True) or b""
                if disp == "attachment" or filename or (cid and ctype.startswith("image/")):
                    attachments.append(
                        FetchedAttachmentData(
                            filename=ImapSmtpProvider._decode_mime_header(filename) or f"attachment_{len(attachments)+1}",
                            mime_type=ctype,
                            content=payload_bytes,
                            size_bytes=len(payload_bytes),
                            content_id=cid,
                            is_inline=(disp == "inline" or bool(cid)),
                        )
                    )
                elif ctype == "text/plain":
                    charset = part.get_content_charset() or "utf-8"
                    text_parts.append(payload_bytes.decode(charset, errors="replace"))
                elif ctype == "text/html":
                    charset = part.get_content_charset() or "utf-8"
                    html_parts.append(payload_bytes.decode(charset, errors="replace"))
        else:
            ctype = (msg.get_content_type() or "text/plain").lower()
            payload_bytes = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload_bytes.decode(charset, errors="replace")
            if ctype == "text/html":
                html_parts.append(decoded)
            else:
                text_parts.append(decoded)

        flags_str = flags_bytes.decode("utf-8", errors="replace").lower() if flags_bytes else ""
        headers_subset = {
            k: ImapSmtpProvider._decode_mime_header(str(v))
            for k, v in list(msg.items())[:30]
        }

        return FetchedEmailData(
            imap_uid=imap_uid,
            imap_uid_validity=uid_validity,
            imap_mailbox=mailbox,
            rfc_message_id=rfc_msg_id,
            in_reply_to=in_reply_to,
            references=references,
            from_name=from_name,
            from_email=from_email,
            to=to_list,
            cc=cc_list,
            reply_to=reply_to_list[0]["email"] if reply_to_list else None,
            subject=subject,
            body_text="\n".join(text_parts).strip(),
            body_html="\n".join(html_parts).strip(),
            raw_headers=headers_subset,
            is_read="\\seen" in flags_str,
            is_starred="\\flagged" in flags_str,
            is_draft="\\draft" in flags_str,
            size_bytes=len(raw_bytes),
            sent_at=sent_iso,
            received_at=sent_iso,
            attachments=attachments,
        )

    def _fetch_messages_sync(self, mailbox: str, last_uid: int, limit: int) -> FetchBatchResult:
        client = self._connect_imap_sync()
        try:
            quoted_box = f'"{mailbox}"' if " " in mailbox and not mailbox.startswith('"') else mailbox
            status, _ = client.select(quoted_box, readonly=True)
            if status != "OK":
                return FetchBatchResult(uid_validity=None, last_uid=last_uid, messages=[])

            uid_validity = self._extract_uid_validity(client)
            search_criteria = f"UID {int(last_uid) + 1}:*" if last_uid > 0 else "ALL"
            st_search, uid_data = client.uid("search", None, search_criteria)
            if st_search != "OK" or not uid_data or not uid_data[0]:
                return FetchBatchResult(uid_validity=uid_validity, last_uid=last_uid, messages=[])

            raw_uids = [int(u) for u in uid_data[0].split() if u.isdigit()]
            # Exclure les UID <= last_uid (certains serveurs renvoient le dernier UID sur X:*)
            uids = [u for u in raw_uids if u > last_uid]
            if not uids:
                return FetchBatchResult(uid_validity=uid_validity, last_uid=last_uid, messages=[])

            # Lors de la synchro initiale (last_uid == 0), récupérer les N plus récents
            if last_uid == 0 and len(uids) > limit:
                uids = uids[-limit:]
            else:
                uids = uids[:limit]

            fetched: list[FetchedEmailData] = []
            max_uid = last_uid
            for uid in uids:
                st_f, msg_data = client.uid("fetch", str(uid), "(FLAGS BODY.PEEK[])")
                if st_f != "OK" or not msg_data:
                    continue
                raw_bytes = b""
                flags_bytes = b""
                for part in msg_data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        flags_bytes = part[0] or b""
                        raw_bytes = part[1] or b""
                        break
                if not raw_bytes:
                    continue
                fetched.append(self._parse_rfc_message(raw_bytes, uid, uid_validity, mailbox, flags_bytes))
                if uid > max_uid:
                    max_uid = uid

            return FetchBatchResult(uid_validity=uid_validity, last_uid=max_uid, messages=fetched)
        finally:
            try:
                client.logout()
            except Exception:
                pass

    async def fetch_messages(
        self,
        mailbox: str = "INBOX",
        last_uid: int = 0,
        limit: int = 50,
    ) -> FetchBatchResult:
        return await asyncio.to_thread(self._fetch_messages_sync, mailbox, last_uid, limit)

    def _send_message_sync(self, outbound: OutboundEmailData, sent_mailbox: Optional[str]) -> str:
        c = self.credentials
        if not c.smtp_host:
            raise ValueError("Hôte SMTP requis.")

        msg = EmailMessage()
        msg["From"] = formataddr((outbound.from_name, outbound.from_email)) if outbound.from_name else outbound.from_email
        if outbound.to:
            msg["To"] = ", ".join(outbound.to)
        if outbound.cc:
            msg["Cc"] = ", ".join(outbound.cc)
        if outbound.reply_to:
            msg["Reply-To"] = outbound.reply_to
        msg["Subject"] = outbound.subject or ""
        msg["Date"] = formatdate(localtime=True)
        rfc_id = outbound.rfc_message_id or make_msgid(domain=outbound.from_email.split("@")[-1])
        msg["Message-ID"] = rfc_id
        if outbound.in_reply_to:
            msg["In-Reply-To"] = outbound.in_reply_to
        if outbound.references:
            msg["References"] = " ".join(outbound.references)

        msg.set_content(outbound.body_text or "")
        if outbound.body_html:
            msg.add_alternative(outbound.body_html, subtype="html")

        for att in outbound.attachments:
            maintype, _, subtype = (att.mime_type or "application/octet-stream").partition("/")
            msg.add_attachment(
                att.content,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=att.filename,
                cid=f"<{att.content_id}>" if att.content_id else None,
            )

        all_rcpts = list(dict.fromkeys([*outbound.to, *outbound.cc, *outbound.bcc]))
        security = (c.smtp_security or "starttls").lower()
        timeout = int(c.timeout or 15)
        client: Optional[smtplib.SMTP] = None
        try:
            if security == "ssl":
                client = smtplib.SMTP_SSL(
                    c.smtp_host, int(c.smtp_port or 465), timeout=timeout, context=self._ssl_context()
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

            client.send_message(msg, from_addr=outbound.from_email, to_addrs=all_rcpts)
        finally:
            if client is not None:
                try:
                    client.quit()
                except Exception:
                    pass

        # Copie optionnelle dans le dossier Sent via IMAP APPEND
        if sent_mailbox and c.imap_host:
            imap_client: Optional[imaplib.IMAP4] = None
            try:
                imap_client = self._connect_imap_sync()
                quoted = f'"{sent_mailbox}"' if " " in sent_mailbox and not sent_mailbox.startswith('"') else sent_mailbox
                imap_client.append(quoted, "\\Seen", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            except Exception:
                pass
            finally:
                if imap_client is not None:
                    try:
                        imap_client.logout()
                    except Exception:
                        pass

        return rfc_id

    async def send_message(
        self,
        outbound: OutboundEmailData,
        sent_mailbox: Optional[str] = None,
    ) -> str:
        return await asyncio.to_thread(self._send_message_sync, outbound, sent_mailbox)

    def _set_flags_sync(self, mailbox: str, imap_uid: int, flags: list[str], add: bool) -> bool:
        client = self._connect_imap_sync()
        try:
            quoted = f'"{mailbox}"' if " " in mailbox and not mailbox.startswith('"') else mailbox
            st, _ = client.select(quoted)
            if st != "OK":
                return False
            op = "+FLAGS.SILENT" if add else "-FLAGS.SILENT"
            flag_str = f"({' '.join(flags)})"
            st2, _ = client.uid("store", str(imap_uid), op, flag_str)
            return st2 == "OK"
        finally:
            try:
                client.logout()
            except Exception:
                pass

    async def set_message_flags(
        self,
        mailbox: str,
        imap_uid: int,
        flags: list[str],
        add: bool = True,
    ) -> bool:
        return await asyncio.to_thread(self._set_flags_sync, mailbox, imap_uid, flags, add)

    def _move_message_sync(self, src_mailbox: str, imap_uid: int, dst_mailbox: str) -> bool:
        client = self._connect_imap_sync()
        try:
            q_src = f'"{src_mailbox}"' if " " in src_mailbox and not src_mailbox.startswith('"') else src_mailbox
            q_dst = f'"{dst_mailbox}"' if " " in dst_mailbox and not dst_mailbox.startswith('"') else dst_mailbox
            st, _ = client.select(q_src)
            if st != "OK":
                return False
            st_copy, _ = client.uid("copy", str(imap_uid), q_dst)
            if st_copy != "OK":
                return False
            client.uid("store", str(imap_uid), "+FLAGS.SILENT", "(\\Deleted)")
            client.expunge()
            return True
        finally:
            try:
                client.logout()
            except Exception:
                pass

    async def move_message(
        self,
        src_mailbox: str,
        imap_uid: int,
        dst_mailbox: str,
    ) -> bool:
        return await asyncio.to_thread(self._move_message_sync, src_mailbox, imap_uid, dst_mailbox)
