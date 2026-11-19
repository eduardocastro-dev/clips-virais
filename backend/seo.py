"""Deterministic, platform-specific SEO copy for manually published GTA Studio videos.

No extra LLM requests, external network calls, ranking guarantees, or invented facts.
All factual copy is derived from the approved script and recorded source/credits.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

PLATFORMS = {"youtube", "tiktok", "instagram"}
BRAND = "GTA 6 Brasil"
CAPTION_LIMITS = {"youtube": 5000, "tiktok": 2200, "instagram": 2200}
DEFAULT_HASHTAGS = {
    "youtube": ("GTA6", "GTA6Brasil", "Shorts"),
    "tiktok": ("GTA6", "GTA6Brasil", "Games", "NoticiasGamer"),
    "instagram": ("GTA6", "GTA6Brasil", "Reels", "Games"),
}
STOPWORDS = {
    "sobre", "para", "com", "mais", "como", "pela", "pelo", "essa",
    "este", "essa", "isso", "aqui", "agora", "novo", "nova", "video",
    "voce", "gta", "brasil", "entenda", "veja", "tudo", "depois",
}


def _line(text, limit=4500):
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(text or ""))
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit].strip()


def _paragraph(text):
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(text or ""))
    return "\n".join(re.sub(r"[ \t]+", " ", row).strip() for row in value.splitlines()).strip()


def _clip(text, maximum):
    text = str(text or "").strip()
    if len(text) <= maximum:
        return text
    cut = text[: maximum + 1].rsplit(" ", 1)[0].rstrip(" ,.;:—-")
    return cut if cut and len(cut) > maximum // 2 else text[:maximum].rstrip(" ,.;:—-")


def _token(value):
    token = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    token = re.sub(r"[^a-zA-Z0-9_]", "", token.lstrip("#"))
    return token[:35]


def _unique(items, max_count):
    found = set()
    output = []
    for item in items:
        token = _token(item)
        key = token.casefold()
        if len(token) < 2 or key in found:
            continue
        found.add(key)
        output.append(token)
        if len(output) >= max_count:
            break
    return output


def _tags(script):
    title = _line(script.get("title", ""), 200)
    words = []
    for word in re.findall(r"[\wÀ-ÿ]+", title, flags=re.UNICODE):
        normalized = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode("ascii").lower()
        if len(normalized) >= 4 and normalized not in STOPWORDS and not normalized.isdigit():
            words.append(word)
    base = ["GTA 6", "GTA VI", "Grand Theft Auto VI", "GTA 6 Brasil", "Rockstar Games"]
    result = []
    seen = set()
    for value in base + [title] + words[:8]:
        value = _line(value, 110)
        if not value or value.casefold() in seen:
            continue
        if sum(map(len, result)) + len(value) + max(0, len(result)) > 450:
            break
        seen.add(value.casefold())
        result.append(value)
    return result


def _source_url(video):
    value = _line(video.get("url"), 1500)
    parsed = urlsplit(value)
    return value if parsed.scheme in ("https", "http") and parsed.netloc else ""


def _source_and_credits(script, video):
    description = _paragraph(script.get("description", ""))
    body, marker, credited = description.partition("Fontes e créditos:")
    credits = _paragraph(credited if marker else video.get("credits", ""))
    if marker and video.get("credits"):
        extra = _line(video.get("credits"))
        if extra.casefold() not in credits.casefold():
            credits = "\n".join(x for x in (credits, extra) if x)
    return body.strip(), credits


def _join_limited(parts, limit, hashtags):
    # Prioritize opening/factual context over tags when a long source is provided.
    hashtag_line = " ".join("#" + tag for tag in hashtags)
    reserve = len(hashtag_line) + 2
    body = "\n\n".join(str(x).strip() for x in parts if str(x or "").strip())
    body = _clip(body, max(1, limit - reserve))
    return (body + "\n\n" + hashtag_line).strip()[:limit]


def build_seo_package(script: dict, video: dict, platform: str) -> dict:
    """Generate copy ready to paste, using only the already approved script."""
    if platform not in PLATFORMS:
        raise ValueError("Plataforma não suportada: " + platform)
    title = _line(script.get("title") or video.get("title") or "Atualização de GTA 6", 200)
    if not re.search(r"(?i)\b(?:gta\s*(?:6|vi)|grand theft auto)\b", title):
        title = "GTA 6: " + title
    title = _clip(title, 100)  # Consistent editable title limit across platforms.
    hook = _line(script.get("hook"), 160)
    body, credits = _source_and_credits(script, video)
    cta = _line(script.get("cta"), 160) or "Qual detalhe chamou mais sua atenção? Comente!"
    source = _source_url(video)
    source_line = "Referência: " + source if source else ""
    credits_line = "Créditos: " + credits if credits else ""
    hashtags = _unique([*script.get("hashtags", []), *DEFAULT_HASHTAGS[platform]],
                       5 if platform == "youtube" else 6)
    tags = _tags(script)
    primary = _line(body, 300) or title
    if platform == "youtube":
        caption = _join_limited(
            [hook, body, cta, source_line, credits_line, BRAND], CAPTION_LIMITS[platform], hashtags)
    elif platform == "tiktok":
        caption = _join_limited(
            [hook or title, _clip(primary, 320), cta, source_line, credits_line],
            CAPTION_LIMITS[platform], hashtags)
    else:
        caption = _join_limited(
            [hook or title, _clip(primary, 600), cta, source_line, credits_line, BRAND],
            CAPTION_LIMITS[platform], hashtags)
    pinned = _clip(cta, 300)
    return {
        "version": 1,
        "platform": platform,
        "language": "pt-BR",
        "brand": BRAND,
        "title": title,
        "caption": caption,
        "description": caption,
        "hashtags": hashtags,
        "tags": tags,
        "pinned_comment": pinned,
        "cover_text": _clip(hook or title, 55),
        "source_url": source,
        "source_credits": credits,
        "test_only": bool(video.get("test")),
        "mode": "manual_copy_and_paste",
        "generated_by": "deterministic_script_seo_v1",
        "notice": "Revise as alegações, os créditos e a redação antes de publicar. SEO não garante alcance.",
    }


def normalize_editor_update(payload: dict, platform: str, original: dict) -> dict:
    """Validate human changes, keeping server-side provenance fields immutable."""
    if platform not in PLATFORMS:
        raise ValueError("Plataforma não suportada.")
    title = _line(payload.get("title"), 200)
    caption = _paragraph(payload.get("caption"))
    if not title or len(title) > 100:
        raise ValueError("Informe um título de até 100 caracteres.")
    if not caption or len(caption) > CAPTION_LIMITS[platform]:
        raise ValueError(f"Legenda obrigatória: máximo de {CAPTION_LIMITS[platform]} caracteres.")
    if not isinstance(payload.get("hashtags"), list) or len(payload["hashtags"]) > 15:
        raise ValueError("Hashtags inválidas.")
    if not isinstance(payload.get("tags"), list) or len(payload["tags"]) > 30:
        raise ValueError("Palavras-chave inválidas.")
    hashtags = _unique(payload["hashtags"], 15)
    tags = [_line(s, 80) for s in payload["tags"] if _line(s, 80)]
    if sum(map(len, tags)) + len(tags) > 500:
        raise ValueError("Palavras-chave excedem 500 caracteres.")
    pinned = _line(payload.get("pinned_comment"), 300)
    cover = _line(payload.get("cover_text"), 55)
    return {**original, "title": title, "caption": caption, "description": caption,
            "hashtags": hashtags, "tags": tags,
            "pinned_comment": pinned, "cover_text": cover,
            "generated_by": "deterministic_script_seo_v1+human_review"}
