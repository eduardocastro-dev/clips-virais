"""Bounded WhisperX analysis keeps aligned times in the source VOD clock."""
from __future__ import annotations
import json
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import live_clip_render as render


def _wav(path: Path, seconds: int):
    # Streaming write: never allocate a complete 20+ MB test audio buffer.
    with wave.open(str(path),'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        for _ in range(seconds):
            output.writeframesraw(b'\0' * 32000)


def test_windows_ignore_intro_and_distribute_analysis_across_long_live():
    duration=4*3600
    levels=[-34.] * duration
    windows=render._analysis_windows(levels,duration)
    assert len(windows)==render.MAX_ANALYSIS_WINDOWS
    assert all(start>=300 and end<=duration for start,end in windows)
    assert all(end-start<=render.ANALYSIS_WINDOW_SECONDS for start,end in windows)
    assert all(a[1]<=b[0] for a,b in zip(windows,windows[1:]))
    assert windows[0][0] < duration/4
    assert windows[-1][0]>duration*.75
    assert sum(end-start for start,end in windows)<=1440


def test_sampled_windows_reject_short_post_intro_audio():
    assert render._analysis_windows([-25.]*310,310)==[]
    assert render._analysis_windows([-25.]*340,340)==[(300,340)]


def test_alignment_offsets_real_times_and_rejects_unaligned_words():
    item=render._offset_alignment({
        'segments':[{'start':10,'end':36,'text':'Olha o momento interessante',
          'words':[{'word':'Olha','start':11,'end':11.5,'score':.97},
                   {'word':'fim','start':35,'end':35.5,'score':.91},
                   {'word':'sem tempo'}]}]},1200,1320)
    assert len(item['segments'])==1
    assert item['segments'][0]['start']==1210
    assert item['segments'][0]['end']==1236
    assert [w['start'] for w in item['words']]==[1211,1235]
    assert [w['end'] for w in item['words']]==[1211.5,1235.5]


def test_whisperx_analyzes_only_windows_once_and_caches_absolute_timestamps(
        monkeypatch,tmp_path):
    path=tmp_path/'audio-16k.wav'
    _wav(path,660)
    calls={'load_model':0,'align_model':0,'transcribe':0,'align':0,'load_audio':0}

    class Model:
        def transcribe(self,audio,batch_size,language):
            calls['transcribe']+=1
            assert batch_size==8 and language=='pt'
            return {'language':'pt','segments':[{'start':9.,'end':36.,
              'text':'Olha esse destaque incrível que aconteceu aqui',
              'words':[{'word':'Olha','start':10,'end':10.5,'score':.9},
                       {'word':'incrível','start':33,'end':33.5,'score':.9}]}]}

    def load_model(*args,**kwargs):
        calls['load_model']+=1
        assert kwargs['compute_type']=='int8'
        return Model()

    def load_align_model(*args,**kwargs):
        calls['align_model']+=1
        return object(),{'mock':'metadata'}

    def load_audio(filename):
        calls['load_audio']+=1
        assert Path(filename).exists()
        with wave.open(filename,'rb') as chunk:
            assert chunk.getnframes()<=render.ANALYSIS_WINDOW_SECONDS*16000
        return object()

    def align(segments,*args,**kwargs):
        calls['align']+=1
        assert kwargs['return_char_alignments'] is False
        return {'segments':segments}

    monkeypatch.setitem(sys.modules,'whisperx',SimpleNamespace(
        load_model=load_model,load_align_model=load_align_model,
        load_audio=load_audio,align=align))
    monkeypatch.setenv('WHISPERX_DEVICE','cpu')
    volumes=[-24.]*660
    result=render._whisperx_words(path,tmp_path,volumes)
    assert result['method']=='whisperx_forced_alignment'
    assert result['scope']=='sampled'
    assert result['source_duration']==660
    assert len(result['windows'])==3
    assert calls=={'load_model':1,'align_model':1,'transcribe':3,'align':3,'load_audio':3}
    assert all(w['start']>=300 for w in result['words'])
    assert result['words'][0]['start']==result['windows'][0][0]+10
    assert result['words'][-1]['start']==result['windows'][-1][0]+33
    assert not list(tmp_path.glob('analysis-window-*.wav'))
    again=render._whisperx_words(path,tmp_path,volumes)
    assert result==again
    assert calls['transcribe']==3
    cached=json.loads((tmp_path/'transcript.json').read_text('utf-8'))
    assert cached['analyzed_seconds']==360


def test_partial_whisperx_checkpoint_resume_skips_completed_windows(
        monkeypatch,tmp_path):
    path=tmp_path/'audio-16k.wav'
    _wav(path,660)
    counter={'calls':0,'fail_once':True}

    class Model:
        def transcribe(self,audio,**kwargs):
            counter['calls']+=1
            if counter['calls']==2 and counter['fail_once']:
                counter['fail_once']=False
                raise RuntimeError('simulated interruption')
            return {'language':'pt','segments':[{'start':5,'end':32,
                'text':'Reação interessante da live com muitas palavras',
                'words':[{'word':'Reação','start':6,'end':6.5,'score':.9}]}]}

    fake=SimpleNamespace(
        load_model=lambda *args,**kwargs:Model(),
        load_align_model=lambda **kwargs:(object(),{}),
        load_audio=lambda path:object(),
        align=lambda segments,*args,**kwargs:{'segments':segments})
    monkeypatch.setitem(sys.modules,'whisperx',fake)
    monkeypatch.setenv('WHISPERX_DEVICE','cpu')
    volumes=[-22.]*660
    with pytest.raises(RuntimeError,match='interruption'):
        render._whisperx_words(path,tmp_path,volumes)
    assert counter['calls']==2
    assert len(list(tmp_path.glob('transcript-window-*.json')))==1
    result=render._whisperx_words(path,tmp_path,volumes)
    assert counter['calls']==4  # second + third; first restored from checkpoint
    assert len(result['windows'])==3
    assert all(item['start']>=300 for item in result['segments'])
