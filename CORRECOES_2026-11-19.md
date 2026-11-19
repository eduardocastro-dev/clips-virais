# Correções GTA Studio — 19/11/2026

## Correções incluídas
- Redator: correção de string quebrada em `backend/redator.py` que causava erro de sintaxe.
- Radar: ação de limpar oportunidades com endpoint autenticado `DELETE /api/opportunities`, preservando vídeos e fontes.
- Prontos para postar: exclusão de uma publicação ainda não confirmada via `DELETE /api/publications/{id}`, preservando o arquivo de vídeo e o histórico publicado.
- Agentes: limpeza de jobs concluídos ou falhos sem eliminar trabalhos ativos.
- Worker: reavalia oportunidades descobertas a cada 60 segundos com modo automático ativo, registra motivo de bloqueio e mantém a fila funcionando quando ocorre falha no agendador.
- Interface: exibe diagnóstico do agendador e informações de erro HTTP mais úteis.

## Escopo e segurança
O commit preserva o `.gitignore` da branch principal, os endpoints já existentes e o restante da interface Video Studio. Não inclui modelos `.onnx`, arquivos de áudio, backups locais ou credenciais encontrados no pacote.

## Implantação
```powershell
git pull origin main
docker compose build --no-cache api worker web
docker compose up -d --force-recreate api worker web
docker compose ps
docker compose logs --tail=200 api worker web
```

Não use `docker compose down -v`: volumes persistentes contêm dados e configurações.

## Verificação
Os 40 arquivos Python do backend presentes no ZIP corrigido passaram na análise sintática. Testes de integração e execução real em Docker não foram executados aqui. Monitore o status do agendador e os logs após o deploy.
