from enum import StrEnum
from urllib.parse import urlsplit, parse_qs, urlencode
import re
from pydantic import BaseModel, Field, field_validator, model_validator


class Rights(StrEnum):
    AUTHORIZED = 'AUTHORIZED'
    REFERENCE_ONLY = 'REFERENCE_ONLY'
    REVIEW_REQUIRED = 'REVIEW_REQUIRED'
    BLOCKED = 'BLOCKED'


def platform_url(value: str, profile: bool = False) -> tuple[str, str]:
    u = urlsplit(value.strip())
    host = (u.hostname or '').lower()
    if u.scheme != 'https' or u.username or u.password or u.port not in (None, 443):
        raise ValueError('Use uma URL HTTPS pública da plataforma.')
    hosts = {'youtube.com': 'youtube', 'www.youtube.com': 'youtube', 'm.youtube.com': 'youtube',
             'youtu.be': 'youtube', 'tiktok.com': 'tiktok', 'www.tiktok.com': 'tiktok',
             'instagram.com': 'instagram', 'www.instagram.com': 'instagram'}
    platform = hosts.get(host)
    if not platform:
        raise ValueError('Plataforma não suportada. Use YouTube, TikTok ou Instagram.')
    if profile:
        if not re.fullmatch(r'/(@[\w.-]+|channel/[\w-]+|[\w.-]+)/?', u.path):
            raise ValueError('URL de perfil inválida.')
        return platform, f'https://{host}{u.path.rstrip("/")}'
    if platform == 'youtube':
        vid = (u.path.strip('/') if host == 'youtu.be' else
               u.path.split('/')[-1] if u.path.startswith('/shorts/') else parse_qs(u.query).get('v', [''])[0])
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid):
            raise ValueError('ID de vídeo do YouTube inválido.')
        return platform, 'https://www.youtube.com/watch?' + urlencode({'v': vid})
    pattern = r'/@[\w.-]+/video/\d+/?' if platform == 'tiktok' else r'/(reel|p)/[\w-]+/?'
    if not re.fullmatch(pattern, u.path):
        raise ValueError('Use o link direto do vídeo, sem encurtador.')
    return platform, f'https://www.{platform}.com{u.path.rstrip("/")}/'


class ImportRequest(BaseModel):
    url: str
    rights: Rights = Rights.REFERENCE_ONLY
    evidence: str = Field(default='', max_length=2000)
    credits: str = Field(default='', max_length=1000)
    instructions: str = Field(default='', max_length=3000)
    template: str = 'gta-news'
    duration: int = Field(default=30, ge=10, le=90)
    source_kind: str = Field(default='auto',pattern='^(auto|short|video)$')

    @model_validator(mode='before')
    @classmethod
    def classify_short(cls, data):
        if isinstance(data,dict) and '/shorts/' in str(data.get('url','')):
            return {**data,'source_kind':'short'}
        return data

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        return platform_url(value)[1]

    @model_validator(mode='after')
    def authorization(self):
        if self.rights == Rights.AUTHORIZED and len(self.evidence.strip()) < 10:
            raise ValueError('Informe a evidência da autorização de reutilização.')
        return self


class ProfileRequest(BaseModel):
    url: str
    enabled: bool = True
    interval_minutes: int = Field(default=120, ge=15, le=10080)
    priority: int = Field(default=1, ge=1, le=10)

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        return platform_url(value, profile=True)[1]


class ModelRoute(BaseModel):
    model: str = ''
    fallback_model: str = ''
    max_tokens: int = Field(default=1800, ge=256, le=8000)
    vision: bool = False


class EvaluationCriterion(BaseModel):
    name: str = Field(min_length=2, max_length=90)
    description: str = Field(min_length=5, max_length=500)
    weight: float = Field(default=1.0, ge=0, le=10)
    min_score: float = Field(default=6.0, ge=0, le=10)
    enabled: bool = True


def default_evaluation_criteria() -> dict[str, EvaluationCriterion]:
    labels = [
        ('hook','Gancho','Impacto e clareza nos primeiros três segundos.'),
        ('narrative','Narrativa','Coerência, roteiro e clareza da mensagem.'),
        ('audio','Áudio','Narração inteligível, volume e ausência de falhas.'),
        ('subtitles','Legendas','Sincronização, leitura e segurança visual.'),
        ('cuts','Cortes','Precisão e continuidade dos trechos.'),
        ('rhythm','Ritmo','Fluidez e ausência de trechos mortos.'),
        ('resolution','Formato','Resolução, proporção e codecs adequados.'),
        ('duration','Duração','Duração dentro da proposta definida.'),
        ('briefing','Briefing','Aderência ao briefing do Escritor.'),
        ('originality','Originalidade','Criação própria e uso transformativo responsável.'),
        ('accuracy','Exatidão','Não inventa informações e não contradiz as fontes, sem exigir selos de verificação.'),
        ('rights','Direitos e créditos','Origem, autorizações e atribuições documentadas.'),
        ('visual_relevance','Relevância visual','Visuais realmente relacionados à narração e identificados no manifesto.'),
    ]
    return {key: EvaluationCriterion(name=name,description=desc,min_score=6.0) for key,name,desc in labels}


class Settings(BaseModel):
    channel: str = Field(default='GTA Content Studio', min_length=1, max_length=80)
    language: str = 'pt-BR'
    countries: list[str] = Field(default_factory=lambda: ['US', 'GB', 'CA', 'AU'])
    daily_limit: int = Field(default=3, ge=1, le=100)
    max_review_attempts: int = Field(default=5, ge=1, le=10)
    evaluation_criteria: dict[str, EvaluationCriterion] = Field(default_factory=default_evaluation_criteria)
    duration: int = Field(default=30, ge=10, le=90)
    search_minutes: int = Field(default=180, ge=15, le=10080)
    retention_days: int = Field(default=7, ge=1, le=365)
    approval_score: float = Field(default=8, ge=1, le=10)
    automatic: bool = False
    emergency_stop: bool = False
    configured: bool = False
    approval_mode: str = Field(default='manual', pattern='^(manual|automatic)$')
    platforms: list[str] = Field(default_factory=lambda: ['youtube', 'tiktok', 'instagram'])
    provider_url: str = 'http://host.docker.internal:11434/v1'
    routes: dict[str, ModelRoute] = Field(default_factory=lambda: {a: ModelRoute() for a in ['diretor', 'cacador', 'escritor', 'redator', 'editor', 'avaliador', 'pessoa']})
    daily_tokens: int = Field(default=999999, ge=1000, le=1000000)
    daily_cost_usd: float = Field(default=1, ge=0, le=100)
    cost_per_million: float = Field(default=0, ge=0, le=1000)
    youtube_auto: bool = False
    paused_integrations: list[str] = Field(default_factory=list)
    sample_seconds: int = Field(default=5, ge=2, le=30)
    transcription: bool = False
    postiz_url: str = ''
    postiz_auto: bool = False
    postiz_channels: dict[str, str] = Field(default_factory=dict)
    postiz_settings: dict[str, dict] = Field(default_factory=dict)
    clip_threshold_seconds: float = Field(default=45,ge=5,le=3600)
    clip_seconds: float = Field(default=10,ge=2,le=120)
    clip_min_tail_seconds: float = Field(default=3,ge=0.1,le=30)
    upload_max_mb: int = Field(default=1024,ge=1,le=4096)
    music_volume: float = Field(default=0.16,ge=0,le=0.6)
    visual_cut_seconds: float = Field(default=2.25,ge=1.5,le=3.0)
    source_min_relevance: float = Field(default=7.0,ge=0,le=10)
    source_topic_coverage: float = Field(default=0.6,ge=0,le=1)
    energetic_mode: bool = True
    # All narration must be aligned against actual audio, not estimated by phrase.
    redator_ai: bool = True
    spectator_min_score: float = Field(default=6.0, ge=0, le=10)
    auto_catalog_shorts: bool = True
    auto_download_authorized_shorts: bool = False
    max_third_party_clip_seconds: float = Field(default=4, ge=1, le=5)
    temporary_retention_days: int = Field(default=7, ge=1, le=90)
    narration_margin_seconds: float = Field(default=5.0, ge=0, le=20)
    narration_lead_seconds: float = Field(default=0.5, ge=0, le=3)

    @model_validator(mode='after')
    def narration_margin_valid(self):
        if self.narration_margin_seconds + self.narration_lead_seconds >= self.duration:
            raise ValueError('Margem da narração não pode ocupar todo o vídeo.')
        return self

    @model_validator(mode='after')
    def complete_agent_routes(self):
        for agent, origin in (('redator','escritor'),('pessoa','avaliador')):
            if agent not in self.routes and origin in self.routes:
                self.routes[agent]=self.routes[origin].model_copy(deep=True)
        return self

    @model_validator(mode='after')
    def clip_settings_valid(self):
        if self.clip_min_tail_seconds>self.clip_seconds:
            raise ValueError('Clipe mínimo final deve ser menor que o tamanho do clipe.')
        return self

    @field_validator('postiz_url')
    @classmethod
    def valid_postiz(cls, value):
        if not value:
            return value
        u = urlsplit(value)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or u.query:
            raise ValueError('URL Postiz inválida.')
        return value.rstrip('/')

    @field_validator('platforms', 'paused_integrations')
    @classmethod
    def valid_platforms(cls, value):
        if any(x not in ['youtube', 'tiktok', 'instagram'] for x in value):
            raise ValueError('Plataforma inválida')
        return list(dict.fromkeys(value))

    @field_validator('provider_url')
    @classmethod
    def valid_provider(cls, value):
        u = urlsplit(value)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or u.query:
            raise ValueError('URL de provedor inválida; use o campo de credenciais para segredos.')
        return value.rstrip('/')

    @field_validator('countries')
    @classmethod
    def valid_countries(cls, value):
        if not value or any(not re.fullmatch('[A-Z]{2}', x) for x in value):
            raise ValueError('Informe códigos de países ISO com duas letras maiúsculas.')
        return value


class Handoff(BaseModel):
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    run_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    status: str = Field(pattern='^(CONCLUIDO|FALHA|REVISAR|REPROVADO)$')
    proximo_agente: str
    resumo: str = Field(max_length=600)
    arquivos: list[str]
    dados: dict = Field(default_factory=dict)

    @field_validator('resumo')
    @classmethod
    def compact(cls, v):
        if len(v.splitlines()) > 3:
            raise ValueError('Resumo excede três linhas')
        return v


class Scene(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=120)
    narration: str = Field(min_length=1, max_length=600)
    source_id: str
    source_start: float = Field(default=0, ge=0, le=600)
    speaker: str = Field(default='dante_palma', pattern=r'^[a-z][a-z0-9_]{1,39}$')
    emotion: str = Field(default='neutro', pattern=r'^[a-z][a-z0-9_]{1,35}$')


class Script(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    hook: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=4500)
    hashtags: list[str]
    rumor: bool = False
    template: str
    duration: int = Field(ge=10, le=90)
    scenes: list[Scene] = Field(min_length=2, max_length=12)
    cta: str = Field(default='', max_length=120)
    music: str = 'none'

    @model_validator(mode='after')
    def contiguous(self):
        pos = 0
        for s in self.scenes:
            if abs(s.start - pos) > .05 or s.end <= s.start:
                raise ValueError('As cenas devem ter timestamps contínuos.')
            pos = s.end
        if abs(pos - self.duration) > .05:
            raise ValueError('Cenas não correspondem à duração.')
        if self.music != 'none':
            raise ValueError('Música requer catálogo licenciado; use none.')
        return self
