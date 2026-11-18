---
name: cache-de-dados
description: Reutilizar consultas de pesquisa e métricas com validade explícita.
---

# cache-de-dados

Use backend.core.cache_get/cache_set. Inclua plataforma, parâmetros e identidade da consulta na chave.
Metadados: TTL 3600s; busca: 1800s; métricas: 3600s. Não use cache expirado como observação atual.
Ausência de métrica é null, nunca zero inventado. Não armazene credenciais no cache.
