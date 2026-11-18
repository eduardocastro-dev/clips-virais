# Aplicação do patch V8 sem perder assets

1. Faça backup do projeto, incluindo `data/`, `assets/`, `models/` e `.env`.
2. Extraia os arquivos do ZIP patch na raiz `Clips-Virais`. Preserve as pastas e arquivos do usuário.
3. Execute `docker compose up -d --build api worker web`.
4. Faça o diagnóstico `docker compose exec api python -m backend.migrate_art_v8` (somente leitura).
5. Confirme os hashes listados no relatório e execute `docker compose exec api python -m backend.migrate_art_v8 --apply` para arquivar apenas sprites v7 **não alterados**, em `_antigo`.
6. Confirme no painel a referência Dante, a galeria de assets, a opção de upload de poses e a pré-visualização de zonas seguras.
7. Habilite `Escritor aceita imagens` nas configurações apenas com modelo multimodal operacional.
8. Gere um vídeo com uma fonte de licença registrada; revise manifesto e MP4 antes da publicação manual.

Não execute `docker compose down -v`. Este patch não toca no banco nem nas credenciais e não publica nas redes.
