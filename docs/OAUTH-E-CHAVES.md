# OmniRoute + Postiz: chaves de API e OAuth

## Chave OmniRoute no GTA Studio

O Estúdio armazena a credencial em `llm_api_key` criptografada no volume `studio`. Não é a senha do painel OmniRoute (`OMNIROUTE_PASSWORD`) nem o nome do combo. Em GTA Studio > Configurações > OmniRoute — conexão de IA, veja o status e, se necessário, cole a **chave completa de inferência** criada em OmniRoute > API Keys. Prefira uma chave limitada ao combo `studio-free`, sem scope `manage`/`admin`; mantenha `provider_url=http://omniroute:20128/v1` e modelos de agentes `studio-free`.

Uma chave já criada no OmniRoute pode ser mostrada apenas mascarada após sua criação. O bootstrap **não recupera** uma chave preexistente do painel nem deve usar chaves administrativas para contornar permissões. Se perdeu a chave completa, gere outra chave de inferência e salve-a no Estúdio.

O bootstrap local tenta provisionar uma chave própria e conservadora. Se falhar, registre manualmente pelo painel ou investigue `docker compose logs --tail=80 bootstrap` e `docker compose exec api python -m backend.doctor`. A falha do Postiz não impede as tentativas no OmniRoute.

## Erro Google `400 invalid_request: Missing required parameter: client_id`

O Postiz mostra provedores mesmo sem configurar os respectivos aplicativos OAuth. Para conectar um **canal YouTube**, crie um projeto no Google Cloud Console, configure a tela de consentimento OAuth, habilite a **YouTube Data API v3**, crie um **OAuth Client ID do tipo aplicativo web** e informe o redirect exatamente como no Postiz. Para a configuração **local** deste Compose, o redirect é:

`http://localhost:4007/integrations/social/youtube`

Em servidor público use o seu endereço HTTPS: `https://seu-dominio/integrations/social/youtube` e ajuste `POSTIZ_PUBLIC_URL` para esse endereço. O redirect e domínio devem corresponder aos autorizados no console Google; contas em modo Teste devem ser adicionadas como usuários de teste conforme a configuração do OAuth.

Copie **apenas para o seu `.env`**, sem enviar ao chat e sem registrar no Git:

```dotenv
YOUTUBE_CLIENT_ID=SEU_CLIENT_ID_EMITIDO_PELO_GOOGLE
YOUTUBE_CLIENT_SECRET=SEU_CLIENT_SECRET_EMITIDO_PELO_GOOGLE
```

Se os campos já existem vazios, **preencha-os** em vez de duplicá-los. Depois rode:

```powershell
docker compose up -d --force-recreate postiz
docker compose logs --tail=80 postiz
```

Um simples `docker compose restart postiz` **não** atualiza variáveis do `.env` de um container já criado. Não use `down -v` nem apague os volumes.

**Importante:** o erro exibido ao clicar em `Sign in with Google` (login no Postiz) pode exigir uma configuração de login Google/OIDC distinta daquela usada em **Adicionar canal > YouTube**. Esse Compose não configurou `POSTIZ_GENERIC_OAUTH`; para uso pessoal, entre no Postiz com a conta local cadastrada. Se o erro ocorre ao conectar **YouTube**, verifique `YOUTUBE_CLIENT_ID` e `YOUTUBE_CLIENT_SECRET` como acima.

## Outras redes

- Instagram vinculado a Facebook Business: `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET` (Meta Developers); modo Instagram Standalone: `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`.
- TikTok: `TIKTOK_CLIENT_ID`, `TIKTOK_CLIENT_SECRET` do TikTok Developers, com permissões de publicação aprovadas.

Essas credenciais **não podem ser geradas pelo Docker**, pois exigem contas, termos e aprovações de cada plataforma. Confirme redirect/URLs HTTPS conforme políticas do provedor.

## Diagnóstico

`python scripts/check_integrations.py` lista apenas se as variáveis estão presentes, nunca os valores.

Referências:
- https://docs.postiz.com/self-host/providers/overview
- https://docs.postiz.com/self-host/providers/youtube
- https://docs.postiz.com/self-host/configuration/reference
