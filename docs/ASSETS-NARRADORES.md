# GTA Studio — pacote de assets dos narradores

Conjunto fornecido a partir das três folhas de poses enviadas na conversa:

- Dante Palma — apresentador, blazer creme, camisa floral, óculos azuis.
- Lia Varela — analista, cabelo preto com mecha violeta, paletó roxo.
- Caio Rivas — repórter, jaqueta preta com detalhes coloridos e camisa coral.

Cada personagem possui 24 PNGs RGBA de 1024×1536, `manifest.json`, `avatar.png` e `portrait-quality.png`.
Os nomes e as emoções seguem exatamente o catálogo usado por `backend.personas.expression_file`.

**Qualidade da origem:** as imagens foram recortadas de folhas 4×6 de 1024×1536,
com **256×256 pixels nativos por pose**. Foram redimensionadas com tratamento de canal alfa
para 1024×1536, que é a dimensão operacional do editor. Isso não cria novos detalhes nativos;
uma futura versão com 24 PNGs desenhados individualmente pode substituí-las.
Os arquivos-fonte estão em `assets/personas/_referencia/`.

## Instalação

1. Faça backup da pasta atual, especialmente `.env`, `assets/`, `models/` e `data/`.
2. Extraia o ZIP completo sobre a pasta do GTA Studio, preservando `.env` e dados do Docker.
3. Na raiz do projeto, execute:

```powershell
docker compose up -d --build api worker web
docker compose exec api python -m backend.persona_assets
```

O script instala faltantes, substitui **apenas galerias antigas/incompletas** e mantém backup em
`assets/personas/_antigo/`. Galerias completas personalizadas são preservadas.
A função `get_cast()` também aplica a instalação idempotente no primeiro acesso.

## Verificação

```powershell
docker compose exec api python -c "from backend.personas import get_cast,expression_file; c=get_cast(); print({k:(v['production_ready'],v['image_path']) for k,v in c.items()}); print(expression_file('lia_varela','surpreso'))"
docker compose --profile test run --rm tests
```

No GTA Studio, acesse **Configurações → Elenco e vozes**, atualize o navegador e abra as galerias dos três narradores.
Confira 24 poses por pessoa, o retrato de cada personagem e a opção de restaurar o master da pose.

A atualização **não inclui** novos modelos ONNX de voz, credenciais ou banco SQLite.
