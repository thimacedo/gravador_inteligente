# Gravador Inteligente

Pipeline de processamento de áudio para **TJRN radio** — gera automaticamente os boletins diários a partir de uma única gravação contendo múltiplos boletins (B1–B5), aplicando segmentação, limpeza, edição de erros e montagem com vinhetas.

## O que ele faz

Recebe um áudio longo (ex: `06_JUL_B1-B5.mp3`) e produz, para cada boletim detectado:

1. **Segmentação** — detecta os marcadores `B1`, `B2`, `B3`, `B4`, `B5` na transcrição Whisper e corta o áudio em arquivos individuais.
2. **Tratamento** — correção de canal morto (stereo assimétrico → mono), redução de ruído, atenuação de respirações, remoção opcional de silêncios longos e normalização LUFS (-16).
3. **Edição** — detecta e remove repetições de locução via duas estratégias:
   - Palavras-gatilho (`repete`, `novamente`, `de novo` etc.) com retrocesso inteligente
   - Detecção de repetições textuais via similaridade `difflib.SequenceMatcher`
4. **Montagem** — insere vinhetas (abertura, passagem, encerramento) e estrutura o boletim como:
   ```
   VHT_ABERTURA + CABEÇA (manchete) + VHT_PASSAGEM + OFF (corpo) + VHT_ENCERRAMENTO
   ```
5. **Auditoria automática** — após a montagem, roda verificação de qualidade e reporta problemas.

## Pré-requisitos

- **Python 3.11+**
- **FFmpeg** instalado e no `PATH` (obrigatório para todas as operações de áudio)
- **Git** (para clonar o repositório)

### Sistema recomendado

O pipeline é pesado em CPU (Whisper carrega modelo + transcreve + edita). Um processador moderno sem GPU funciona, mas transcrever áudio longo leva vários minutos.

| Componente     | Observação                                                |
|----------------|-----------------------------------------------------------|
| CPU            | i5-8600K+ ou equivalente recomendado                     |
| RAM            | 8 GB mínimo; 16 GB recomendado para áudios longos        |
| GPU            | Não obrigatória (modelo `tiny` roda na CPU)              |
| Disco          | Áudio de entrada + arquivos intermediários podem ser MBs  |

## Instalação

### 1. Clonar o repositório

```bash
cd /c/Users/THIAGO  # ou onde preferir
git clone https://github.com/thimacedo/gravador_inteligente.git
cd gravador_inteligente
```

### 2. Criar e ativar o ambiente virtual

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Instalar dependências

```bash
pip install -e ".[dev]"
```

Isso instala:

- `openai-whisper` — transcrição (modelo `tiny` por padrão)
- `pydub` — manipulação de áudio
- `numpy` — processamento numérico
- `torch` — backend do Whisper
- `fastapi` + `uvicorn` — se quiser expor o pipeline como serviço (opcional, não usado no fluxo atual)
- `pytest`, `black`, `ruff` — desenvolvedor

> **Nota:** `whisper-timestamped` não é mais uma dependência ativa deste projeto. Se por algum motivo precisar de timestamps de palavra, pode instalar manualmente.

### 4. Configurar o ambiente

Copie `.env.example` para `.env` e preencha a variável obrigatória:

```bash
cp .env.example .env
```

Edite `.env` e defina:

```
DIVISOR_WORKSPACE=C:/caminho/para/workspace
```

Sendo que dentro do workspace deve existir:

```
<DIVISOR_WORKSPACE>/
└── assets/
    └── vinhetas/
        └── boletim/
            ├── VHT_ABERTURA_BOLETIM.mp3
            ├── VHT_PASSAGEM_BOLETIM.mp3
            └── VHT_ENCERRAMENTO_BOLETIM.mp3
```

Ou você pode sobrescrever os caminhos na chamada CLI com `--assets-dir`.

## Uso

### Pipeline completo (recomendado)

Executa todas as etapas em sequência:

```bash
.venv\Scripts\python.exe -m app.pipeline audio_gravacao.mp3 \
  -o output_boletins \
  --num-boletins 5 \
  --assets-dir "C:/caminho/para/workspace/assets/vinhetas/boletim" \
  --manter-intermediarios
```

Opções úteis:

| Flag | Descrição | Padrão |
|------|-----------|--------|
| `-o` / `--output` | Diretório de saída | `output_boletins` |
| `-n` / `--num-boletins` | Quantidade de boletins esperados | 5 |
| `--pular-segmentacao` | Não segmenta, assume áudio já cortado | False |
| `--pular-tratamento` | Pula limpeza de áudio | False |
| `--pular-edicao` | Pula remoção de repetições | False |
| `--pular-montagem` | Pula montagem com vinhetas | False |
| `--modelo` | Modelo Whisper (`tiny`, `base`, `small`) | `tiny` |
| `--lufs` | Alvo de loudness | -16.0 |
| `--noise-strength` | Intensidade de redução de ruído (0–1) | 0.5 |
| `--limiar` | Limiar de similaridade para repetições (0–1) | 0.5 |
| `--assets-dir` | Caminho dos assets de vinheta | `$DIVISOR_WORKSPACE/assets/vinhetas/boletim` |
| `--manter-intermediarios` | Não apaga arquivos intermediários | False |
| `-v` / `--verbose` | Log detalhado | False |

### Segmentação isolada

Se você já tem um áudio segmentado ou quer testar só a segmentação:

```bash
.venv\Scripts\python.exe -m app.segmentacao_boletins audio.mp3 \
  -o boletins_segmentados \
  -n 5 \
  -m tiny
```

### Edição isolada

Se você quer editar arquivos já cortado:

```bash
.venv\Scripts\python.exe -m app.edicao_boletins B1.mp3 \
  -o B1_editado.mp3 \
  -m tiny \
  -l 0.65
```

Ou editar um diretório inteiro:

```bash
.venv\Scripts\python.exe -m app.edicao_boletins --dir boletins_segmentados --output-dir editados
```

### Montagem isolada

Se você já tem áudio editado e só quer aplicar vinhetas:

```bash
.venv\Scripts\python.exe -m app.montagem_boletins B1_editado.mp3 \
  -o B1_final.mp3 \
  --assets-dir "C:/caminho/para/workspace/assets/vinhetas/boletim" \
  --lufs -16.0
```

## Estrutura de saída

Pelo padrão (`output_boletins/`), o pipeline gera:

```
output_boletins/
├── 01_segmentados/       # áudios individuais por boletim (se segmentação ativada)
├── 02_tratados/          # áudio após limpeza
├── 03_editados/          # áudio com repetições removidas
├── 04_montados/          # áudio final com vinhetas
├── pipeline_log.json     # log estruturado de todo o processo
└── B*_FINAL.mp3          # (se montagem ativada — nome final)
```

Com `--manter-intermediarios`, os arquivos intermediários são preservados. Sem ele, só o resultado final e o log ficam.

## Como o pipeline detecta repetições

O módulo de edição combina duas estratégias:

### 1. Palavras-gatilho

Se o locutor disser "repete", "novamente", "de novo", "volta", etc., o sistema retrocede um período padrão (8 segundos por padrão) e corta do início do erro até o comando.

### 2. Similaridade textual

Cada frase transcrita é comparada com as 4 frases anteriores (ou dentro de uma janela de 25 segundos). Se a similaridade (difflib.SequenceMatcher) ultrapassar o limiar (0.65 por padrão), a primeira versão é removida.

### Logs de edição

Cada execução de edição gera um log em `logs_edicao/log_edicao_YYYYMMDD_HHMMSS.json` com todas as operações aplicadas (tipo, timestamps, similaridade, texto excluded/excluded).

## Configuração externa

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `DIVISOR_WORKSPACE` | Sim (se não passar `--assets-dir`) | Caminho base para assets de vinheta |

Exemplo de `.env`:

```
DIVISOR_WORKSPACE=E:/02_Projetos_Trabalho/Projetos_Ativos/DIVISOR
```

## Testes

```bash
.venv\Scripts\python.exe -m pytest tests/ -v
```

Atualmente os testes cobrem o módulo de edição (`app/edicao_boletins.py`), incluindo:

- Detecção de gatilhos (repete, novamente, etc.)
- Detecção de repetições por similaridade
- Normalização de texto
- Configuração e operações de edição

## Desenvolvimento

```bash
# Formatar
.venv\Scripts\black.exe app/ tests/

# Lint
.venv\Scripts\ruff.exe check app/ tests/

# Testar
.venv\Scripts\python.exe -m pytest tests/ -v
```

## Estrutura do código

```
gravador_inteligente/
├── app/
│   ├── __init__.py              # pacote (público: pipeline, edicao, montagem, tratamento, segmentacao)
│   ├── pipeline.py              # orquestrador principal
│   ├── segmentacao_boletins.py  # segmentação via Whisper + marcadores B1-B5
│   ├── tratamento_audio.py      # limpeza: canal morto, ruído, respiração, silêncio, LUFS
│   ├── edicao_boletins.py       # detecção/remoção de repetições
│   └── montagem_boletins.py     # montagem com vinhetas + auditoria
├── tests/
│   └── test_edicao.py           # testes do módulo de edição
├── docs/
│   ├── arquitetura_projeto.md   # arquitetura e fluxo
│   ├── ROADMAP.md               # estado atual e próximos passos
│   ├── worklog.md               # registro de atividades
│   └── IDEA.md                  # índice de documentação
├── .env.example                 # variáveis de ambiente
├── pyproject.toml               # dependências e configuração
├── .gitignore                   # ignorados
└── README.md                    # este arquivo
```

## Limitações conhecidas

- **Whisper na CPU é lento** — áudios longos podem levar vários minutos para transcrever. Use `--modelo tiny` (padrão) ou transcreva uma vez e reutilize o JSON.
- **Canal morto** — se o áudio for stereo com som só no canal esquerdo, o tratamento converte automaticamente para mono. Verifique se o arquivo original realmente é stereo assimétrico antes de escalonar.
- **Booth de áudio** — oáúdo deve ter os marcadores `B1`, `B2` etc. na fala para a segmentação automática funcionar bem; caso contrário, você pode passar `--sem-transcricao` e usar divisão proporcional.
- **Pydub depende de ffmpeg** — se ffmpeg não estiver no PATH, tudo quebra. Teste com `ffmpeg -version` antes de começar.

## Licença

Não especificada (uso interno TJRN radio).

## Contato / Autor

Thiago Macedo — `thi.macedo@gmail.com`
