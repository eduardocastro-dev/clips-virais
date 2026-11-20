# GTA Studio — nove cenários com TV editorial (v1)

## Os nove formatos
`gta-news` (redação Miami), `gta-theory` (investigação), `gta-comparison` (showroom),
`gta-cinematic` (cinema), `gta-facts` (arcade), `gta-reaction` (quarto gamer),
`gta-radar-viral` (controle/radar), `gta-detail-breakdown` (bancada de análise)
e `gta-hype-reaction` (talk show ao pôr do sol).

São **plates originais procedurais em Pillow**, separados da imagem na TV, moldura e primeiro plano.
Não são fotografias de estúdio nem templates Envato. Cada cenário contém **uma única TV física**;
o conteúdo da TV é composto pelo FFmpeg em perspectiva/corner-pin e pode mudar sem redesenhar o plate.

### Coordenadas 1080×1920 / 30 fps
- Moldura TV: x=92–988, y=225–788. Conteúdo: x=143–937, y=291–733.
- Apresentador: x=160–920, y=800–1388. Sem móveis, texto ou partes da TV.
- Legendas cinéticas: y=1400–1580 (ponto de ancoragem 1530).
- Rodapé editorial e CTA: abaixo de y=1580. Badge de canal: acima da TV.
- Glitch de troca da TV: 7 frames; os cortes são ajustados a palavras realmente transcritas quando existe um timestamp próximo, dentro de 180 ms, sem mudar a duração total.
- Push-in dentro da TV: máximo de 3%; câmera da persona é estável. A cor amostrada da mídia aplica luz ambiente suave e cor secundária ao apresentador.

### Conteúdo da TV
1. **Vídeo-fonte público** da notícia ou do link de importação, obtido anonimamente via yt-dlp e guardado em `assets/source_previews`. Suporta URLs diretas do YouTube, Instagram e TikTok dentro das validações existentes; artigos com `video_url` também podem apontar ao vídeo. Nunca usa cookies, contas logadas, YouTube Data API nem contorna restrições.
2. Se o download não estiver disponível, usar foto identificada da fonte da notícia dentro da TV.
3. Se não houver mídia da fonte, usar vídeo autorizado da biblioteca. O pipeline exige os demais assets obrigatórios originais.

Um vídeo-fonte importado sem prova de licença pode ser usado **somente em uma prévia privada**. A biblioteca o identifica como `REVIEW_REQUIRED`. Arquivos públicos acessíveis **não são automaticamente licenciados**, e o operador pode remover a mídia na biblioteca.

### Fluxo de aprovação — após concluir a edição
1. Roteiro, narração Piper com duração REAL, transcrição, edição das camadas, som licenciado e avaliação técnica/editorial são executados **antes** da escolha do operador.
2. O arquivo MP4 fica disponível no **Video Studio**. Se alguma fonte na TV estiver com autorização pendente, o estado será **`PENDING_RIGHTS_REVIEW`**.
3. Assista à prévia, veja a fonte no manifesto e escolha **Descartar** ou **Confirmar direitos para esta prévia**. A confirmação exige comprovação/declaração cobrindo os materiais exibidos.
4. Depois disso, pressione **Aprovar manualmente**. Só então o vídeo entra em **Prontos para postar**. Nunca existe postagem automática.
5. `rights_log.json` registra uso, status e a autorização posterior; os assets podem ser apagados manualmente.

**Atenção:** confirmar direitos é uma declaração feita pelo operador. O GTA Studio não verifica automaticamente a validade jurídica da autorização. Mantenha a licença, o escopo de reutilização, a data e o autor para auditoria.

### Dependências e compatibilidade
- Não muda o mecanismo de duração de áudio do Piper, verificação de decodificação ou lote de revisão. Só muda a composição de vídeos que usam um dos nove IDs de template.
- Reaproveita personas, legendas ASS, biblioteca, mix com ducking e assets registrados. O SFX de troca de canal utiliza efeitos **já autorizados** na biblioteca; sem SFX aprovado, não inventa ou baixa um áudio de terceiros.
- Fica no máximo 250 MB por fonte baixada; fontes com login/restrição ou falha de rede não são usadas.
- O estado de revisão de direitos conta como produção ativa na cota, não como Short aprovado.
- Gráficos vetoriais/plates são uma base reutilizável v1; assets artísticos adicionais licenciados podem evoluir a aparência mais adiante.

### Implantação
```powershell
git pull --ff-only origin main
docker compose build api worker web
docker compose up -d --force-recreate api worker web
docker compose ps
```

Evite reconstruir o worker enquanto uma live estiver em transcrição, pois a operação atual seria interrompida.

### Testes
`tests/test_scenarios_tv.py` verifica os nove ambientes, regiões seguras,
camadas intercambiáveis, status privado, bloqueio de publicação e confirmação
de licença depois do render. Os projetos ainda requerem um teste de produção
real em Docker com Piper, licença de assets e um vídeo de fonte acessível.
