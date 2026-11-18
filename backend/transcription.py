"""Bounded subprocess entry point for local Whisper work; parent enforces wall-clock timeout."""
import json
import os
import sys
from backend import core as db


def main():
    from faster_whisper import WhisperModel
    source=db.safe_file(sys.argv[1])
    target=db.Path(sys.argv[2]).resolve()
    if not target.is_relative_to((db.ROOT/'cache').resolve()):
        raise ValueError('Transcript destination outside cache')
    model=WhisperModel(os.getenv('WHISPER_MODEL','small'),device='cpu',compute_type='int8',download_root=str(db.ROOT/'cache/whisper'))
    segments,info=model.transcribe(str(source),language='pt',word_timestamps=True,vad_filter=True)
    words=[{'start':w.start,'end':w.end,'text':w.word.strip()} for segment in segments for w in (segment.words or [])]
    db.atomic(target,json.dumps({'language':info.language,'words':words,'text':' '.join(w['text'] for w in words)},ensure_ascii=False))


if __name__=='__main__':
    main()
