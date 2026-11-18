# GTA Studio v8 — Direção de arte e vídeo dinâmico

## Diagnóstico a partir do MP4 enviado (45s)

- Os avatares SVG apareciam muito pequenos (280×420) e eram graficamente inconsistentes.
- Havia gameplay, porém sem capturas reconhecíveis da fonte original; cards "fato/rumor" ocupavam parte da narrativa.
- O gerador antigo `scripts/generate_expressions.py` desenhava os três bonecos por SVG e convertia o resultado em PNG. Desativado, **não é fonte de arte de produção**.
- O vídeo gerado não prova a relação entre os quadros apresentados e o assunto narrado. A nova curadoria visual precisa de fonte acessível com direitos documentados e de um modelo OmniRoute que aceite imagens.

## Arte dos personagens

O arquivo `assets/personas/_referencia/dante_palma_sheet.png` é a folha 4×6 fornecida pelo usuário. Cada célula tem somente 256×256 px; **não cortar e ampliar** para fingir 1024×1280. O busto original `templates/personas/dante_palma/portrait-quality.png` (1122×1402, RGBA) é a primeira referência em alta resolução de Dante. Ela funciona como único retrato de qualidade enquanto outras 23 poses não forem fornecidas; **não confundir isso com 24 poses HD**.

### Briefing para aprovação — Lia Varela, Analista

Silhueta própria, ombros estreitos, corte de cabelo preto curto levemente assimétrico com mecha violeta, expressão curiosa e confiante, óculos discretos apenas quando apropriado; jaqueta curta de couro azul petróleo, camiseta creme e brincos geométricos. Paleta petróleo, lavanda e prata. Cartoon semirrealista anos 1980, contornos escuros espessos, sombreamento detalhado, rosto único e proporções humanas. O papel mudou: ela contextualiza e apresenta curiosidades, não segura placas "fato/rumor". Requisitos: busto 1024×1280 ou maior, fundo RGBA transparente, 24 expressões originais.

### Briefing para aprovação — Caio Rivas, Repórter

Silhueta mais alta/esguia, cabelo preto ondulado curto, sobrancelhas expressivas, sorriso discreto, sem óculos escuros permanentes; jaqueta bomber coral e marrom ferrugem sobre camiseta verde água, microfone compacto ou celular apenas na pose de última hora. Paleta coral, ferrugem e turquesa. Mesmo acabamento da folha Dante, mas roupa, proporção, rosto e linguagem gestual completamente distintos. Requisitos: 24 bustos 1024×1280+, RGBA, identidade consistente.

Não gerar Lia/Caio automaticamente com o SVG antigo. A importação só libera produção quando os 24 PNGs de alta resolução estiverem presentes e válidos. Antes disso o Roteirista recebe somente os personagens visuais disponíveis.

### Importação

1. `Configurações > Elenco > Importar folha 4×6` armazena a folha somente como referência.
2. `Importar ZIP com 24 PNGs` exige `01_neutro.png` até `24_chamando_comentar.png`, seguindo todos os slugs de `backend/pose_import.py`.
3. Os arquivos são verificados por formato PNG RGBA, 1024×1280 mínimo, dimensões uniformes e cantos transparentes.
4. A versão anterior é preservada em `assets/personas/_antigo/{nome}/{id}`. As versões mestres importadas ficam em `assets/personas/_quality_master/{nome}`; **Restaurar** copia esse master, jamais o SVG.

## Ritmo e relevância visual

- Cortes de 1,5 a 3 s; padrão 2,25 s.
- Bustos com até 850 px de altura, um em cada lateral conforme a fala; faixa de legendas deslocada para cima.
- Legendas palavra a palavra **somente quando existem timestamps reais do Whisper**; fallback medido por frase não finge alinhamento por palavra.
- SFX discretos na abertura e a cada ~5s; escolha de música disponível em `/assets/music` continua dependente de conteúdo local.
- Sem etiquetas "fato/fake/confirmado" na tela; a verificação factual continua nos agentes, e afirmações incertas recebem contexto natural.
- `backend/source_frames.py`: amostragem distribuída + detector de corte de cena, remoção de quadros pretos/borrados/duplicados, classificação multimodal quando `routes.escritor.vision = true`.
- Só um modelo que de fato recebe as imagens pode dar `relevance` 0–10. Frames com relevância inferior a 7 não são selecionados; se a visão falhar, não são fabricadas notas. Para notícias, o Playwright captura excertos/figuras curtos com URL de fonte e sinalização de direitos a revisar.
- Reutilização de trechos de vídeo exige autorização documentada, 3–4 s por corte e máximo de 5 s por fonte de terceiros no vídeo. Créditos na tela e metadados, sem afirmar que crédito substitui permissão.
- Todo render produz `visual-assets-attempt-N.json` e `visual-rhythm-attempt-N.json` para auditoria.

## Infra e homologação

Comandos no PowerShell, a partir de Clips-Virais:

```powershell
# Backup da pasta do projeto e do /assets antes de atualizar
# Extraia o patch v8, preservando .env, models, data e volumes.
docker compose up -d --build api worker web

# Examinar o que será arquivado; nenhuma alteração é feita
# quando não se usa --apply:
docker compose exec api python -m backend.migrate_art_v8

# Após conferir o relatório, arquivar os 72 sprites do pacote v7
# SOMENTE quando seus bytes correspondem aos originais fornecidos:
docker compose exec api python -m backend.migrate_art_v8 --apply

# Conferir os serviços
docker compose exec api python -m backend.doctor
docker compose logs --tail=80 worker
```

Em Configurações, ative visão para o Escritor **somente se o combo escolhido realmente aceitar imagens**. Configure gameplay/música autorizadas, importe o material da fonte e produza um vídeo curto em modo manual.

### Critérios de aceite realmente testados

- O renderizador FFmpeg gerou trecho 1080×1920 com uma captura da fonte sobre gameplay.
- Em um vídeo de 45s foram encontrados 28 quadros não duplicados elegíveis para curadoria.
- A saída sintática Python passou; os testes do backend foram executados com substituto de RSS por falta da dependência `feedparser` no ambiente.
- UI TSX analisada por TypeScript transpiler; build Next.js completo NÃO homologado porque o cache npm não contém `undici-types`.

### Limitações ainda abertas

- Existem apenas **1 busto individual de qualidade** (Dante), não 72 poses HD. Lia/Caio aguardam aprovação e importação do novo elenco; até lá, não entram em renders finais.
- A qualidade semântica real da curadoria multimodal depende de uma conta/modelo OmniRoute com visão e fonte com direito de uso.
- Não há geração automática de 24 poses por personagem, lip-sync de boca nem aprendizado causal por retenção de Analytics neste patch.
- Conteúdo de terceiros não é classificado automaticamente como licenciado. O botão "Ativar" regula disponibilidade editorial; os direitos continuam sendo avaliados separadamente.
