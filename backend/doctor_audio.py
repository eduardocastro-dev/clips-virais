"""Read-only dependency diagnosis: python, PyAV, Whisper, FFmpeg and exact traceback."""
import importlib.metadata, inspect, json, shutil, subprocess, sys
from backend import core as db

def main():
    print('Python:',sys.version.replace('\n',' '),'executable:',sys.executable)
    for pkg in ('av','faster-whisper','piper-tts','ctranslate2'):
        try:print(pkg,importlib.metadata.version(pkg))
        except importlib.metadata.PackageNotFoundError:print(pkg,'NÃO INSTALADO')
    try:
        import av
        print('PyAV file:',av.__file__)
        try:print('av.open signature:',inspect.signature(av.open))
        except (ValueError,TypeError):pass
    except ImportError:pass
    for binary in ('ffmpeg','ffprobe'):
        program=shutil.which(binary)
        if program:
            p=subprocess.run([binary,'-version'],capture_output=True,text=True,timeout=10)
            print(p.stdout.splitlines()[0] if p.stdout else binary+' failed')
        else:print(binary,'NÃO DISPONÍVEL')
    log=db.ROOT/'logs'/'media-last-error.log'
    print('Log:',log,'existe:',log.is_file())
    if log.is_file():
        print('----- TRACEBACK REGISTRADO (completo) -----')
        print(log.read_text('utf-8',errors='replace')[-24000:])
    else:print('Log do erro original não consta neste container.')
if __name__=='__main__':main()
