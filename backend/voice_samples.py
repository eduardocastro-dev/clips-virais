"""Generate comparable real Piper samples with hashes and median-pitch estimates."""
import hashlib, json, subprocess, wave, struct, math
from pathlib import Path
from backend import core as db
from backend.personas import get_cast
from backend.media import binary, probe

PHRASE='GTA seis: vamos separar o que sabemos do que ainda é rumor.'

def rough_f0(path:Path):
    # Autocorrelation on a single 200 ms voice window; a rough measurable indicator,
    # not a certified perceptual similarity or gender classifier.
    try:
        import numpy as np
        out=subprocess.run([binary('ffmpeg'),'-v','error','-i',str(path),'-ac','1','-ar','16000','-f','s16le','-'],capture_output=True,check=True,timeout=25).stdout
        x=np.frombuffer(out,dtype=np.int16).astype(float)/32768
        for start in range(0,max(0,len(x)-4800),1600):
            frame=x[start:start+4800];energy=float(np.sqrt(np.mean(frame*frame)))
            if energy<0.012:continue
            frame=frame-frame.mean()
            lag=max(range(53,161),key=lambda j:float(np.dot(frame[:-j],frame[j:])))
            f0=16000/lag
            if 100 <= f0 <= 300:return round(f0,1)
    except Exception:
        return None
    return None

def main():
    directory=db.ROOT/'assets'/'voices'/'samples';directory.mkdir(parents=True,exist_ok=True)
    evidence=[]
    for slug,person in get_cast().items():
        model=Path(person['voice_model']);output=directory/(slug+'.wav')
        if not model.is_file():raise RuntimeError('Modelo não encontrado: '+str(model))
        args=[binary('piper'),'--model',str(model),'--length_scale',str(round(1/float(person.get('speed') or 1),3)),'--output_file',str(output)]
        proc=subprocess.run(args,input=PHRASE.encode(),capture_output=True,timeout=120)
        if proc.returncode:raise RuntimeError(f'Piper {slug}: '+proc.stderr.decode('utf-8','replace')[-800:])
        evidence.append({'personagem':slug,'modelo':str(model),'arquivo':str(output.relative_to(db.ROOT)),
          'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
          'duracao_s':float(probe(output)['format']['duration']),'f0_aproximada_hz':rough_f0(output)})
    if len(set(e['sha256'] for e in evidence))!=len(evidence):raise AssertionError('Duas amostras são idênticas!')
    (directory/'samples.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False),'utf-8')
    print(json.dumps(evidence,indent=2,ensure_ascii=False))
if __name__=='__main__':main()
