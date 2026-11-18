## Contexto
App: GTA Studio (Video Studio), pipeline autônomo em 1080x1920 (9:16). Mesmo depois das últimas atualizações, o vídeo final sai sem o personagem, sem imagens da notícia, com texto fraco e com fundo neon aleatório. Além disso, o Avaliador reprova ou pede revisão por motivos que não dependem do vídeo (ex.: "test_audio é false", data da fonte "futura") e repete o mesmo texto em "Motivo completo" e "Correções sugeridas". A data de hoje deve ser sempre injetada nos agentes.

O pipeline passa a ter 6 agentes (os 5 atuais + o novo Redator). Execute na ordem, valide cada etapa e me reporte antes de seguir.

## 1. Diagnóstico (antes de alterar qualquer código)
- Liste os 5 agentes atuais e a função de cada um.
- Me diga onde estão salvos os assets de cada persona: imagem de referência, avatar, voz e dossiê (pasta, tabela e arquivo). Se não existirem, diga que não foram gerados.
- Para uma produção recente, rastreie por que o personagem e as imagens da notícia não aparecem no render:
  1. O asset foi gerado ou baixado?
  2. Foi salvo e o caminho existe no disco?
  3. Foi registrado na cena (campo asset/origem)?
  4. O renderizador usa esse caminho, ou ignora e cai em fallback?
- Mostre uma tabela por cena: asset esperado, caminho, existe (sim/não), usado no render (sim/não) e o motivo real da falha.
- Corrija as causas e confirme com uma produção de teste de 1 cena: personagem na tela + 1 print da notícia + gameplay + música.

## 2. Pasta /assets (eu vou colocando os arquivos lá)
- Monitore /assets automaticamente (watcher + botão "Reescanear"). Todo arquivo novo é registrado sem eu precisar usar a aba Upload.
- Estrutura: /assets/gameplay/, /assets/music/, /assets/sfx/, /assets/personas/{nome}/, /assets/images/, /assets/shorts/, /assets/clips/, /assets/uploads/.
- A categoria é inferida pela pasta e pode ser editada na "Biblioteca de assets". Cada asset guarda origem: "próprio/gerado", "press kit/oficial", "livre de direitos" ou "terceiros".
- Vídeos > 45s são fatiados em clipes de 10s (original intacto, último clipe < 3s junta ao anterior). Parâmetros configuráveis.
- A aba "Upload de mídia" continua existindo como alternativa e grava nas mesmas pastas.

## 3. Elenco de personagens com voz própria
Naturais, sem caricatura: a personalidade aparece no ritmo e na escolha de palavras, não em gritos, sotaque forçado ou bordão a cada frase.
- Liste os personagens que já existem. Proponha um elenco de 3 ORIGINAIS (sem copiar Johnny Bravo ou outro personagem protegido), com papéis distintos:
  - Apresentador: confiante e levemente vaidoso, humor seco.
  - Analista: calmo, cético, separa fato de rumor.
  - Repórter: ágil e direto, traz o "último minuto".
- Para cada um defina: nome, visual e personalidade; voz TTS própria em PT-BR (timbre, velocidade e pausas diferentes entre si); jeito de falar (tamanho das frases, vocabulário, formalidade); no máximo 2-3 expressões características, usadas com moderação; o que nunca faz (ex.: afirmar rumor como fato).
- Gere a imagem de referência de cada um UMA vez, salve em /assets/personas/{nome}/ e reutilize sempre.
- Em Configurações, mostre cada personagem com imagem, voz, dossiê e botão "ouvir amostra". Tudo editável.
- O roteiro marca quem fala em cada trecho. A voz muda conforme o personagem.

## 4. Elementos obrigatórios em TODO vídeo
- Gameplay (de /assets/gameplay/ e uploads), alternando entre os clipes: nunca o mesmo clipe duas vezes seguidas, nem clipes consecutivos do mesmo vídeo original, priorizando os menos usados. Cortes a cada 2-4s.
- Música de fundo leve (de /assets/music/), em volume baixo com ducking automático sob a narração, com fade in/out e normalização de volume. Não repita a mesma faixa em vídeos seguidos.
- Persona na tela: o avatar de quem está falando fica visível durante a fala, sem cobrir as legendas.
- Em notícias: prints da matéria (recortados, com destaque, sem banner de cookie/anúncio) e imagens da própria notícia, sincronizados com a fala. Em vídeo-fonte: trechos de no máximo 3-4s, variando o source_start entre cenas, com crédito automático do canal na tela e na descrição. Me avise antes de passar de 5s de terceiros no total.
- Fonte baixada vai para /temp/{id_producao}/, nunca edite o original. Se a mídia já existir localmente, copie em vez de baixar. Mantenha a pasta enquanto a produção estiver reprovada ou aguardando decisão manual e apague depois (7 dias, configurável).
- REMOVA o fundo neon/gradiente automático. Ele não pode ser fundo nem fallback. Neon só como detalhe discreto (moldura de print, legenda).
- Se faltar gameplay, música ou a imagem da persona, NÃO renderize. Pause a produção e avise: "Faltam assets: [lista]. Coloque em /assets/...".

## 5. Roteirista: texto explicativo, divertido e viral
Processo obrigatório:
1. Extraia da fonte uma lista de fatos: o que aconteceu, quem, quando, e o que é confirmado versus rumor.
2. Sintetize com suas próprias palavras. Nunca copie ou traduza a fonte frase por frase.
3. Estrutura: gancho nos primeiros 3s (pergunta, dado surpreendente ou afirmação forte, nunca "Olá pessoal"); contexto rápido; 2 a 4 pontos principais, um por cena; análise leve do personagem com humor; fechamento com pergunta ou gancho para comentário.
4. Explique como a um amigo que não acompanha o tema: sem jargão e sem enrolação. O humor vem de comparações sobre o assunto, sem piada genérica.
5. Tamanho conforme a duração do template (cerca de 2,5 palavras/s). Cada cena traz uma ideia diferente e um texto de tela próprio (nunca repetir o mesmo texto em cenas seguidas).
6. Rumor é identificado como rumor. Métricas da fonte (views, curtidas) entram como "segundo a fonte".
7. Cada cena informa o visual sugerido (gameplay, print, personagem, imagem relacionada).

## 6. NOVO agente: Redator (revisão do texto antes do render)
Entra depois do Roteirista/Editor e antes do render. Confere se o texto está coerente, coeso e bem escrito PARA NARRAÇÃO COM IA:
- Coerência e coesão: começo, meio e fim, transições entre cenas, sem contradição, sem repetir ideia, fiel aos fatos extraídos.
- Frases completas: nenhuma frase pode terminar cortada (ex.: "mostram que a.", "mais.").
- Adequação ao TTS: números e siglas por extenso ("GTA seis", "vinte e oito mil"), frases de até ~20 palavras, pontuação que gere pausas naturais, sem emoji, parênteses, hashtags ou abreviações que a voz leia errado.
- Fidelidade ao personagem que fala (tom e vocabulário do dossiê).
Regra anti-vai-e-volta: o Redator CORRIGE DIRETO erros de redação e só devolve ao Roteirista problemas estruturais (fato errado, ideia faltando). Máximo de 2 devoluções, que NÃO contam como tentativa das 5. Mostre no painel o texto antes e depois e o que foi alterado.

## 7. Verificações automáticas antes da avaliação (não são tentativas)
Antes de qualquer IA avaliar, rode checagens determinísticas e corrija sozinho o que falhar, sem consumir tentativa:
- Arquivo de áudio existe, sem cortes abruptos, sem silêncios longos, volume normalizado (~-14 LUFS).
- Legendas sincronizadas com o áudio REAL (alinhamento por transcrição com timestamps), nunca "estimated_by_phrase".
- Última frase de cada cena termina com ponto; duração final dentro da tolerância do template.
- Existem gameplay, música e persona no render; cenas seguidas não repetem clipe nem source_start.
- Créditos e fonte preenchidos automaticamente a partir dos metadados da fonte (canal, URL, direitos).
Se uma checagem não puder ser corrigida, mostre o erro real no painel.

## 8. Avaliação por duas IAs em conjunto
Ambas avaliam o MESMO render, em paralelo e de forma independente (uma não vê a nota da outra). Ambas recebem o vídeo mp4 real, o áudio, a transcrição, as legendas, frames, o briefing e a DATA DE HOJE (nunca tratar a data de uma fonte recente como "futura").

**IA 1: Avaliador (visão crítica/técnica).** Mantém os 12 critérios atuais (gancho, narrativa, áudio, legendas, cortes, ritmo, formato, duração, briefing, originalidade, exatidão, direitos e créditos), cada um com nota mínima e peso editáveis em Configurações.

**IA 2: Pessoa (espectador comum).** Age como uma pessoa de 18-34 anos que gosta de games, vendo o Short no celular. Dá notas de 0 a 10, em linguagem simples ("achei", "me perdi", "dei risada"), sem jargão técnico:
- Prenderia minha atenção depois de 3s?
- Entendi o assunto?
- Achei divertido?
- A voz e o visual são agradáveis?
- Compartilharia ou comentaria?
Devolve também uma nota geral, um motivo curto e o momento exato (tempo) em que ficaria entediado, se houver. Cada nota tem mínimo configurável (padrão 6).

**Decisão:** Aprovado quando TODOS os critérios do Avaliador e da Pessoa estão no mínimo ou acima. A média é só informativa e não decide. Mostre no painel as notas das duas IAs lado a lado; se divergirem em 3+ pontos, destaque.

## 9. Refação sem revisão desnecessária
- Critério que passou na nota mínima fica TRAVADO: não é alterado e não é reavaliado nas tentativas seguintes (a nota é mantida). Isso vale para o Avaliador e para a Pessoa.
- Só critérios abaixo do mínimo geram refação, e a refação é CIRÚRGICA: refaça apenas a parte afetada (ex.: narração truncada da cena 2 = regerar só o TTS da cena 2), sem refazer o vídeo todo. Reavalie somente os critérios reprovados e os que dependem do trecho alterado.
- Observações sobre critérios que passaram não geram refação. Aparecem como "sugestões opcionais", separadas.
- Todo defeito citado precisa de evidência (tempo, frame ou campo) ligada a um critério. Sem evidência, não conta. Dado que não dá para verificar (ex.: views da fonte) não reprova: vira "segundo a fonte".
- Falta de insumo (ex.: não enviar o áudio) é erro do pipeline e será corrigido na etapa 7, nunca reprovação do vídeo.
- Painel sem duplicação: uma única lista "Problema → Evidência → Correção", sem repetir o mesmo texto em "Motivo" e "Correções".
- Máximo de 5 tentativas (configurável). Depois disso: "Aguardando decisão manual" com botões Aprovar manualmente / Descartar (registrando quem e quando). Esses botões existem a qualquer momento.
- O render de cada tentativa é salvo ANTES da avaliação e fica disponível na pré-visualização, mesmo reprovado.

## Critérios de aceite
- Sei onde estão os assets das personas e o diagnóstico mostra por que não apareciam.
- Todo vídeo mostra gameplay alternada, música leve e a persona que fala. Sem fundo neon.
- Notícias mostram prints e imagens da matéria na hora da fala.
- Cada personagem tem voz e jeito de falar distintos e naturais, com amostra em Configurações.
- O Redator corrige o texto antes do render e não deixa frase cortada nem número ilegível para a voz.
- Avaliador e Pessoa avaliam juntos e suas notas aparecem lado a lado.
- Critério aprovado não é alterado nem reavaliado, e a refação mexe só no que reprovou.
- Nenhuma reprovação por falta de insumo, e nenhum texto repetido no painel.
- Falta de assets obrigatórios pausa a produção com aviso claro.
- Colocar arquivos em /assets os registra automaticamente.

Ao final, liste os arquivos alterados, onde ficam as pastas e como testar cada item.