"""Install all requested professional skills into .agents/skills and sync with .claude/skills."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / '.agents' / 'skills'
CLAUDE_DIR = ROOT / '.claude' / 'skills'

SKILLS_DATA = {
    "superpowers": {
        "description": "Planejamento estruturado, depuração metódica, TDD e execução controlada de tarefas de engenharia de software.",
        "content": """# superpowers

## Função no Estúdio
Skill de engenharia estruturada e resolução metódica de problemas. Garante que qualquer implementação siga princípios de decomposição de tarefas, validação contínua e tolerância zero a suposições não comprovadas.

## Diretrizes de Operação
1. **Planejamento Primeiro**: Antes de qualquer modificação, liste os requisitos, componentes impactados e cenários de teste.
2. **Decomposição em Unidades Atômicas**: Quebre alterações complexas em commits/passos verificáveis independentemente.
3. **Execução Disciplinada**: Altere uma unidade lógica por vez, validando regressões após cada mudança.
4. **Resolução de Causas Raiz**: Nunca aplicar correções de contorno (workarounds) sem compreender a causa fundamental da falha.
"""
    },
    "frontend-design": {
        "description": "Design de interfaces modernas, responsivas e profissionais para aplicações web e estúdios de vídeo.",
        "content": """# frontend-design

## Função no Estúdio
Especialista em UI visual moderna, paletas de cores imersivas, tipografia legível e hierarquia visual voltada para criadores de conteúdo gamer e audiovisual.

## Diretrizes de Operação
1. **Design System & Consistência**: Seguir paletas escuras (dark mode estilo Vice City / Cyberpunk), contrastes WCAG AA e espaçamentos simétricos.
2. **Micro-interações**: Aplicar feedback visual suave em botões, badges, modais e transições de tela.
3. **Exibição Audiovisual**: Players verticais 9:16 com controles responsivos, safe zones e overlays limpos.
"""
    },
    "react-best-practices": {
        "description": "Padrões de arquitetura, ciclo de vida, gerenciamento de estado e performance em React e Next.js.",
        "content": """# react-best-practices

## Função no Estúdio
Auditoria e desenvolvimento de componentes React eficientes, modularizados e livres de re-renderizações desnecessárias na interface do estúdio.

## Diretrizes de Operação
1. **Composição e Separação de Responsabilidades**: Componentes de apresentação isolados de chamadas de API e regras de negócio.
2. **Hooks Personalizados**: Encapsular lógica assíncrona (como polling de render ou status do pipeline) em custom hooks limpos.
3. **Imutabilidade e Estado Previsível**: Utilizar estados atômicos e evitar mutações diretas de objetos e arrays.
"""
    },
    "web-design-guidelines": {
        "description": "Diretrizes de usabilidade, acessibilidade (a11y), responsividade e padrões modernos da web.",
        "content": """# web-design-guidelines

## Função no Estúdio
Garantia de usabilidade de alto nível, contraste adequado, acessibilidade via teclado e visualização impecável em qualquer resolução de monitor.

## Diretrizes de Operação
1. **Acessibilidade**: Elementos interativos com atributos ARIA corretos, estados de foco visíveis e suporte a navegação por teclado.
2. **Tipografia e Safe Zones**: Manter textos informativos em tamanhos legíveis (>13px) e contrastes superiores a 4.5:1.
3. **Resiliência a Falhas**: Tratamento elegante de estados vazios, erros de rede e carregamento de mídias.
"""
    },
    "playwright-cli": {
        "description": "Automação e testes com navegadores headless, capturas de tela reais de matérias e validação E2E.",
        "content": """# playwright-cli

## Função no Estúdio
Captura autêntica de manchetes e imagens de matérias jornalísticas (Playwright Chromium) e testes de ponta a ponta na interface do usuário.

## Diretrizes de Operação
1. **Captura Fiel de Notícias**:
   - Bloquear cookies, anúncios, pop-ups e banners promocionais via injeção CSS antes do screenshot.
   - Capturar seletores pontuais (`h1`, `article p`, `article img`) gerando prints limpos e transparentes.
2. **Segurança de Navegação**:
   - Bloquear requisições a redes privadas/localhost e URLs não HTTPS.
   - Timeout rígido para evitar congelamento de workers em matérias pesadas.
"""
    },
    "code-review": {
        "description": "Revisão técnica de código para identificar falhas lógicas, vulnerabilidades, débitos técnicos e anti-patterns.",
        "content": """# code-review

## Função no Estúdio
Auditoria técnica pré-merge e pós-refatoração no backend FastAPI e frontend Next.js do GTA Studio.

## Diretrizes de Operação
1. **Critérios de Revisão**:
   - Robustez no tratamento de exceções (nunca engolir erros sem log).
   - Gerenciamento seguro de recursos (fechamento de conexões, descritores de arquivo e processos FFmpeg).
   - Ausência de vazamento de chaves e segredos em logs e artefatos.
2. **Modularidade**: Funções enxutas com escopo único e contratos de tipagem Pydantic / TypeScript rigorosos.
"""
    },
    "security-review": {
        "description": "Auditoria de segurança, controle de acesso, integridade de arquivos, proteção contra SSRF e sanitização de inputs.",
        "content": """# security-review

## Função no Estúdio
Proteção estrita da infraestrutura local, containers Docker, dados confidenciais e integridade das bibliotecas de mídia do usuário.

## Diretrizes de Operação
1. **Prevenção de SSRF**: Validação rigorosa de URLs de fontes antes de qualquer requisição (impedindo acesso a IPs privados e portas não padrão).
2. **Inviolabilidade de Arquivos**: Validação de caminhos via `safe_file` e `safe_asset` para impedir path traversal.
3. **Preservação de Mídias**: Nunca apagar, sobrescrever ou alterar arquivos da pasta original `/assets/`.
"""
    },
    "systematic-debugging": {
        "description": "Metodologia científica para identificação e resolução da causa raiz de defeitos de software e renderização.",
        "content": """# systematic-debugging

## Função no Estúdio
Diagnóstico estruturado para falhas em pipelines de renderização, dessincronia de áudio/vídeo, estouro de timeouts e erros em APIs.

## Diretrizes de Operação
1. **Reprodução Mínima**: Reproduzir o defeito com o menor conjunto de dados possível antes de tentar alterações no código.
2. **Isolamento de Variáveis**: Inspecionar logs (`media-last-error.log`, traces de eventos) e separar falhas de FFmpeg de falhas de modelos ou dados.
3. **Confirmação com Testes**: Criar teste automatizado que falha antes da correção e passa após a solução.
"""
    },
    "test-driven-development": {
        "description": "Desenvolvimento guiado por testes (TDD) para garantir corretude de contratos, codecs e fluxos de trabalho.",
        "content": """# test-driven-development

## Função no Estúdio
Desenvolvimento de novas funcionalidades e correções garantindo cobertura de testes antes da implementação.

## Diretrizes de Operação
1. **Ciclo Red-Green-Refactor**:
   - Escreva o teste unitário ou de integração com os inputs e saídas esperadas.
   - Execute o teste e confirme a falha pelo motivo correto.
   - Implemente o código mínimo necessário para o teste passar.
   - Refatore preservando a aprovação do teste.
"""
    },
    "vercel-composition-patterns": {
        "description": "Padrões modernos de composição de componentes React, Server/Client components e arquitetura Next.js.",
        "content": """# vercel-composition-patterns

## Função no Estúdio
Arquitetura de componentes Next.js / React no painel de controle do estúdio, separando streaming e renderização de dados.

## Diretrizes de Operação
1. **Divisão de Responsabilidades**: Isolar Server Components (busca de dados estáveis) de Client Components (interatividade do estúdio).
2. **Composição Limpa**: Evitar props drilling usando composição direta (`children` e slots).
3. **Feedback Instantâneo**: Estados de loading (skeletons) e fallbacks com React Suspense.
"""
    },
    "performance-optimization": {
        "description": "Otimização de tempo de renderização, uso de CPU/GPU, vazamento de memória e processamento assíncrono.",
        "content": """# performance-optimization

## Função no Estúdio
Maximização de eficiência em montagens FFmpeg, consultas SQLite, geração de áudio TTS e cache de assets intermediários.

## Diretrizes de Operação
1. **Reutilização e Caching**: Evitar renderizar novamente trechos idênticos de vídeo (`segment-cache` por hash SHA256).
2. **Paralelismo Controlado**: Limitar threads de FFmpeg (`-threads 2`) para evitar exaustão de recursos no host.
3. **Filtragem de Processos**: Liberar subprocessos zumbis e aplicar timeouts determinísticos em todas as operações de E/S.
"""
    },
    "cicd-automation": {
        "description": "Automação de rotinas de verificação, testes contínuos, validação de tipos e integridade de containers.",
        "content": """# cicd-automation

## Função no Estúdio
Manutenção de pipelines de homologação rápida, verificações sintáticas e testes automatizados de ponta a ponta.

## Diretrizes de Operação
1. **Verificação Pré-execução**: Executar validação de tipagem Python (`mypy` / `pytest`) e sintaxe TypeScript antes de homologações.
2. **Build Limpo**: Manter containers Docker reproduzíveis sem poluição de arquivos temporários.
3. **Integridade de Dependências**: Monitorar compatibilidade entre versões de Python, PyAV, FFmpeg e pacotes Node.
"""
    },
    "remotion-best-practices": {
        "description": "Boas práticas de composição audiovisual programática com React, animações temporizadas, tipografia e transições.",
        "content": """# remotion-best-practices

## Função no Estúdio
Desenho de layouts de vídeo verticais 9:16 (1080x1920), animações matemáticas suaves baseadas em frames (spring, interpolate) e sincronização visual.

## Diretrizes de Operação
1. **Frame-Rate e Proporção**: Produções sempre em 30 FPS ou 60 FPS, 1080x1920 (9:16 vertical), com tempo baseado em segundos absolutos e frames determinísticos.
2. **Curvas de Animação**: Utilizar funções de interpolação suaves (ease-out, spring) em cards de texto e entradas de mídia em vez de cortes secos.
3. **Safe Zones para Redes Sociais**:
   - Manter informações críticas entre Y=200px e Y=1500px para evitar sobreposição pelos botões de curtir/comentar do TikTok/Shorts.
"""
    },
    "ffmpeg-skill": {
        "description": "Operação avançada de filtros FFmpeg, redimensionamento com proporção preservada, transições, ducking e exportação H.264.",
        "content": """# ffmpeg-skill

## Função no Estúdio
Engenharia de linha de comando FFmpeg para corte, composição de múltiplas camadas, overlay com alpha, mixagem de áudio e aceleração gráfica.

## Diretrizes de Operação
1. **Cálculo de Proporção e Escala**:
   - Para fundo vertical: `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1`.
   - Para cards e capturas com Ken Burns: `zoompan=z='min(zoom+0.0008,1.15)':d=1:s=1080x1920:fps=30`.
2. **Composição em Camadas (filter_complex)**:
   - Camada 0: Gameplay / Fundo animado.
   - Camada 1: Card editorial ou trecho de vídeo da fonte com borda e sombra.
   - Camada 2: Avatar da persona com animação de flutuação e respiração.
   - Camada 3: Legendas sincronizadas (ASS) e badge temático superior.
3. **Mixagem de Áudio**:
   - Narração primária no canal frontal, música ambiente atenuada com ducking (`sidechaincompress`) para garantir clareza vocal.
"""
    },
    "fal-video-generation": {
        "description": "Diretrizes e integração para geração de clipes visuais e cenas cinematográficas via modelos de IA de vídeo.",
        "content": """# fal-video-generation

## Função no Estúdio
Planejamento e orquestração de prompts visuais para modelos generativos de vídeo quando autorizado pelo operador para cenas conceituais.

## Diretrizes de Operação
1. **Consistência de Prompt**: Descrever iluminação, enquadramento cinematográfico, paleta de cores (Miami Vice, pôr do sol néon) e ausência de deformações.
2. **Duração Econômica**: Gerar apenas trechos curtos de 2 a 4 segundos para manter dinamismo e controle de custos.
3. **Atribuição Obrigatória**: Registrar no manifesto de transparência quando uma cena for sintética/generativa.
"""
    },
    "fal-video-edit": {
        "description": "Transformação, remixagem e aprimoramento de vídeos existentes através de processamento por IA.",
        "content": """# fal-video-edit

## Função no Estúdio
Aprimoramento de qualidade visual, interpolação de quadros, remoção de ruído e estilização de trechos de mídia autorizados.

## Diretrizes de Operação
1. **Preservação de Direitos**: Nunca aplicar edição generativa sobre material de terceiros sem licença de uso transformativo.
2. **Integridade de Fatos**: Não alterar o conteúdo factual de trechos jornalísticos ou documentos oficiais exibidos no vídeo.
"""
    },
    "remotion-captions": {
        "description": "Legendas dinâmicas sincronizadas palavra por palavra com pop-in, destaque de cor e posicionamento seguro.",
        "content": """# remotion-captions

## Função no Estúdio
Desenvolvimento de legendas dinâmicas de alto impacto visual no formato ASS ou composição direta, sincronizadas com Whisper ASR.

## Diretrizes de Operação
1. **Destaque por Palavra (Word-Level Karaoke)**:
   - Palavra atual ganha escala ampliada (112%) e cor de realce (ciano, amarelo ou rosa Vice City).
   - Palavras precedentes e antecedentes mantêm tom branco puro com contorno preto espesso (outline de 4px).
2. **Quebra e Ritmo**:
   - Máximo de 3 a 5 palavras por grupo na tela para manter a leitura instantânea em telas verticais de smartphone.
   - Posição vertical segura centrada (Y=740px a Y=820px) para não colidir com o avatar nem com o título do post.
"""
    },
    "video-editing-vexjoy": {
        "description": "Direção de montagem, ritmo de cortes rápidos, seleção de momentos épicos e cadência para vídeos virais de alta retenção.",
        "content": """# video-editing-vexjoy

## Função no Estúdio
Especialista em retenção de audiência e ritmo editorial (cuts-per-minute, curva de atenção e pacing de gameplay).

## Diretrizes de Operação
1. **Regra dos Primeiros 2 Segundos**: Gancho impactante visual e sonoro imediato; sem introduções lentas.
2. **Ritmo de Corte Contínuo**:
   - Intervalo médio entre cortes de 1.8s a 2.5s para manter a taxa de retenção elevada.
   - Alternância entre plano de gameplay, corte para manchete/screenshot da fonte e reação do avatar.
3. **Identificação do Segundo de Tédio (`boring_second`)**: Interromper qualquer sequência visual monótona antes do 4º segundo consecutivo.
"""
    },
    "remotion-render": {
        "description": "Pipeline de renderização de alta velocidade para MP4, controle de codecs e geração de miniaturas de capa.",
        "content": """# remotion-render

## Função no Estúdio
Padronização da renderização final para compatibilidade com YouTube Shorts, TikTok e Instagram Reels.

## Diretrizes de Operação
1. **Especificações Técnicas de Saída**:
   - Contêiner: MP4 (`-movflags +faststart`).
   - Codec de Vídeo: H.264 (libx264), High Profile, CRF 22, pixel format `yuv420p`.
   - Resolução: 1080x1920 (proporção 9:16).
   - Codec de Áudio: AAC estéreo, 48kHz, 192kbps.
2. **Validação de Pré-Voo**: Confirmar duração, resolução, ausência de quadros pretos e integridade do áudio antes da entrega.
"""
    }
}

def main():
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    created = 0

    for name, data in SKILLS_DATA.items():
        # Agent skill
        agent_skill_dir = AGENTS_DIR / name
        agent_skill_dir.mkdir(parents=True, exist_ok=True)
        agent_skill_file = agent_skill_dir / 'SKILL.md'
        content = f"---\nname: {name}\ndescription: {data['description']}\n---\n\n{data['content'].strip()}\n"
        agent_skill_file.write_text(content, encoding='utf-8')

        # Claude skill mirror
        claude_skill_dir = CLAUDE_DIR / name
        claude_skill_dir.mkdir(parents=True, exist_ok=True)
        (claude_skill_dir / 'SKILL.md').write_text(content, encoding='utf-8')
        created += 1

    print(f"Sucesso: {created} novas skills criadas e espelhadas em .agents/skills/ e .claude/skills/.")

if __name__ == '__main__':
    main()
