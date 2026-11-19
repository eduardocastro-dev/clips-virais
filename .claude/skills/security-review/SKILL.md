---
name: security-review
description: Auditoria de segurança, controle de acesso, integridade de arquivos, proteção contra SSRF e sanitização de inputs.
---

# security-review

## Função no Estúdio
Proteção estrita da infraestrutura local, containers Docker, dados confidenciais e integridade das bibliotecas de mídia do usuário.

## Diretrizes de Operação
1. **Prevenção de SSRF**: Validação rigorosa de URLs de fontes antes de qualquer requisição (impedindo acesso a IPs privados e portas não padrão).
2. **Inviolabilidade de Arquivos**: Validação de caminhos via `safe_file` e `safe_asset` para impedir path traversal.
3. **Preservação de Mídias**: Nunca apagar, sobrescrever ou alterar arquivos da pasta original `/assets/`.
