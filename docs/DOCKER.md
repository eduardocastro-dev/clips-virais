# Instalação Docker integrada

Execute `./start.ps1` no PowerShell ou `sh start.sh` no Linux, na pasta do projeto. Só é necessário Docker com Compose v2 e containers Linux. O primeiro download pode demorar vários minutos. Reserve preferencialmente 4 CPUs, 12–16 GB de RAM para Docker e 20 GB de disco para o conjunto e mídias.

O comando executa um container temporário que cria `.env`, preserva valores existentes e gera senhas distintas para bancos, Postiz, OmniRoute e estúdio. Depois sobe a aplicação, Postiz, OmniRoute, Redis, PostgreSQL e Temporal/Elasticsearch. Os serviços usam uma instância PostgreSQL compartilhada (bancos/roles isolados) e uma instância Redis compartilhada (DB 0 Postiz, DB 1 OmniRoute), com volumes persistentes. O Temporal também precisa de Elasticsearch; o estúdio mantém SQLite e o OmniRoute mantém seus arquivos de configuração próprios. Não há montagem do socket Docker nos serviços.

| Acesso local | Credencial em `.env` |
|---|---|
| [Estúdio](http://localhost:3000) | `STUDIO_TOKEN` |
| [Postiz](http://localhost:4007) | `POSTIZ_ADMIN_EMAIL` + `POSTIZ_ADMIN_PASSWORD` |
| [OmniRoute](http://localhost:20128) | `OMNIROUTE_PASSWORD` |

As senhas ficam no arquivo local; não são impressas nos logs. `.env` está excluído do Git e do contexto de build. No Linux recebe modo 0600; no Windows mantenha as permissões da pasta limitadas ao seu usuário. Faça backup seguro de `.env` e dos volumes juntos.

## O que já fica conectado

O serviço `bootstrap` aguarda os painéis e configura **OmniRoute primeiro**, de forma independente do Postiz. Em seguida tenta registrar ou autenticar a conta local Postiz e obter a chave da organização. Se a API do OmniRoute permitir, cria uma chave de inferência restrita ao combo `studio-free`. Aplica e verifica a política restritiva da chave OmniRoute via PATCH, impedindo que uma criação ignorada pela API vire uma chave permissiva sem aviso. Grava segredos criptografados no banco do estúdio. Se uma API/versão não permitir essa operação, o bootstrap falha de modo explícito em vez de afirmar sucesso. Define as URLs internas e o modelo `studio-free`. Não habilita produção ou publicação automática. Credenciais e configurações já personalizadas são preservadas; novas contas não são criadas em uma instalação Postiz que já tenha usuário.

Confira `docker compose logs bootstrap`: deve concluir as duas integrações. Reiniciar não troca senhas nem cria novamente as chaves já salvas. Se você alterar a senha no painel, atualize seu registro privado; os valores iniciais de `.env` não redefinem senhas já persistidas.

## Suas etapas manuais

1. **IA:** entre no OmniRoute e conecte suas contas ou chaves de provedores. Em Combos, crie `studio-free` com estratégia `priority` e os modelos que seu plano permite usar gratuitamente. A chave do estúdio fica restrita a esse combo. O pacote não cria contas externas nem usa credenciais do computador. **Não habilite modelos pagos no `studio-free`**; a combinação não garante custo zero por si só. Uma assinatura paga, acesso via OAuth ou preço desconhecido não significa API gratuita. Confira quotas e desative cobrança no provedor quando disponível.
2. Para reduzir a configuração, você pode preencher `OMNIROUTE_FREE_MODELS` em `.env` com IDs exatos separados por vírgula **antes do primeiro bootstrap**; ele criará o combo com esses modelos. IDs e preços mudam por conta/provedor, por isso não são inventados no instalador. Ao esgotar a quota, a rota respeita os erros/limites; a seleção dos membros do combo é sua lista permitida, não uma garantia de preço permanente.
3. **Redes sociais:** registre os aplicativos OAuth exigidos por YouTube, TikTok e Meta. Acrescente os pares correspondentes de `.env.example` à sua `.env`, sem sobrescrever os segredos gerados. Use as URLs de retorno informadas pelo Postiz e pela [documentação de provedores](https://docs.postiz.com/self-host/providers/overview). Depois execute `docker compose up -d postiz` e conecte os canais no painel Postiz.
4. **Estúdio:** em Configurações, consulte os canais autorizados, escolha cada destino e salve as opções de publicação por rede. Salve também o nome do canal e os limites para concluir o onboarding. Confira em Configurações se `llm_api_key` e `postiz_api_key` realmente foram salvas; o bootstrap pode ficar pendente por restrições da versão das APIs, contas Postiz preexistentes ou permissões.
5. **Voz:** coloque a voz Piper PT-BR `.onnx` e seu `.onnx.json` em `models/`, conferindo a licença. O padrão é `pt_BR-faber-medium.onnx`; ajuste `PIPER_MODEL` se usar outra. O teste técnico não precisa de voz nem de provedor.
6. **Opcionais:** chave YouTube para pesquisas, Telegram e SMTP são cadastrados no estúdio se você quiser esses recursos. Segredos emitidos por terceiros precisam ser obtidos nas contas respectivas.

Não é possível validar inferência real, OAuth ou publicação até você conectar essas contas. O instalador não publica nas redes.

## Operação e recuperação

```sh
docker compose ps -a
docker compose logs --tail=80 bootstrap
docker compose logs --tail=80 postiz omniroute temporal
docker compose up -d --build
docker compose restart
docker compose stop
```

Faça diagnóstico com `docker compose exec api python -m backend.doctor` (não publica nem usa tokens de inferência). Se bootstrap falhar, corrija a causa e execute `docker compose up -d --force-recreate bootstrap`. Para instalações anteriores com PostgreSQL/Redis separados, **leia [MIGRATION.md](MIGRATION.md) e migre antes de executar o novo start**. Para Postiz preexistente, cadastre `postiz_api_key` manualmente no estúdio. Para OmniRoute preexistente, cadastre `llm_api_key` e mantenha a rota compatível com a chave. Apagar `.env` não redefine bancos existentes: restaure o backup em vez de gerar novas senhas incompatíveis. **`docker compose down -v` apaga os volumes e o histórico.**

Todas as portas publicadas usam loopback; bancos, Redis e Temporal não têm portas no host. Para uma VPS, use inicialmente um túnel SSH para acessar os painéis. Para callbacks que exigem endereço público, configure domínio HTTPS/reverse proxy, ajuste `POSTIZ_PUBLIC_URL`, remova `NOT_SECURED` do Postiz e habilite cookies seguros no OmniRoute antes de expor os painéis. Esse endereço depende do seu domínio e não pode ser gerado localmente.

Postiz segue a infraestrutura do [Compose oficial](https://github.com/gitroomhq/postiz-docker-compose). OmniRoute usa a [imagem oficial publicada](https://github.com/cheaper-inference/OmniRoute/blob/release/v3.8.55/docs/guides/DOCKER_GUIDE.md). As imagens validadas são fixadas por digest no Compose; uma atualização deve ser testada antes de trocar os digests. Serviços auxiliares mantêm tags explícitas.

## OAuth Google e chaves locais

Consulte [OAUTH-E-CHAVES.md](OAUTH-E-CHAVES.md) para o erro 400 sem `client_id`, obtenção das credenciais Google/Meta/TikTok e conferência das chaves OmniRoute. Execute `python scripts/check_integrations.py` para diagnóstico local sem exibir valores.
