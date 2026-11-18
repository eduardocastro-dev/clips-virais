# GTA 6 Studio v5 — Upload de mídia e fatiamento de gameplay

## Aplicação do patch (Windows PowerShell)

1. Faça backup da pasta `Clips-Virais` e dos dados Docker, se necessário.
2. Extraia o ZIP **patch** na raiz da instalação existente, substituindo apenas
   os arquivos de código. Não substitua `.env`, `models/`, `assets/`, `temp/`,
   `data/` ou os volumes Docker.
3. Execute:

```powershell
docker compose up -d --build api worker web
docker compose ps
docker compose logs --tail=100 worker
docker compose exec api python -m backend.doctor
```

O backend aplica automaticamente as migrações SQLite (`assets` e `upload_sessions`)
sem apagar as produções, a biblioteca antiga ou as credenciais.

## Teste de cada etapa

### A. Upload e retomada

1. Abra `http://localhost:3000` → **Upload de mídia**.
2. Selecione dois vídeos, uma imagem e um MP3 ou WAV. Informe categoria,
   tags e classificação de origem para cada arquivo. Só assinale material
   autorizado quando tiver evidência da licença.
3. Acompanhe a barra de cada arquivo. Para testar retomada, desligue a rede
   local durante o upload, depois selecione novamente o mesmo arquivo e
   clique **Retomar**. O servidor consulta o offset e não reenvia blocos aceitos.
4. Teste um formato inválido ou um arquivo maior do que o limite configurado:
   o painel deve mostrar um erro específico.

### B. Fatiamento e original preservado

1. Envie um vídeo com 51 segundos, categoria **gameplay**, com direitos
   comprovados. Na **Biblioteca de assets**, encontre o original e expanda
   os clipes. São esperados 5 trechos: quatro de 10s e um de ~11s.
2. Confirme a localização do original em `assets/uploads/video/` e dos
   derivados em `assets/clips/<id>/`. O original não deve mudar.
3. Envie um vídeo de 30s: ele não deverá receber clipes derivados.
4. Para ver falhas reais de FFmpeg: `docker compose logs --tail=100 worker`.
5. Os clipes são gerados assincronamente; aguarde o estado **READY** na
   Biblioteca antes de concluir o teste.

### C. Gerenciamento e direitos

1. Em **Biblioteca de assets**, filtre por origem, tipo, categoria ou tag.
2. Renomeie um asset, altere sua categoria e desative-o.
3. Tente apagar um original com derivados: a interface exige confirmação e
   o backend recusa uma exclusão sem `confirm_children=true`.
4. Se escolher apagar de fato, o original e seus derivados serão excluídos.
   Faça isso apenas com arquivos de teste.
5. Mídias de terceiros não autorizadas permanecem catalogadas, mas não
   entram na montagem até registrar permissão.

### D. Seleção de cortes, trilha e preview

1. Disponibilize pelo menos dois gameplays próprios (ou outra mídia
   autorizada). Selecione categorias/tags relacionadas ao roteiro.
2. Gere uma produção com 12 a 30 segundos. Abra **Video Studio** e expanda
   **Assets e clipes usados em cada cena**. Verifique `asset_id`, `parent_id`,
   nome da fonte, tipo e duração de cada trecho.
3. Os clipes devem alternar sem repetição do mesmo arquivo em cortes
   consecutivos. Se não houver outro asset autorizado, o estúdio usa um
   fundo animado em vez de repetir o mesmo clipe ou produzir tela preta.
4. Envie uma música e um efeito com direitos autorizados; gere um segundo
   vídeo e confira que a voz permanece inteligível sob a trilha.
5. A aprovação e a postagem continuam manuais; nada é enviado às redes.

### E. Suíte automatizada

```powershell
docker compose --profile test run --rm tests
```

## Estrutura de armazenamento

```text
assets/
  gameplay/               # Gameplay local previamente cadastrado
  shorts/                 # Shorts autorizados baixados por yt-dlp
  uploads/
    video/                # Originais de vídeos enviados
    audio/                # Música, efeitos e narrações
    image/                # Imagens
    font/                 # Fontes
    subtitle/             # SRT
    logo/                 # Logos
  clips/<id_original>/
    clip_001.mp4
    clip_002.mp4
    ...
temp/
  uploads/<id>.part       # Uploads interrompidos, para retomar
  <id_producao>/          # Cópias de trabalho por produção
handoff/<id_producao>/    # Manifestos visuais por tentativa
videos/final/<id>/        # MP4s renderizados
```

**Utilidades:** FFmpeg/ffprobe (segmentação e montagem), yt-dlp (somente
fontes autorizadas), FastAPI (upload por blocos) e Next.js (interface).

**Limitações e segurança:** o upload retomável depende da seleção novamente
**do mesmo arquivo**. O sistema preserva o original durante todas as
operações, exceto se o próprio usuário confirmar uma exclusão na Biblioteca.
A classificação de uso autorizada depende de evidência fornecida pelo usuário;
creditar o autor não constitui licença. O limite de 5s de terceiros é aplicado
na montagem sem opção de ultrapassá-lo automaticamente.

## Validação da entrega

- 80 testes Python passaram com stub isolado do parser RSS ausente no ambiente
  de autoria (não usado em produção).
- FFmpeg real: divisão de um vídeo sintético de 51,2s em 5 clipes; teste de
  composição vertical 1080×1920, 12s, com H.264 e áudio AAC mixado.
- Sintaxe TypeScript/TSX verificada; o `npm ci` excedeu o tempo de execução no
  ambiente de autoria. **Build completo do frontend e Docker do usuário ainda
  requerem homologação.**
