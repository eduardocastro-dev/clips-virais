import json
from pathlib import Path
from PIL import Image
import pytest
from backend import core as db, pipeline, visual_renderer, media
from backend.contracts import Script, Scene


def test_template_catalog_has_dynamic_fields():
    catalog_path = Path(__file__).resolve().parent.parent / 'templates' / 'catalog.json'
    assert catalog_path.is_file()
    catalog = json.loads(catalog_path.read_text('utf-8'))
    assert isinstance(catalog, dict)
    assert len(catalog) >= 6

    expected_keys = {
        'badge', 'badge_color', 'pacing', 'cut_seconds',
        'animation_style', 'highlight_color', 'editorial_guideline'
    }
    for tid, t in catalog.items():
        assert expected_keys.issubset(t.keys()), f"Template {tid} faltando campos"
        assert t['cut_seconds'] > 0
        assert len(t['badge']) > 0


def test_director_choose_template():
    # URGENTE / NOTÍCIAS OFICIAIS -> gta-news
    assert pipeline.director_choose_template({'title': 'URGENTE: Rockstar confirma data oficial de GTA 6'}) == 'gta-news'
    assert pipeline.director_choose_template({'title': 'Anúncio confirmado com nova data de lançamento oficial'}) == 'gta-news'

    # TEORIA & VAZAMENTO -> gta-theory
    assert pipeline.director_choose_template({'title': 'Vazamento massivo revela mapa e código fonte de GTA 6'}) == 'gta-theory'
    assert pipeline.director_choose_template({'title': 'Apuração dos bastidores e documentos secretos de desenvolvimento'}) == 'gta-theory'

    # COMPARAÇÃO -> gta-comparison
    assert pipeline.director_choose_template({'title': 'Gráficos de GTA 6 comparados lado a lado com RDR2'}) == 'gta-comparison'

    # ANÁLISE / FATOS / DETALHES -> gta-facts
    assert pipeline.director_choose_template({'title': '20 segredos e easter eggs escondidos no Trailer 2 de GTA 6'}) == 'gta-facts'

    # SHOWCASE VISUAL -> gta-cinematic
    assert pipeline.director_choose_template({'title': 'Visual cinematográfico e iluminação com ray tracing no motor gráfico'}) == 'gta-cinematic'

    # REAÇÃO / DEBATE / HYPE -> gta-reaction
    assert pipeline.director_choose_template({'title': 'A comunidade gamer está debatendo a polêmica do preço'}) == 'gta-reaction'
    assert pipeline.director_choose_template({'title': 'Fãs entram em revolta com possível adiamento de GTA 6'}) == 'gta-reaction'

    # FALLBACK -> gta-news
    assert pipeline.director_choose_template({'title': 'Vídeo comum sem palavras chave'}) == 'gta-news'


def test_visual_title_card_generation(tmp_path):
    card_path = tmp_path / 'test_card.png'
    visual_renderer.title_card(
        text='ROCKSTAR CONFIRMA NOVO TRAILER COM DATA OFICIAL',
        source='twitter.com/RockstarGames',
        path=card_path,
        badge='URGENTE'
    )
    assert card_path.is_file()
    with Image.open(card_path) as img:
        assert img.size == (860, 680)
        assert img.mode == 'RGBA'


def test_visual_style_screenshot_card(tmp_path):
    raw_img = tmp_path / 'raw_shot.png'
    Image.new('RGB', (640, 360), color=(100, 150, 200)).save(raw_img)

    out_card = tmp_path / 'styled_card.png'
    visual_renderer.style_screenshot_card(
        img_path=raw_img,
        out_path=out_card,
        source_label='https://ign.com/articles/gta-6-preview',
        badge='FONTE ORIGINAL'
    )
    assert out_card.is_file()
    with Image.open(out_card) as img:
        assert img.size == (860, 660)
        assert img.mode == 'RGBA'


def test_subtitles_include_badge_and_karaoke(tmp_path):
    script = Script(
        title='Teste',
        description='Descrição de teste do vídeo',
        hashtags=['#gta6', '#rockstar'],
        hook='GTA 6 vai mudar tudo na indústria dos games!',
        cta='Comente o que você achou',
        angle='curiosidade',
        template='gta-news',
        scenes=[
            Scene(source_id='v1', text='Primeira cena', narration='Rockstar Games revela data oficial.', start=0.0, end=5.0, speaker='dante_palma', emotion='excited'),
            Scene(source_id='v1', text='Segunda cena', narration='Trailer de GTA 6 bate recordes.', start=5.0, end=11.0, speaker='dante_palma', emotion='neutral')
        ],
        duration=11.0
    )
    sub_path = tmp_path / 'sub.ass'
    style = {
        'font_size': 54,
        'badge': 'URGENTE',
        'highlight_color': '&H00F4FF&'
    }
    transcript = {
        'words': [
            {'text': 'Rockstar', 'start': 0.1, 'end': 0.6},
            {'text': 'Games', 'start': 0.7, 'end': 1.1},
            {'text': 'revela', 'start': 1.2, 'end': 1.6},
            {'text': 'GTA', 'start': 4.1, 'end': 4.5},
            {'text': '6', 'start': 4.6, 'end': 4.9}
        ]
    }
    media.subtitles(script, style, sub_path, transcript=transcript)
    assert sub_path.is_file()
    content = sub_path.read_text('utf-8')
    assert 'URGENTE' in content
    assert 'Style: Badge' in content
    assert 'GTA' in content
