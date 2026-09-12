# ROADMAP — Gravador Inteligente

Última atualização: 2026-09-11

## Status atual

| Etapa | Status | Observação |
|-------|--------|------------|
| Segmentação | ✅ Funcional | Whisper tiny + regex B1-B5 + interpolação. Log JSON automático. |
| Tratamento de áudio | ✅ Funcional | Canal morto, ruído (noisereduce/ffmpeg), respiração, silêncio opcional, LUFS -16. |
| Edição (remoção de erros) | ✅ Funcional + testado | Gatilhos + similaridade textual. 22 testes no `tests/test_edicao.py`. |
| Montagem com vinhetas | ✅ Funcional | Abertura + cabeça + passagem + off + encerramento. Crossfade. Auditoria pós-montagem. |
| Pipeline orquestrador | ✅ Funcional | Conecta todas as etapas, log estruturado, CLI completa. |
| Testes (geral) | 🔴 Parcial | Só há testes para edição. Faltam testes para tratamento e montagem. |
| Documentação | ✅ Completada (2026-09-11) | README, arquitetura, roadmap, worklog, IDEA, .env.example. |
| Configuração externa | ✅ `.env.example` criado | `DIVISOR_WORKSPACE` com estrutura documentada. |
| CI/CD | 🔴 Ausente | Sem GitHub Actions ou similar. |
| Serviço web (FastAPI) | 🟡 Dependência presente, não usada | `fastapi` + `uvicorn` no `pyproject.toml` mas sem rotas implementadas. |

## Feito ✅

- [x] Pipeline completo `app/pipeline.py` (segmentação → tratamento → edição → montagem → auditoria)
- [x] Segmentação com Whisper + detecção de marcadores B1-B5
- [x] Tratamento: correção de canal morto, redução de ruído, respiração, LUFS
- [x] Edição com gatilhos + similaridade textual
- [x] Montagem com vinhetas e estrutura de rádio
- [x] Auditoria pós-montagem automática
- [x] CLI completa para cada etapa + pipeline
- [x] Logs estruturados (JSON) para segmentação, edição e pipeline
- [x] Testes para módulo de edição (`tests/test_edicao.py`, 22 testes)
- [x] README.md com instruções de uso
- [x] `.env.example` com `DIVISOR_WORKSPACE`
- [x] `docs/arquitetura_projeto.md` com fluxo e componentes
- [x] `docs/ROADMAP.md` (este arquivo)
- [x] `docs/worklog.md` com registro de atividades
- [x] `docs/IDEA.md` com índice de documentação
- [x] Limpeza de código legado (3 scripts de segmentação removidos)
- [x] `pyproject.toml` corrigido (`whisper-timestamped` → `openai-whisper` explícito)

## Próximos (priorizados)

### 🔴 Alto

1. **Testes para tratamento e montagem** — adicionar `tests/test_tratamento.py` (pelo menos `detectar_canal_morto` e `process` com ffmpeg mock) e `tests/test_montagem.py` (montagem com assets mock)
2. **Validar pipeline com áudio real** — executar o pipeline completo com um áudio de teste (ex: `test_audio.wav` que já está versionado) e verificar se os caminhos de saída, estrutura de diretórios e logs estão conforme esperado
3. **CI básico** — GitHub Actions que roda `pytest` e `ruff check` em cada push

### 🟡 Médio

4. **App `.__init__.py`** mais explícito — exportar as funções públicas de cada módulo para uso por outros projetos
5. **FastAPI como serviço separado** — se houver interesse em expor o pipeline como API, criar `app/server.py` ou projeto separado; se não, remover `fastapi`/`uvicorn` das dependências para não poluir instalação
6. **Configuração de log centralizada** — atualmente cada módulo chama `logging.basicConfig` independentemente; centralizar em um `app/logger.py` para evitar reconfiguração acidental

### 🟢 Baixo

7. **Tipo de saída configurável** — hoje sempre MP3; adicionar suporte a WAV para uso em estúdio
8. **Progress bar** — para áudios longos, mostrar progresso da transcrição Whisper (Whisper já tem `verbose=True` que loga, mas uma barra seria melhor)
9. **Cache de transcrição** — salvar transcrição Whisper em JSON e reutilizar em edições subsequentes (já tem suporte via `--json-transcricao`, mas poderia ser automático no pipeline)

## Histórico de versões

### 0.1.0 — 2026-09-11

- Pipeline completo
- README + docs
- .env.example
- Correção de dependências
- Limpeza de legado
