"""Licensed text-effect/font library; renders original words, never EPS sample lettering.

EPS/JPG packs are editable vector *examples*, not actual fonts. Store them for
provenance/preview and produce a local visual approximation for changing titles.
TTF/OTF files can supply the real outlines for generated titles.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from backend import core as db

LIBRARY = 'assets/text_styles'
MAX_UPLOAD = 25 * 1024 * 1024
MAX_UNPACKED = 40 * 1024 * 1024
MAX_MEMBERS = 16
FONT_EXTS = {'.ttf', '.otf'}
RIGHTS_CLASSES = {'OWNED_GENERATED', 'FREE_LICENSE', 'THIRD_PARTY'}
THEMES = {
    'california_sunset': {'top': '#FF786B', 'bottom': '#7828B4', 'outline': '#FFA83B', 'shadow': '#471276'},
    'vintage_shadow': {'top': '#FFFDF0', 'bottom': '#FFFFFF', 'outline': '#090909', 'shadow': '#080808'},
    'neon_gaming': {'top': '#22D3EE', 'bottom': '#8B5CF6', 'outline': '#101827', 'shadow': '#EB11B9'},
}


def _safe_font_bytes(data: bytes, extension: str) -> None:
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError('Arquivo de fonte vazio ou maior que 25 MB.')
    if extension == '.ttf' and data[:4] not in (b'\x00\x01\x00\x00', b'true'):
        raise ValueError('Arquivo TTF inválido.')
    if extension == '.otf' and data[:4] != b'OTTO':
        raise ValueError('Arquivo OTF inválido.')
    try:
        ImageFont.truetype(io.BytesIO(data), 36)
    except (OSError, ValueError) as exc:
        raise ValueError('Não foi possível validar os glifos da fonte.') from exc


def _preview_jpeg(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 32_000_000:
                raise ValueError('Prévia excede 32 megapixels.')
            result = image.convert('RGB')
            result.thumbnail((960, 600), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            result.save(out, 'JPEG', quality=87)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Imagem de prévia inválida.') from exc


def _pack_members(raw: bytes) -> tuple[bytes, bytes, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as pack:
            members = [x for x in pack.infolist() if not x.is_dir()]
            if len(members) > MAX_MEMBERS or not members:
                raise ValueError('ZIP precisa ter até 16 arquivos de conteúdo.')
            if sum(x.file_size for x in members) > MAX_UNPACKED:
                raise ValueError('Conteúdo descompactado excede 40 MB.')
            if any(x.flag_bits & 1 for x in members):
                raise ValueError('ZIP criptografado não é suportado.')
            previews = [x for x in members if Path(x.filename).suffix.lower() in ('.jpg', '.jpeg', '.png')]
            vectors = [x for x in members if Path(x.filename).suffix.lower() == '.eps']
            if not previews or not vectors:
                raise ValueError('O pacote de efeito deve incluir pelo menos um EPS e uma imagem JPG/PNG.')
            preview = pack.read(previews[0])
            vector = pack.read(vectors[0])
            if not vector.startswith(b'%!PS-Adobe') or b'EPSF' not in vector[:100]:
                raise ValueError('Arquivo EPS inválido.')
            if len(vector) > 14 * 1024 * 1024:
                raise ValueError('EPS grande demais.')
            return _preview_jpeg(preview), vector, 'eps'
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ValueError('Não foi possível abrir ZIP de efeito de texto.') from exc


def _font_preview(data: bytes) -> bytes:
    canvas = Image.new('RGB', (960, 400), '#101827')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(io.BytesIO(data), 74)
    text = 'GTA 6 BRASIL'
    while draw.textbbox((0, 0), text, font=font)[2] > 860 and font.size > 32:
        font = ImageFont.truetype(io.BytesIO(data), font.size - 4)
    draw.text((48, 140), text, font=font, fill='#FFFDF0', stroke_width=3, stroke_fill='#8B5CF6')
    out = io.BytesIO()
    canvas.save(out, 'JPEG', quality=88)
    return out.getvalue()


def import_style(*, name: str, filename: str, content: bytes, source_class: str,
                 evidence: str, theme: str) -> dict:
    name = re.sub(r'\s+', ' ', str(name or '')).strip()[:100]
    evidence = str(evidence or '').strip()
    if not name:
        raise ValueError('Informe o nome do efeito ou da fonte.')
    if len(evidence) < 10 or len(evidence) > 2000:
        raise ValueError('Informe a licença e a permissão de uso (10 a 2000 caracteres).')
    if source_class not in RIGHTS_CLASSES:
        raise ValueError('Origem de licença inválida.')
    if theme not in THEMES:
        raise ValueError('Paleta de efeito inválida.')
    if not content or len(content) > MAX_UPLOAD:
        raise ValueError('O upload deve ter até 25 MB.')
    ext = Path(filename or '').suffix.lower()
    if ext == '.zip':
        preview, vector, kind = _pack_members(content)
        suffix = '.eps'
        asset = vector
        font = None
    elif ext in FONT_EXTS:
        _safe_font_bytes(content, ext)
        preview = _font_preview(content)
        kind = 'font'
        suffix = ext
        asset = content
        font = True
    else:
        raise ValueError('Envie um ZIP contendo EPS/JPG ou uma fonte TTF/OTF.')
    asset_id = db.uid()
    folder = db.ROOT / LIBRARY / asset_id
    folder.mkdir(parents=True, exist_ok=False)
    relative = Path(LIBRARY) / asset_id
    asset_file = relative / ('original' + suffix)
    preview_file = relative / 'preview.jpg'
    try:
        (db.ROOT / asset_file).write_bytes(asset)
        (db.ROOT / preview_file).write_bytes(preview)
        metadata = {'kind':kind, 'theme':theme, 'preview_path':str(preview_file),
                    'font_path':str(asset_file) if font else None,
                    'vector_path':str(asset_file) if kind == 'eps' else None,
                    'source_name':Path(filename).name[:200],
                    'rendering':'font_glyphs' if font else 'original_dynamic_text_approximation'}
        now = time.time()
        db.execute("""INSERT INTO assets
            (id,kind,source_id,url,title,channel,source_class,rights_status,evidence,path,
             status,metadata,created,updated,category,tags,active,sha256,media_type,size_bytes)
            VALUES (:id,'text_style',:source,'',:title,'',:source_class,'AUTHORIZED',:evidence,:path,
                    'READY',:metadata,:now,:now,'estilo de texto','[]',1,:sha,'text_style',:size)""",
            {'id':asset_id,'source':'text-style:'+asset_id,'title':name,'source_class':source_class,
             'evidence':evidence,'path':str(asset_file),'metadata':json.dumps(metadata),
             'now':now,'sha':hashlib.sha256(asset).hexdigest(),'size':len(asset)})
    except Exception:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return {'id':asset_id, 'title':name, 'kind':kind, 'theme':theme, 'ready':True}


def list_styles() -> dict:
    current = db.get_setting('text_style_active', '')
    rows = db.rows("SELECT id,title,source_class,rights_status,evidence,metadata,created,status "
                   "FROM assets WHERE kind='text_style' ORDER BY created DESC")
    items = []
    for row in rows:
        meta = json.loads(row['metadata'] or '{}')
        items.append({'id':row['id'], 'title':row['title'],
                      'kind':meta.get('kind'), 'theme':meta.get('theme'),
                      'preview_available':bool(meta.get('preview_path')),
                      'source_class':row['source_class'], 'rights_status':row['rights_status'],
                      'license_evidence':row['evidence'], 'active':current == row['id'],
                      'rendering':meta.get('rendering'), 'status':row['status']})
    return {'items':items, 'active_id':current}


def _licensed_row(asset_id: str):
    rows = db.rows("SELECT * FROM assets WHERE id=:id AND kind='text_style' AND "
                   "rights_status='AUTHORIZED' AND status='READY' AND active=1",
                   {'id':asset_id})
    if not rows or not rows[0]['evidence'] or len(rows[0]['evidence']) < 10:
        raise ValueError('Estilo sem licença comprovada ou desativado.')
    row = rows[0]
    file = db.safe_file(row['path'])
    if not file.is_relative_to((db.ROOT / LIBRARY).resolve()):
        raise ValueError('Arquivo de texto fora da biblioteca.')
    meta = json.loads(row['metadata'] or '{}')
    if meta.get('theme') not in THEMES:
        raise ValueError('Tema do efeito inválido.')
    if meta.get('kind') == 'font' and file.suffix.lower() not in FONT_EXTS:
        raise ValueError('Extensão da fonte não permitida.')
    if meta.get('kind') == 'eps' and file.suffix.lower() != '.eps':
        raise ValueError('Modelo vetorial inválido.')
    return row, meta


def activate(asset_id: str) -> dict:
    _licensed_row(asset_id)
    db.put_setting('text_style_active', asset_id)
    return {'active_id':asset_id}


def deactivate() -> dict:
    db.put_setting('text_style_active', '')
    return {'active_id':''}


def active_style():
    selected = db.get_setting('text_style_active', '')
    if not selected:
        return None
    row, meta = _licensed_row(selected)
    return {'id':row['id'], **meta}


def preview(asset_id: str) -> Path:
    rows = db.rows("SELECT metadata FROM assets WHERE id=:id AND kind='text_style'", {'id':asset_id})
    if not rows:
        raise ValueError('Estilo de texto não encontrado.')
    path = json.loads(rows[0]['metadata'] or '{}').get('preview_path', '')
    file = db.safe_file(path)
    if not file.is_relative_to((db.ROOT / LIBRARY).resolve()) or file.suffix != '.jpg':
        raise ValueError('Prévia indisponível.')
    return file


def _blend_rgb(a: str, b: str, ratio: float) -> tuple[int,int,int,int]:
    x = tuple(bytes.fromhex(a.lstrip('#')))
    y = tuple(bytes.fromhex(b.lstrip('#')))
    return tuple(round(x[i] * (1 - ratio) + y[i] * ratio) for i in range(3)) + (255,)


def render_hook(text: str, target: Path, selected: dict) -> Path:
    """Render *new* words with licensed font or fallback; never put EPS sample text in video."""
    palette = THEMES[selected['theme']]
    canvas = Image.new('RGBA', (1080, 1920), (0,0,0,0))
    font_path = selected.get('font_path')
    if font_path:
        font_file = db.safe_file(font_path)
        if not font_file.is_relative_to((db.ROOT / LIBRARY).resolve()):
            raise ValueError('Fonte fora da biblioteca.')
    else:
        font_file = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    text = re.sub(r'\s+', ' ', str(text or '')).strip()[:120]
    if not text:
        raise ValueError('O gancho da cena não possui texto.')
    draw = ImageDraw.Draw(canvas)
    best = None
    for size in range(100, 37, -4):
        try:
            font = ImageFont.truetype(str(font_file), size)
        except OSError:
            font = ImageFont.truetype('DejaVuSans-Bold.ttf', size)
        words = text.split(' ')
        lines = []
        current = ''
        for word in words:
            attempt = (current + ' ' + word).strip()
            if current and draw.textbbox((0, 0), attempt, font=font, stroke_width=0)[2] > 930:
                lines.append(current)
                current = word
            else:
                current = attempt
        if current:
            lines.append(current)
        if len(lines) <= 3:
            best = font, lines
            break
    if best is None:
        raise ValueError('Texto do gancho muito longo para o efeito; encurte o título.')
    font, lines = best
    line_height = round(font.size * 1.25)
    y = 290
    for line in lines:
        bbox = draw.textbbox((0,0), line, font=font, stroke_width=0)
        width = bbox[2] - bbox[0]
        x = (1080 - width) // 2 - bbox[0]
        offset = 13 if selected['theme'] == 'vintage_shadow' else 8
        draw.text((x+offset, y+offset), line, font=font, fill=palette['shadow'],
                  stroke_width=8, stroke_fill=palette['shadow'])
        draw.text((x,y), line, font=font, fill=palette['outline'], stroke_width=8,
                  stroke_fill=palette['outline'])
        mask = Image.new('L', canvas.size, 0)
        ImageDraw.Draw(mask).text((x, y), line, font=font, fill=255)
        gradient = Image.new('RGBA', canvas.size, (0,0,0,0))
        gd = ImageDraw.Draw(gradient)
        for py in range(max(0,y-5), min(1920,y+line_height+10)):
            t = max(0.0, min(1.0, (py-y)/max(1,line_height)))
            gd.line((0, py,1080, py),fill=_blend_rgb(palette['top'],palette['bottom'],t))
        canvas.paste(gradient, (0,0), mask)
        y += line_height
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, format='PNG')
    return target
