---
name: transcricao-whisperx
description: Preparar timestamps palavra-a-palavra em PT-BR usando WhisperX quando disponivel, preservando Piper real e fallback de transcricao existente.
---
# Transcricao / WhisperX

## Entrada
Audio real ja gerado pelo Piper e aprovado pelo orcamento temporal do projeto; nao usar TTS estimado como substituto. Referencias: `backend/audio_timeline.py`, `backend/transcription.py` e `style_guide.json`.

## Passos
1. Verificar existencia do arquivo de audio, duracao FFprobe, idioma PT-BR e disponibilidade real da ferramenta (`python -c "import whisperx"`). Nao alterar `requirements.txt` sem autorizacao.
2. Quando WhisperX e os modelos de alinhamento estiverem **instalados localmente**, realizar ASR + forced alignment e salvar `transcript.json` com `words:[{text,start,end,confidence}]`, `language`, `method:whisperx_forced_alignment`, `source_audio`, `timebase`; gerar `.srt`.
3. Quando WhisperX estiver ausente, reutilizar `backend/transcription.py` (faster-whisper com word_timestamps) se disponivel, marcando explicitamente `method:faster_whisper_word_timestamps`. Se nenhum alinhador estiver acessivel, retornar etapa opcional indisponivel; sem fingir precisão de dois frames.
4. Validar cada intervalo: tempo em segundos, `0 <= start < end <= audio_real_duration`, ordenacao, pausas e confianca sem inventar pontuacoes.
5. Nao alterar o audio real, nem ajustar velocidade so para alinhar texto. Se a qualidade dos timestamps nao permitir legenda cinetica confiavel, usar legendas por frase ou pedir revisao.

## Saida
`transcript.json` e `subtitles.srt` relativos ao diretorio de handoff da producao, com metodo de alinhamento indicado e timecode conforme o audio real.

## Referencia publica
https://github.com/m-bain/whisperX
