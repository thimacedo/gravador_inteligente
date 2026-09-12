# ROADMAP — Gravador Inteligente

Última atualização: 2026-09-11 (commit `3cf7863`)

## Status atual

| Etapa | Status | Observação |
|-------|--------|------------|
| Segmentação | ✅ Funcional | Whisper tiny + regex B1-B5 + interpolação. Log JSON automático. |
| Tratamento de áudio | ✅ Funcional | Canal morto, ruído (noisereduce/ffmpeg), respiração, silêncio opcional, LUFS -16. |
| Edição (remoção de erros) | ✅ Funcional + testado | Gatilhos + similaridade textual. 22 testes no `tests/test_edicao.py`. |
| Montagem com vinhetas | ✅ Funcional | Abertura + cabeça + passagem + off + encerramento. Crossfade. |
| Auditoria pós-montagem | ✅ Funcional (2026-09-11) | `auditar_boletim()` implementada. Verifica LUFS, duração, existência. |
| Pipeline orquestrador | ✅ Funcional | Conecta todas as etapas, log estruturado, CLI completa. |
| Testes (geral) | 🟡 Melhorado | Agora tem testes para edição (22), tratamento (16) e montagem (15) = 59 testes total. |
| Documentação | ✅ Completada (2026-09-11) | README, arquitetura, roadmap, worklog, IDEA, .env.example. |
| CI/CD | ✅ GitHub Actions | `.github/workflows/ci.yml` roda ruff, black, pytest em cada push/PR. |
| Configuração externa | ✅ `.env.example` criado | `DIVISOR_WORKSPACE` com estrutura documentada. |
| Serviço web (FastAPI) | 🟢 Removido das dependências | `fastapi`/`uvicorn` removidos do `pyproject.toml`. Se quiser API futuramente, pode virar optional ou projeto separado. |

## Feito ✅

- [x] Pipeline completo `app/pipeline.py` (segmentação → tratamento → edição → montagem → auditoria)
- [x] Segmentação com Whisper + detecção de marcadores B1-B5
- [x] Tratamento: correção de canal morto, redução de ruído, respiração, LUFS
- [x] Edição com gatilhos + similaridade textual
- [x] Montagem com vinhetas e estrutura de rádio
- [x] Auditoria pós-montagem automática (`auditar_boletim()`)
- [x] CLI completa para cada etapa + pipeline
- [x] Logs estruturados (JSON) para segmentação, edição e pipeline
- [x] Testes para módulo de edição (`tests/test_edicao.py`, 22 testes)
- [x] Testes para módulo de tratamento (`tests/test_tratamento.py`, 16 testes)
- [x] Testes para módulo de montagem (`tests/test_montagem.py`, 15 testes)
- [x] README.md com instruções de uso
- [x] `.env.example` com `DIVISOR_WORKSPACE`
- [x] `docs/arquitetura_projeto.md` com fluxo e componentes
- [x] `docs/ROADMAP.md` (este arquivo)
- [x] `docs/worklog.md` com registro de atividades
- [x] `docs/IDEA.md` com índice de documentação
- [x] Limpeza de código legado (3 scripts de segmentação removidos)
- [x] `pyproject.toml` corrigido (`whisper-timestamped` → `openai-whisper`, FastAPI removido)
- [x] CI: `.github/workflows/ci.yml` (ruff + black + pytest)
- [x] `assets/` com placeholders de vinheta para teste (substituir por reais)

## Próximos (priorizados)

### 🔴 Alto

1. **Validar pipeline com áudio de produção** — rodar o pipeline completo com áudio de boletim real (com marcadores B1–B5) e verificar se segmentação, edição, montagem e auditoria funcionam end-to-end com conteúdo real.
2. **Substituir assets de vinheta placeholder** — os MP3 em `assets/vinhetas/boletim/` são silêncio gerado por ffmpeg. Substituir por vinhetas reais de TJRN radio antes de usar em produção.
3. **Testes com áudio real de vinheta** — os testes de montagem usam mocks de AudioSegment. Adicionar testes com áudio real de vinheta quando disponível para validar crossfade e estrutura.

### 🟡 Médio

4. **App `.__init__.py`** mais explícito — exportar as funções públicas de cada módulo para uso por outros projetos.
5. **Configuração de log centralizada** — atualmente cada módulo chama `logging.basicConfig` independentemente; centralizar em um `app/logger.py` para evitar reconfiguração acidental.
6. **Pipeline com tratamento habilitado** — testar com `--pular-tratamento` removido para validar o pipeline completo (segmentação + tratamento + edição + montagem + auditoria) em áudio real.

### 🟢 Baixo

7. **Tipo de saída configurável** — hoje sempre MP3; adicionar suporte a WAV para uso em estúdio.
8. **Progress bar** — para áudios longos, mostrar progresso da transcrição Whisper (Whisper já tem `verbose=True` que loga, mas uma barra seria melhor).
9. **Cache de transcrição** — salvar transcrição Whisper em JSON e reutilizar em edições subsequentes (já tem suporte via `--json-transcricao`, mas poderia ser automático no pipeline).

## Histórico de versões

### 0.1.1 — 2026-09-11

- `auditar_boletim()` implementada em `app/montagem_boletins.py`
- Correção de bug: `tratar_config` → `tratamento_config` no CLI do pipeline
- `assets/vinhetas/boletim/`: placeholders de vinheta para teste
- Pipeline validado end-to-end com `test_audio.wav`
- ROADMAP atualizado com status dos 3 commits mais recentes

### 0.1.0 — 2026-09-11

- Pipeline completo
- README + docs
- .env.example
- Correção de dependências
- Limpeza de legado
- CI básico
- Testes de tratamento e montagem
- Lint/format cleanup
