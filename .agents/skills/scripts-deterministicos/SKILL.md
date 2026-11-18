---
name: scripts-deterministicos
description: Executar tarefas mecânicas do estúdio sem gastar chamadas de modelo.
---

# scripts-deterministicos

Use backend.media para FFmpeg/ffprobe e backend.worker para fila, retenção e agendamento.
Download exige AUTHORIZED e evidência. Publicação pertence ao serviço, não a um sexto agente.
Subprocessos usam argumentos separados e timeout; não use shell=True. Retorne resumo, caminhos e falhas relevantes.
