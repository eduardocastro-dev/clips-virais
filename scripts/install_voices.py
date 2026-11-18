"""Install distinct PT-BR Piper voice weights from official rhasspy repository.
No model is claimed to be ready until all three files have been downloaded and validated.
Run on host: python scripts/install_voices.py; then rebuild containers.
"""
from __future__ import annotations
import json, pathlib, shutil, urllib.request, tempfile, hashlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
MODEL_DIR=ROOT/'models';MODEL_DIR.mkdir(exist_ok=True,parents=True)
VOICES={'dante_palma':('cadu','medium'),'lia_varela':('jeff','medium'),'caio_rivas':('faber','medium')}
BASE='https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR'

def fetch(url: str,dest: pathlib.Path):
    if dest.is_file() and dest.stat().st_size>1000:return
    with tempfile.NamedTemporaryFile(prefix=dest.name+'.',suffix='.part',dir=dest.parent,delete=False) as out:
        temporary=pathlib.Path(out.name)
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'GTAStudio-VoiceInstaller/1.0'}),timeout=150) as remote:
                shutil.copyfileobj(remote,out,1024*1024)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(dest)

def main():
    license_lines=['# Licenças das vozes PT-BR (Piper)','',
        'O repositório de modelos declara licença MIT; os três cartões de modelo indicam dataset CC0.',
        'CC0 permite uso comercial. Confirme os termos da versão publicada antes de redistribuir os pesos.','']
    for slug,(name,quality) in VOICES.items():
        stem=f'pt_BR-{name}-{quality}'
        folder=f'{BASE}/{name}/{quality}/'
        voice=MODEL_DIR/(stem+'.onnx');config=MODEL_DIR/(stem+'.onnx.json')
        card=MODEL_DIR/(stem+'.MODEL_CARD')
        if not card.is_file():
            # the card is deliberately not hidden in user data, it travels with the model
            urllib.request.urlretrieve(folder+'MODEL_CARD',str(card))
        content=card.read_text('utf-8')
        if 'License: CC0' not in content:
            raise RuntimeError(f'Licença CC0 não confirmada para {stem}: {card}')
        fetch(folder+voice.name,voice)
        fetch(folder+config.name,config)
        if voice.stat().st_size<1000000:raise RuntimeError(f'Arquivo ONNX incompleto: {voice}')
        info=json.loads(config.read_text('utf-8'))
        if not isinstance(info,dict) or 'phoneme_type' not in info:raise RuntimeError(f'Config JSON inválida: {config}')
        digest=hashlib.sha256(voice.read_bytes()).hexdigest()
        license_lines += [f'## {slug}: {stem}',f'- Origem: {folder}',f'- Dataset: CC0, conforme MODEL_CARD ({card.name})',
            f'- Arquivo: {voice.name}',f'- SHA-256: `{digest}`','- Uso comercial: permitido pelo CC0 declarado; mantenha atribuições do software e avalie condições adicionais da distribuição.','']
        print(f'Instalada: {stem} ({voice.stat().st_size//1048576} MiB)')
    destination=ROOT/'assets'/'voices';destination.mkdir(parents=True,exist_ok=True)
    (destination/'LICENSES.md').write_text('\n'.join(license_lines),'utf-8')
    print('Todas as vozes instaladas. Execute: docker compose up -d --build api worker')
if __name__=='__main__': main()
