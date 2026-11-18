"""Original fictional hosts; artwork is only attached after the user chooses a persona."""
from backend import core as db
import os
import json
import shutil
from pathlib import Path

PRESETS={
 'nico_neon':{
  'name':'Nico Neon','look':'Topete preto em espiral, óculos âmbar retangulares, jaqueta turquesa sobre camiseta coral, anel prateado, estética de rádio noturno de Miami',
  'personality':'Galã exagerado, apresentador de rádio fictício, vaidoso, caloroso, autoconfiança cômica sem ridicularizar pessoas',
  'voice':'grave, pausada, PT-BR, humor seco e tom radiofônico',
  'catchphrases':['O sinal de Vice City está no ar!','Acenda o neon e confira a fonte.','Meu penteado é certeza; esse rumor, ainda não.','A cidade fala, mas quem confirma é a evidência.','Aperta o cinto, mas segura a teoria.','Nico na frequência, fatos na pista.'],
  'opening':'O sinal de Vice City está no ar! Aqui é Nico Neon.',
  'closing':'Nico na frequência, fatos na pista. Até a próxima!',
  'never':['Nunca declarar rumor como fato','Nunca imitar personagens conhecidos','Nunca prometer vazamentos ou gameplay comprovada','Nunca usar material sem autorização'],
 },
 'dante_palma':{
  'name':'Dante Palma','look':'Cabelo volumoso castanho ondulado, óculos espelhados azuis, camisa floral noturna e paletó creme, microfone retrô',
  'personality':'Locutor satírico, sofisticado demais para a própria estação, amistoso e irônico',
  'voice':'barítono relaxado, compassado, PT-BR',
  'catchphrases':['Palma na pista, notícia na mesa.','Meu paletó brilha, a fonte tem que brilhar também.','O radar não para!','Pisa leve na teoria!','Fala a cidade, confere o Dante.'],
  'opening':'Boa noite, asfalto brilhante! Dante Palma na sua frequência.',
  'closing':'Eu fico com o neon; você fica com os fatos. Até já!',
  'never':['Nunca afirmar rumor como fato','Nunca representar material não autorizado como próprio','Nunca copiar bordões de personagens de TV'],
 },
 'vito_onda':{
  'name':'Vito Onda','look':'Topete ruivo escuro em formato de onda, óculos pretos circulares, jaqueta violeta com patch de cassete, gravata aberta',
  'personality':'Cronista hiperconfiante de uma rádio clandestina fictícia, humor absurdo e timing pausado',
  'voice':'grave aveludada, cadenciada, PT-BR',
  'catchphrases':['Onda alta, informação limpa.','O rumor acelera; a prova freia.','Vice City não dorme, meu topete também não.','Sintonize o caos, preserve os fatos.','Se é teoria, vai com etiqueta.'],
  'opening':'Sintonizou? Vito Onda invade a noite neon.',
  'closing':'Mantenha o radar ligado. Vito Onda, câmbio final.',
  'never':['Nunca imitar personagens de outras obras','Nunca tratar rumores como confirmações','Nunca usar conteúdo sem licença'],
 },
}

# Full cast: these are independent fictional GTA news characters, not copyrighted likenesses.
PRESETS['dante_palma'].update(role='apresentador',style='confiante, levemente vaidoso, humor seco',
    speed=0.96,pauses='pausas suaves antes de revelações',phrases=['Eis o que sabemos.','Olha o detalhe que escapou!'])
PRESETS['lia_varela']={
    'name':'Lia Varela','role':'analista',
    'look':'Cabelo preto curto com mecha lateral violeta, óculos discretos, jaqueta azul-marinho e camiseta branca, iluminação de estúdio Miami',
    'personality':'Analista calma e curiosa; explica contexto e detalhes escondidos com humor discreto e linguagem acessível.',
    'voice':'PT-BR médio-grave, serena, velocidade moderada, pausas em dados e datas',
    'speed':0.92,'pauses':'naturais entre os argumentos',
    'catchphrases':['Vamos separar as coisas.','O que a fonte diz?'],
    'opening':'Olha o detalhe que quase passou despercebido!','closing':'Agora me conta o que você achou.',
    'never':['Não chama rumor de confirmação','Não finge ter visto imagens não fornecidas','Não copia bordões ou vozes reais'],
}
PRESETS['caio_rivas']={
    'name':'Caio Rivas','role':'reporter',
    'look':'Cabelo castanho curto, óculos esportivos escuros, camisa coral com jaqueta de tecido técnico, gravador portátil',
    'personality':'Repórter ágil, objetivo e curioso, com humor observacional sem exageros.',
    'voice':'PT-BR claro, ritmo mais rápido, com pausas breves em fatos importantes',
    'speed':1.05,'pauses':'curtas entre notícias',
    'catchphrases':['Chegou agora no radar.','Olha o que chegou no radar!'],
    'opening':'A notícia acaba de entrar no radar.','closing':'Até a próxima atualização!',
    'never':['Não afirma boatos como notícias','Não inventa números','Não imita personagens ou celebridades'],
}


VOICE_MODELS={'dante_palma':'/models/pt_BR-cadu-medium.onnx',
 'lia_varela':'/models/pt_BR-jeff-medium.onnx',
 'caio_rivas':'/models/pt_BR-faber-medium.onnx'}

def get_cast():
    """Dossiers for all three speakers, with safe per-host overrides."""
    global_settings=db.get_setting('cast',{}) or {}
    # One-time migration of the v6 default: all three were left pointing to Cadu.
    # Preserve intentional custom voices and run only when new models are installed.
    old_voices=[global_settings.get(key,{}).get('voice_model') for key in ('dante_palma','lia_varela','caio_rivas')]
    if len(set(old_voices))==1 and old_voices[0] in ('/models/pt_BR-cadu-medium.onnx','/models/pt_BR-faber-medium.onnx') \
        and all(Path(path).is_file() for path in VOICE_MODELS.values()):
        for key,voice in VOICE_MODELS.items():
            global_settings.setdefault(key,{})['voice_model']=voice
        db.put_setting('cast',global_settings)
    # First boot: copy supplied original reference art into bind-mounted /assets,
    # without overwriting art the creator has added or modified.
    templates=Path(__file__).resolve().parent.parent/'templates'/'personas'
    # Never seed the old simplified v7 avatar.png artwork.
    # High-resolution original bust (not an enlarged 256px sprite). User art
    # takes precedence; never overwrite an existing file in the bind mount.
    portrait=db.ROOT/'assets'/'personas'/'dante_palma'/'portrait-quality.png'
    portrait_source=templates/'dante_palma'/'portrait-quality.png'
    if not portrait.exists() and portrait_source.is_file():
        portrait.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(portrait_source,portrait)
    result={}
    for key in ('dante_palma','lia_varela','caio_rivas'):
        original=PRESETS[key]
        # V8 does not seed SVG sprites into production. Creator artwork is imported explicitly.
        override=global_settings.get(key,{})
        # Default portraits are generated assets bundled with the project.
        auto=f'assets/personas/{key}/avatar.png'
        high_quality=f'assets/personas/{key}/portrait-quality.png'
        avatar=override.get('image_path') or (high_quality if (db.ROOT/high_quality).is_file() else auto if (db.ROOT/auto).is_file() else '')
        manifest=db.ROOT/'assets'/'personas'/key/'expressions'/'manifest.json'
        try:
            production_quality=json.loads(manifest.read_text('utf-8')).get('quality')=='creator_supplied_high_resolution'
        except (OSError,ValueError):production_quality=False
        production_ready=production_quality or (key=='dante_palma' and (db.ROOT/high_quality).is_file())
        if not production_ready:avatar=''  # don't show v7 SVG placeholder as cast reference
        voice=override.get('voice_model') or VOICE_MODELS[key]
        result[key]={**original, **{k:v for k,v in override.items() if k in (
            'name','look','personality','voice','voice_model','speed','opening','closing','image_path','catchphrases','never')},
            'selected':key,'image_path':avatar,'voice_model':voice,'production_ready':production_ready,
            'image_mtime_ns':(db.ROOT/avatar).stat().st_mtime_ns if avatar and (db.ROOT/avatar).is_file() else 0}
    return result

def get_persona():
    current=db.get_setting('persona',{})
    selected=current.get('selected','dante_palma')
    base=PRESETS.get(selected,PRESETS['dante_palma'])
    result={**base, **current.get('overrides',{}), 'selected':selected,
            'image_path':current.get('image_path',''), 'voice_model':current.get('voice_model','')}
    if selected in get_cast():
        auto=get_cast()[selected]
        result['image_path']=result['image_path'] or auto.get('image_path','')
        result['voice_model']=result['voice_model'] or auto.get('voice_model','')
    return result


def expression_file(speaker: str, emotion: str, previous: str | None = None) -> tuple[Path,str]:
    """Resolve a genuine RGBA asset, avoiding immediate repetition and preserving original."""
    if speaker not in ('dante_palma','lia_varela','caio_rivas'):
        raise ValueError('Personagem desconhecido')
    folder=db.ROOT/'assets'/'personas'/speaker/'expressions'
    manifest_file=folder/'manifest.json'
    if not manifest_file.is_file():
        get_cast()
        if not manifest_file.is_file():
            portrait=db.ROOT/'assets'/'personas'/speaker/'portrait-quality.png'
            if speaker=='dante_palma' and portrait.is_file():
                return portrait,'retrato_qualidade_unico'
            raise ValueError('Nenhuma galeria de poses de qualidade importada para '+speaker)
    manifest=json.loads(manifest_file.read_text('utf-8'))
    entries={entry['emotion']:entry for entry in manifest['images'] if entry.get('active',True)}
    if emotion not in entries or emotion==previous:
        emotion='neutro' if previous!='neutro' else 'feliz'
    quality=manifest.get('quality')=='creator_supplied_high_resolution'
    if not quality:
        portrait=db.ROOT/'assets'/'personas'/speaker/'portrait-quality.png'
        if speaker=='dante_palma' and portrait.is_file():
            return portrait,'retrato_qualidade_unico'
        raise ValueError('Ilustrações simplificadas não são usadas em produção. Importe 24 PNGs individuais de qualidade para '+speaker)
    entry=entries.get(emotion) or entries.get('neutro')
    if not entry:raise ValueError('Nenhuma pose ativa para '+speaker)
    candidate=(folder/entry['file']).resolve()
    if not candidate.is_relative_to(folder.resolve()) or not candidate.is_file():
        raise ValueError('Pose ausente: '+str(candidate))
    return candidate,emotion
