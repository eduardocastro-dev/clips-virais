# SEO pronto para postar — GTA Studio

## Objetivo
Toda produção aprovada que chega à lista **Prontos para postar** recebe um pacote SEO **específico por plataforma**, pronto para revisão, edição e cópia. Não usa uma nova chamada de IA e não envia/publica automaticamente nas redes.

## Formato produzido
- **YouTube Shorts:** título (até 100 caracteres), descrição longa, hashtags, tags de palavras-chave, comentário fixado, texto sugerido para capa e créditos.
- **TikTok:** título de organização, legenda curta e engajadora, hashtags adequadas, comentário e fonte/créditos.
- **Instagram Reels:** título de organização, legenda, hashtags, comentário, texto de capa e créditos.

Os títulos e descrições usam somente roteiro aprovado, link de origem e créditos existentes. A marca **GTA 6 Brasil** vem da identidade visual fornecida pelo usuário. O material não promete cliques, retenção ou posicionamento.

As referências são links, não garantias de que um rumor seja verdadeiro. A pessoa que publicar deve reler afirmações, legendas e créditos antes da postagem.

## Como funciona
- **Novos vídeos:** `backend/pipeline.py` grava um objeto `seo` dentro do arquivo `output/<plataforma>/<dia>/metadata_<video_id>.json`.
- **Vídeos antigos:** `GET /api/publications/{id}/seo` gera metadados a partir do roteiro salvo quando não existir um objeto `seo`; o arquivo original é preservado.
- **Revisar/editar:** `PUT /api/publications/{id}/seo` valida os campos e salva o pacote no mesmo JSON. Publicações já marcadas como `PUBLICADO` não podem ser alteradas via essa rota.
- **Interface:** na aba **Prontos para postar**, expandir **SEO pronto para copiar**, editar e salvar, ou copiar título, legenda, hashtags, tags do YouTube e comentário fixado individualmente. O botão **Copiar título + legenda** permite colar o texto completo.
- **Exportação anterior:** `GET /api/exports/{video_id}/{platform}` mantém o arquivo JSON e agora traz também o objeto `seo`.
- Nenhuma integração faz upload nem acessa contas sociais.

## Cuidados de SEO e compatibilidade
- Conteúdo exclusivo por plataforma e PT-BR.
- A descrição mantém atribuição e URL de fonte quando URL HTTP(S) válida.
- Hashtags deduplicadas; tags do YouTube geradas sem preencher com termos irrelevantes.
- Limites de campos no backend e na interface.
- Nenhum arquivo MP4 é modificado, e não há necessidade de migrar SQLite.
- O vídeo de homologação fica marcado como `test_only`; não publicar.
- Visibilidade e monetização dependem da plataforma. O SEO não garante desempenho.

## Implantação
```powershell
git pull origin main
docker compose build --no-cache api worker web
docker compose up -d --force-recreate api worker web
docker compose ps
```

Testes de regressão: `python -m pytest -q tests/test_publication_seo.py tests/test_manual_mode.py`. Não executar `docker compose down -v`.
