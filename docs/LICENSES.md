# Dependências e licenças

Consulta aos metadados públicos de PyPI e npm registrada em `licenses-observed.json`; reproduza com `python scripts/licenses.py`. O arquivo registra a versão dos metadados consultados, que pode diferir das versões fixadas nos manifests. Os manifests e lockfile definem as versões executadas.

| Componente | Licença declarada | Uso |
|---|---|---|
| FastAPI, SQLAlchemy, Pydantic Settings | MIT | API, contratos, persistência |
| Uvicorn, HTTPX | BSD-3-Clause | servidor e HTTP |
| Cryptography | Apache-2.0 ou BSD-3-Clause | segredos Fernet |
| yt-dlp | Unlicense (dependências têm licenças próprias) | download explicitamente autorizado |
| Piper TTS 1.3 | GPL-3.0-or-later | processo de narração local |
| Faster Whisper | MIT | transcrição opcional |
| Next.js, React, Tailwind | MIT | painel |
| Lucide | ISC | ícones |
| FFmpeg Debian com libx264 | GPL, conforme configuração da distribuição | render via subprocesso |
| DejaVu Sans | licença DejaVu/Bitstream Vera | textos e legendas |

Piper e FFmpeg são executados como ferramentas locais. Uso pessoal self-hosted é compatível com este cenário; redistribuição de imagens/binários exige preservar avisos e cumprir as respectivas obrigações de disponibilização de código. Este repositório não incorpora uma licença de voz: verifique o model card de cada voz Piper antes de baixar e usar.

Revideo foi considerado, mas não incorporado: FFmpeg já atende ao render determinístico implementado e evita um segundo runtime de edição. O servidor Postiz não foi incorporado à imagem: há um adaptador HTTP para sua API pública, consultada na documentação oficial. O código do Postiz não foi copiado; uma instalação externa deve seguir sua licença e requisitos próprios. Ollama e OmniRoute são serviços externos opcionais compatíveis com o protocolo configurável; suas imagens/código não foram copiados.

Fontes: [FFmpeg legal](https://ffmpeg.org/legal.html), [Piper](https://github.com/OHF-Voice/piper1-gpl), [Faster Whisper](https://github.com/SYSTRAN/faster-whisper), [yt-dlp](https://github.com/yt-dlp/yt-dlp). Metadados de licença não autorizam reutilizar vídeos, marcas, trilhas ou vozes de terceiros.
