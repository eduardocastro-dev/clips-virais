# Correção: orçamento de IA e descoberta de YouTube Shorts

## O que muda

- O Viral Radar procura **somente YouTube Shorts sobre GTA 6** via filtro específico da busca do YouTube ou pela aba `/shorts` dos canais cadastrados. Mídias são **somente referência** salvo licença/autorização verificável.
- RSS e vídeos comuns deixam de entrar na **descoberta automática**. Dados antigos continuam no SQLite (somente são ocultados do Viral Radar).
- Pesquisar Shorts não faz chamadas ao OmniRoute: usa yt-dlp em modo de metadados (sem download).
- Contagem de IA passa a estimar tokens de entrada por caracteres/4, reservar antes da chamada e reconciliar com `usage.total_tokens`, quando fornecido. HTTP 400, 401, 403, 404, 422 e 429 não descontam permanentemente a reserva. Erros de resultado incerto retêm a reserva por segurança.
- A publicação permanece **100% manual**.
- `yt-dlp` atualizado para 2026.10.26 (filtro específico para Shorts) e Piper mantido em **1.8.0** para preservar a voz brasileira instalada anteriormente.

## Aplicação no Windows

1. Pause o modo automático e aguarde o worker terminar qualquer job em andamento.
2. Faça backup do diretório e dos volumes. Extraia o patch **na raiz `Clips-Virais`**, substituindo os arquivos. **Não sobrescreva `.env`**, `models/` nem o volume `studio`.
3. Reconstrua a API, o worker e o painel:

```powershell
docker compose up -d --build api worker web
```

4. Para aliviar o limite interno antigo de 20.000 tokens/dia, execute **uma vez**:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ajustar-orcamento-ia.ps1
```

Por padrão ajusta o teto interno para 200.000 tokens/dia **sem limpar o consumo já registrado**. Pode passar um teto diferente dentro do permitido: `-TokensPorDia 100000`. Não altera quotas, preços ou limites externos dos provedores no OmniRoute. Só altere o limite se souber que os modelos e credenciais conectados são compatíveis com seu orçamento real; a existência de um modelo no combo não significa uso ilimitado ou gratuito.

5. Vá em **Viral Radar → Pesquisar Shorts**, confira a fila em **Agentes** e o log do worker:

```powershell
docker compose logs --tail=80 worker
```

6. O painel **Agentes** mostra o consumo interno contabilizado no dia. Se ainda aparecer orçamento atingido, confira em **Configurações** o campo `Limite interno de tokens/dia` e também `Orçamento diário (US$)` e `Custo/milhão tokens`. Não zere o banco `usage` sem auditar.

## Notas de operação

- Pesquisa pública no YouTube é de **melhor esforço** e pode retornar zero resultados, exigir atualizações no yt-dlp ou sofrer limites da plataforma; não contornamos acesso ou login.
- Um URL `/shorts/` sozinho não comprova que determinado resultado é um Short; a busca usa a origem da aba/tipo Shorts, rejeita URLs watch/live explícitas e descarta vídeos com mais de 180s quando a duração é informada. Isso é um filtro conservador, mas não há validação perfeita sem metadados mais completos.
- O YouTube continua sendo uma fonte de inspiração/referência. O Editor não pode baixar e republicar mídias de terceiros sem autorização.
- Os testes locais foram executados com adaptadores simulados de busca, não com a rede real nem Docker.
