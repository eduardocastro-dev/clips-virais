# GTA Studio — mídia temporária, biblioteca, persona e renders v4

## O que mudou

1. `backend/pipeline.py::write_script` agora chama `backend/storyboard.py::normalize` **antes** da validação do objeto `Script`. A duração é a duração solicitada pelo vídeo ou, quando definido, `duration` do template. Campos divergentes (`duration`, `template`, `scenes[*].timestamps` e `source_id`) são registrados em `handoff/{id}/briefing-fixes-{n}.json`. Há até 2 novas gerações se o roteiro continuar inválido.
2. A edição passa a montar imagens/filmagens por cena em `backend/visual_renderer.py`. Não existe vídeo de fundo sem conteúdo visual: em último caso é gerado um gradiente neon panorâmico com zoom lento. O render final permanece em `videos/final/{id}/attempt-NN.mp4` para revisão, inclusive quando reprovado.
3. `backend/production_media.py` faz cópias de arquivos licenciados de `assets` para `temp/{video_id}`, sem alterar origem. Fontes autorizadas não existentes localmente são baixadas via `yt-dlp` em até três tentativas. Erros ficam em eventos e em `temp/{id}/download-error.json`; na indisponibilidade, editor utiliza gameplay licenciada e gradiente. Notícias usam Playwright para capturas pequenas da manchete/parágrafo/imagem, quando a página permite; caso contrário, card original com título.
4. Manifestos `handoff/{id}/visual-assets.json` e `visual-assets-attempt-N.json` identificam arquivo e origem, trechos, tempo, classificação e direitos. O Video Studio apresenta estes campos ao selecionar a tentativa.
5. O Diretório `assets/` é persistente. Shorts são catalogados por ID do YouTube como `METADATA_ONLY` até a licença ser registrada. Só se houver autorização explícita o botão de download usa `yt-dlp`, salvando `{data}_{canal}_{id}.mp4` + `.json` na biblioteca permanente. As atualizações de download mostram `DOWNLOADING`, `RETRYING`, `FAILED` e percentual quando reportado.
6. O diretório `temp/` é limpo na aprovação após exportação, ou no descarte. Reprovações, retries e itens aguardando decisão manual conservam as fontes. A manutenção remove diretórios de produções finalizadas e abandonadas depois de `temporary_retention_days` (padrão sete dias) sem apagar rendes finais.
7. `backend/personas.py` inclui três apresentadores fictícios. Em Configurações pode selecionar preset, editar dossiê e voz Piper e associar avatar original da biblioteca. O dossiê é enviado ao Escritor; não se promete usar voz única se o TTS configurado não tiver a timbragem desejada.

## Estrutura de pastas (Windows / Docker)

| Host (pasta Clips-Virais) | No container | Descrição |
|---|---|---|
| `assets/gameplay/` | `/studio/assets/gameplay` | Gameplays com permissão de uso |
| `assets/shorts/` | `/studio/assets/shorts` | Shorts licenciados + metadados JSON |
| `assets/images/` | `/studio/assets/images` | Imagens de apoio autorizadas |
| `assets/persona/` | `/studio/assets/persona` | Avatar escolhido pelo operador |
| `temp/{video_id}/` | `/studio/temp/{video_id}` | Cópias de trabalho e capturas de notícias |
| `handoff/{video_id}/` | `/studio/handoff/{video_id}` | Manifestos e briefings |
| `videos/final/{video_id}/` | `/studio/videos/final/{video_id}` | Renders por tentativa, independente de temp |

**Migração de assets antes da troca de Compose:** se a versão anterior tinha arquivos em `/studio/assets` dentro do volume `studio`, copie-os do container **ainda em execução** usando `docker compose cp api:/studio/assets/. ./assets/` ANTES de substituir o `docker-compose.yml`. Novo bind mount oculta arquivos antigos no mesmo caminho dentro do volume, mas não os deleta. Se ainda não havia biblioteca, crie somente as pastas `assets` e `temp` e prossiga.

## Instalação no Windows

1. Faça backup da pasta do projeto e das credenciais. Preserve `.env`, `models/` e volumes Docker.
2. Se já possuía assets no volume, execute o comando de migração acima enquanto o container API antigo está ativo.
3. Extraia o **patch** na raiz de `Clips-Virais`, sobrescrevendo somente os arquivos do patch.
4. Execute `docker compose up -d --build api worker web`. A imagem backend instala Pillow, Playwright e Chromium no build.
5. Confira `docker compose ps` e `docker compose logs --tail=100 worker`.
6. Em **Biblioteca de assets**, envie ou copie gameplay, imagens e avatar. Classifique o direito/adicione evidência para liberar uso. Se o vídeo vier de um terceiro sem licença, preserve somente como referência; isso não autoriza download nem reupload.
7. Em **Configurações**, escolha a persona, configure modelo Piper PT-BR e ajuste `temporary_retention_days`.
8. Inicie produção por URL ou Radar. Em **Video Studio**, confira cada MP4, as fontes/trechos por cena, e a razão completa da avaliação.

## Segurança, licenças e limites

- O software não elimina direitos autorais por usar trechos curtos ou adicionar crédito. Shorts de terceiros sem licença documentada permanecem `REFERENCE_ONLY`. Mesmo conteúdos com autorização devem seguir as condições específicas da licença.
- Para links sociais autorizados, limite automático padrão de **4s por inserção** e **5s no total de trechos da fonte**. O software não inclui trechos acima de 5s sem um fluxo adicional de permissão; evita a necessidade de alerta para um excesso que não pode ocorrer.
- Capturas de artigos são excertos editoriais marcados `REVIEW_REQUIRED` e devem ser revisadas pelo usuário antes da postagem. Anúncios, paywalls e proteções de acesso não são contornados. Fallback é card editorial original com fonte.
- Geração externa de **imagem por IA** não foi homologada: se não houver recurso de geração de imagem configurado/licenciado, o sistema usa assets autorizados ou gradiente animado. Não há promessa de gerar imagens inéditas usando somente um modelo de chat.
- Nenhuma integração publica conteúdo. Os MP4s e metadados permanecem para publicação manual.

## Testes

```powershell
# Testes Python no container com dependências reais
# docker compose --profile test run --rm tests

docker compose exec api python -m backend.doctor

# Conferir cópias, originais e manifestos de uma produção
# docker compose exec api ls -lah /studio/temp/<id>
# docker compose exec api ls -lah /studio/handoff/<id>
# docker compose exec api ls -lah /studio/videos/final/<id>
```

Validação feita neste ambiente: 73 testes com parser RSS substituto de teste, `compileall` Python, validação sintática de TSX, e composição real FFmpeg 1080×1920 de duas cenas sintéticas. Não foi possível rodar Docker nem validar downloads externos, Playwright/Chromium dentro do Docker ou build completo Next.js nesta sessão.
