"""Dynamic GTA news style. Evidence stays internal; labels never become narration or graphics."""
from __future__ import annotations
import re

# These are display labels, not replacements for factual qualifications.
BADGES = [
    (r'(?i)\b(?:fato\s+ou\s+fake|fato\s+ou\s+(?:rumor|especula[çc][aã]o)|verdade\s+ou\s+mentira)\s*\??', 'Olha esse detalhe!'),
    (r'(?i)\b(?:confirmado\s+ou\s+n[aã]o\s+confirmado)\s*\??', 'O que está acontecendo?'),
    (r'(?i)\b(?:é\s+(?:fato|fake)\s*\??)', 'O que você achou?'),
]

def screen_copy(value: str) -> str:
    """Only remove editorial badges. Never remove context or caveats from source ledger."""
    text=str(value or '')
    for pattern,replacement in BADGES:
        text=re.sub(pattern,replacement,text)
    # Remove naked chips while preserving grammatical text.
    text=re.sub(r'(?im)^\s*(?:\[|#)?(?:FAKE|FATO|RUMOR|NÃO CONFIRMADO|CONFIRMADO)(?:\])?\s*[:—-]?\s*$', '', text)
    return re.sub(r'\s{2,}', ' ', text).strip()

WRITER_STYLE = (
    'Canal GTA 6 Brasil com notícias vibrantes, ritmo rápido e linguagem de amigo entusiasmado. '
    'Abra com a imagem/descoberta mais interessante em até 2 segundos. '
    'Frases curtas (idealmente até 14 palavras), verbos de ação, contexto essencial e uma pergunta natural no final. '
    'Não crie selos, quadros, textos ou bordões de fato/rumor/fake/confirmado. '
    'NÃO confunda entusiasmo com inventar fatos. Preserve incertezas naturalmente: '
    '"segundo a fonte", "está circulando que", sem apresentar alegações não verificadas como certezas. '
    'Não use bordões em toda cena. Varie emoções e visuais; sugerir o frame mais relevante da fonte. '
)
