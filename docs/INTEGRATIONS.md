# Contratos externos e operação

## Postiz

Contrato consultado na documentação pública oficial durante a implementação:

- [Autenticação e base URL](https://docs.postiz.com/public-api/introduction)
- [Integrações/canais](https://docs.postiz.com/public-api/integrations/list)
- [Upload multipart](https://docs.postiz.com/public-api/uploads/upload-file)
- [Criar/agendar post](https://docs.postiz.com/public-api/posts/create)
- [Consultar posts e estado](https://docs.postiz.com/public-api/posts/list)
- [Métricas por post](https://docs.postiz.com/public-api/analytics/post)

Header `Authorization` recebe a chave sem prefixo Bearer. A base self-hosted termina em `/api/public/v1`. O upload retorna `id` e `path`; são enviados no campo `image` mesmo quando o arquivo é MP4. `adjust` não é solicitado porque o arquivo já é H.264/AAC vertical. Se o serviço informar `processing`, o envio não começa.

Cada POST de agendamento contém um único destino, isolando falhas por rede. Os campos `settings` específicos vêm da configuração explícita do usuário, obtida no assistente Postiz. Nunca assumir que uma opção de privacidade do TikTok é permitida para uma conta particular. O adaptador valida identidade/tipo do canal antes de enviar.

`postId` confirma apenas agendamento. A aplicação consulta a lista de posts por intervalo de datas e aguarda `state=PUBLISHED` com `releaseURL` válida da rede correspondente. `ERROR` mantém o arquivo disponível para publicação manual. Falhas ambíguas não iniciam POST repetido: ficam pendentes de reconciliação humana. A API Postiz não oferece uma chave genérica de idempotência documentada neste contrato; o estado local durável impede repetição automática.

Os rótulos de métricas variam por rede. O adaptador normaliza somente labels conhecidos e preserva as séries completas em `provider_series`; campos desconhecidos não são convertidos em zeros. Cache de seis horas e limite conservador global de 30 chamadas/hora evitam coleta excessiva.

## TikTok

oEmbed é referência pública quando disponível. Consulta de perfil usa `https://open.tiktokapis.com/v2/user/info/` e `/v2/video/list/`, com bearer token e escopos adequados. O username retornado deve corresponder ao perfil cadastrado. Não há pesquisa arbitrária de perfis externos por este token.

## Instagram

Consulta usa Graph API v23.0 com a conta profissional vinculada ao Facebook e acesso aprovado. Lê username e a mídia recente da própria conta. Instagram Login independente requer outro adaptador de autenticação/host; não é silenciosamente tratado como Facebook Login. Tokens e escopos devem ser obtidos por fluxos oficiais. Importação usa metadados de mídia já observada no perfil autorizado.

## RSS/Atom

Feeds HTTPS públicos, sem credenciais na URL e sem redirecionamento automático. Resolução para endereço privado é bloqueada. Entradas sobre GTA 6/VI ou Grand Theft Auto são guardadas como referência, com URL do artigo, URL do feed, texto e momento da coleta. A presença em um feed não comprova direitos audiovisuais nem confirmação oficial de um rumor.

## Homologação

As interfaces HTTP foram implementadas; os testes usam fixtures explícitas. Nenhuma conta social foi conectada e nenhum post foi enviado durante o desenvolvimento. É necessário validar os conectores com os aplicativos aprovados do usuário antes de ativar produção real. O fallback manual permanece operacional quando credenciais, permissões ou disponibilidade da plataforma faltarem.
