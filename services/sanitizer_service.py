from __future__ import annotations

import html
import re
from typing import Optional

try:
    import nh3  # type: ignore
except ImportError:  # pragma: no cover
    nh3 = None

_ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "caption", "code", "col", "colgroup",
    "dd", "del", "div", "dl", "dt", "em", "figcaption", "figure", "font",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins", "kbd",
    "li", "mark", "ol", "p", "pre", "q", "s", "samp", "small", "span",
    "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead",
    "tr", "u", "ul",
}

_ALLOWED_ATTRIBUTES = {
    "*": {"class", "dir", "lang", "title", "style"},
    "a": {"href", "name", "target", "rel"},
    "img": {"src", "alt", "width", "height", "data-blocked-src"},
    "table": {"border", "cellpadding", "cellspacing", "width"},
    "td": {"colspan", "rowspan", "align", "valign", "width"},
    "th": {"colspan", "rowspan", "align", "valign", "width"},
    "font": {"color", "face", "size"},
}

_REMOTE_IMG_RE = re.compile(
    r'(<img\b[^>]*?\bsrc\s*=\s*)(["\'])(https?://[^"\']+)\2',
    re.IGNORECASE,
)


class SanitizerService:
    """
    Nettoyage HTML strict côté serveur (anti-XSS, anti-script, anti-tracking).
    Le résultat est ensuite affiché côté client dans une <iframe sandbox> isolée.
    """

    @staticmethod
    def sanitize_html(
        raw_html: str,
        block_remote_images: bool = True,
        cid_map: Optional[dict[str, str]] = None,
    ) -> str:
        if not raw_html:
            return ""

        cleaned = raw_html
        if cid_map:
            for cid, url in cid_map.items():
                if cid and url:
                    cleaned = cleaned.replace(f"cid:{cid}", url)

        if nh3 is not None:
            cleaned = nh3.clean(
                cleaned,
                tags=_ALLOWED_TAGS,
                attributes=_ALLOWED_ATTRIBUTES,
                url_schemes={"http", "https", "mailto", "cid"},
                link_rel="noopener noreferrer nofollow",
                strip_comments=True,
            )
        else:
            # Repli minimaliste si nh3 absent
            cleaned = re.sub(r"<\s*(script|iframe|object|embed|form)[^>]*>.*?<\s*/\s*\1\s*>", "", cleaned, flags=re.I | re.S)
            cleaned = re.sub(r"\son\w+\s*=\s*(['\"]).*?\1", "", cleaned, flags=re.I | re.S)
            cleaned = re.sub(r"javascript\s*:", "blocked:", cleaned, flags=re.I)

        if block_remote_images:
            cleaned = _REMOTE_IMG_RE.sub(r'\1"" data-blocked-src=\2\3\2', cleaned)

        return cleaned

    @staticmethod
    def text_to_safe_html(plain_text: str) -> str:
        if not plain_text:
            return ""
        escaped = html.escape(plain_text)
        return f"<pre style=\"font-family: inherit; white-space: pre-wrap; margin: 0;\">{escaped}</pre>"

    @staticmethod
    def make_snippet(body_text: str, body_html: str, max_len: int = 180) -> str:
        source = (body_text or "").strip()
        if not source and body_html:
            source = re.sub(r"<[^>]+>", " ", body_html)
            source = html.unescape(source)
        normalized = re.sub(r"\s+", " ", source).strip()
        if len(normalized) > max_len:
            return normalized[: max_len - 1].rstrip() + "…"
        return normalized
