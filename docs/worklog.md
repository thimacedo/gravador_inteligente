# Worklog — Gravador Inteligente

Registro cronológico de atividades, decisões e mudanças no projeto.

---

## 2026-09-11 — Auditoria + limpeza + documentação

**Objetivo:** Auditar o projeto, limpar código legado e criar documentação base.

### Auditoria

- Mapeie a estrutura do projeto: `gravador_inteligente/` é o diretório real do pipeline, não `DIVISOR/` na raiz
- Identifique que `segmentar_boletins.py`, `segmentar_com_transcricao_anterior.py` e `run_segment.py` duplicam funcionalidade já presente em `app/segmentacao_boletins.py`
- Verifiquei que `whisper-timestamped` está no `pyproject.toml` mas não é usado pelo código (o código importa `whisper` diretamente, que resolve para `openai-whisper`)
- Constatei ausência total de documentação (sem README, sem .env.example, sem docs/)

### Decisões técnicas

1. **Fonte única de segmentação**: `app/segmentacao_boletins.py` é a versão atualizada com API de alto nível `segmentar_audio()`. Os três scripts legados foram removidos.
2. **Dependência de Whisper**: substituí `whisper-timestamped>=1.0.0` por `openai-whisper>=20231117` no `pyproject.toml` porque o código usa `import whisper` (que resolve para `openai-whisper`).
3. **`.gitignore`**: já cobria `segmentar_com_transcricao_anterior.py` e `run_segment.py`; adicionei `segmentar_boletins.py` (agora deletado), `*.png`, `test_audio.wav`, `*.log` para evitar que artfatos de teste/versionamento sem propósito voltem.
4. **Documentação**: criei README completo, `.env.example`, e 4 documentos em `docs/`.

### Arquivos criados/alterados

- `README.md` (novo) — instrução de uso, estrutura, configuração
- `.env.example` (novo) — variável `DIVISOR_WORKSPACE`
- `docs/arquitetura_projeto.md` (novo) — visão geral, fluxo, componentes
- `docs/ROADMAP.md` (novo) — status, próximos passos
- `docs/worklog.md` (novo) — este arquivo
- `docs/IDEA.md` (novo) — índice de documentação
- `pyproject.toml` (alterado) — dependência de Whisper corrigida
- `.gitignore` (alterado) — adicionado `segmentar_boletins.py`, `*.png`, `test_audio.wav`, `*.log`

### Commits

- `e3bb56b` — chore: remove legado de segmentação inline + pipeline com prefixo e auditoria auto
- (em processo) — docs: adicionar README, .env.example, docs/ + fix pyproject.toml

---

## 2026-09-09 — Correção de bug em detecção de repetições

**Problema:** `detectar_repeticoes()` na linha 261 usava `continue` quando a janela temporal era excedida, o que faria a função continuar verificando frases anteriores mais distantes (incorreto — a janela é para trás, então ao extrapolar a janela você já não deve verificar frases anteriores).

**Correção:** Trocar `continue` por `break` na linha 261 de `app/edicao_boletins.py`.

**Commit:** `d205b48` — fix: corrigir detecção de janela temporal em detectar_repeticoes - continue → break

---

## 2026-09-08 — Versão inicial do pipeline

**Objetivo:** Criar estrutura básica do pipeline de produção de boletins.

### Módulos criados

- `app/pipeline.py` — orquestrador principal com CLI
- `app/segmentacao_boletins.py` — segmentação via Whisper
- `app/tratamento_audio.py` — limpeza de áudio
- `app/edicao_boletins.py` — detecção e remoção de repetições
- `app/montagem_boletins.py` — montagem com vinhetas

### Testes

- `tests/test_edicao.py` — 22 testes para módulo de edição

### Commit

- `5daf7ab` — feat: módulos de tratamento, edição, montagem e pipeline de boletins

---

## 2026-09-08 — Preparação inicial

- `40437f7` — test: add test_audio.wav file
- `7b9bca2` — chupeta
