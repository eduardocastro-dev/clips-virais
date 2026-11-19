# Fontes e Efeitos de Texto — GTA Studio

## O que foi adicionado

Uma aba **Fontes e Efeitos** para importar e guardar permanentemente:
- **TTF/OTF:** fontes tipográficas reais, usadas para desenhar títulos dinâmicos.
- **ZIP com EPS + JPG/PNG:** efeitos de texto vetoriais com uma imagem de prévia. EPS não é fonte e não permite simplesmente trocar as letras via FFmpeg/Pillow. O projeto usa o visual como **referência** de cores, gradiente e sombra, produzindo novos títulos editáveis com aproximação estética.

Os dois ZIPs fornecidos na conversa foram examinados: cada um contém **um EPS e uma JPG**, nenhum TTF/OTF. São compatíveis com a nova aba para importação manual.

## Funcionamento
1. Entre em **Fontes e Efeitos**.
2. Selecione ZIP EPS/JPG, TTF ou OTF (até 25MB).
3. Informe nome, paleta e comprovação de licença para o uso pretendido.
4. Clique **Adicionar à biblioteca**.
5. Visualize o asset e escolha **Usar nas próximas edições**.
6. O gancho (0–3 segundos) dos próximos renders ganha uma sobreposição tipográfica com transparência, respeitando o áudio Piper e sem alterar os demais elementos. Desativar restaura o render anterior.

Os arquivos ficam em `/studio/assets/text_styles/<id>/` (sob a raiz definida em `STUDIO_FILES`) e os metadados em SQLite já existente. Não há migração destrutiva de banco.

## Segurança e direitos
- ZIP é lido em memória e extrai somente o EPS e a prévia, com limites de tamanho e quantidade; caminhos internos não são usados ao salvar.
- EPS **não é executado nem renderizado** pelo backend; é guardado apenas como referência.
- Fonte validada como TTF/OTF antes de ser aceita.
- Uso exige licença informada e ativação explícita. Não basta o nome do arquivo ou a origem comercial para provar o direito.
- Não adiciona uma nova chamada ao OmniRoute.
- Nenhuma alteração nos bloqueios de mídia original, duração real do Piper, direitos de gameplay ou música.
- Vídeos anteriores não são reescritos; com a biblioteca desativada, a renderização antiga continua funcionando.

## Instalar em Docker
```powershell
git pull origin main
docker compose build --no-cache api worker web
docker compose up -d --force-recreate api worker web
docker compose ps
```

Para validar num ambiente de teste completo:
```powershell
docker compose --profile test run --rm tests python -m pytest -q tests/test_text_styles.py
```
Verifique o nome real do serviço de testes na configuração Compose antes de executar esse último comando.

## Limitação
A arte exata do EPS editável pode depender do Illustrator/Corel/Photoshop e de fontes comerciais não incluídas nos ZIPs. Neste editor, a forma tipográfica será uma reprodução visual aproximada; importar a fonte original licenciada permite usar seus glifos reais.
