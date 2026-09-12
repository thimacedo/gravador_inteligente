# Arquitetura do Gravador Inteligente

## Visão geral

Gravador Inteligente é um pipeline Python de produção de boletins de rádio (TJRN). Ele transforma uma única gravação longa contendo múltiplos boletins em arquivos finais prontos para transmissão, aplicando segmentação, limpeza, edição e montagem com vinhetas.

O pipeline é sequencial por natureza, mas cada etapa é independente e pode ser usada isoladamente.

## Núcleo do sistema

### app.pipeline — Orquestrador

Responsável por conectar todas as etapas em sequência:

- Recebe áudio de entrada
- Segmenta (opcional)
- Para cada boletim: trata → edita → monta
- Executa auditoria pós-montagem (opcional)
- Gera log estruturado `pipeline_log.json`

**Ponto de entrada principal:** `PipelineBoletins.executar(audio_input, output_dir)`

### app.segmentacao_boletins — Segmentação

Detecta onde cada boletim começa usando Whisper:

1. Transcreve o áudio com Whisper (modelo `tiny` por padrão)
2. Busca os marcadores `B1`, `B2`, `B3`, `B4`, `B5` na transcrição
3. Constrói os limites de cada boletim (interpolação se faltar marcador)
4. Exporta cada segmento como arquivo MP3 individual

**Função principal:** `segmentar_audio(caminho_audio, config=SegmentacaoConfig())`

### app.tratamento_audio — Limpeza de áudio

Pipeline de 4 etapas opcionais (executadas em ordem):

1. **Correção de canal morto** — detecta se é stereo assimétrico e converte o canal ativo para mono
2. **Redução de ruído** — usa `noisereduce` (biblioteca Python) ou `ffmpeg afftdn` (fallback)
3. **Redução de respiração** — detecta gaps pequenos (50–300ms) entre fala e atenua em ~-6dB
4. **Remoção de silêncio longo** — opcional, remove silêncios >2s
5. **Normalização LUFS** — two-pass loudnorm para -16 LUFS (padrão podcast)

**Função principal:** `process(input_path, output_path, config=TratamentoConfig())`

### app.edicao_boletins — Edição de erros

Detecta e remove repetições de locução usando duas estratégias:

- **Palavras-gatilho**: `repete`, `novamente`, `de novo`, `volta`, `refaça`, `outra vez`
- **Similaridade textual**: compara frases adjacentes com `difflib.SequenceMatcher`, remove a versão antiga se similaridade ≥ limiar

Gera log JSON de todas as operações em `logs_edicao/`.

**Função principal:** `editar_boletim(caminho_audio, saida, config=EdicaoConfig())`

### app.montagem_boletins — Montagem final

Estrutura o boletim final:

```
VHT_ABERTURA + silêncio + CABEÇA + silêncio + VHT_PASSAGEM + silêncio + OFF + silêncio + VHT_ENCERRAMENTO
```

Onde:

- **CABEÇA** = manchete (primeiro bloco de fala até a primeira pausa longa)
- **OFF** = corpo da notícia (restante)

Detecta a pausa principal automaticamente nos primeiros 30% do áudio, com fallback para divisão em 1/3 se nada for encontrado. Aplica crossfade entre as partes.

**Função principal:** `montar_boletim(audio_editado, output_path, config=MontagemConfig())`

## Configuração

Todas as etapas usam dataclasses de configuração imutáveis:

| Módulo | Classe de config | Parâmetros principais |
|--------|-----------------|----------------------|
| Pipeline | `PipelineConfig` | `segmentar`, `num_boletins`, `tratar_audio`, `editar`, `montar`, `auditoria_auto`, `prefixo` |
| Segmentação | `SegmentacaoConfig` | `modelo`, `numero_boletins`, `idioma`, `output_dir`, `sem_transcricao` |
| Tratamento | `TratamentoConfig` | `target_lufs`, `noise_reduction_strength`, `reduce_noise`, `reduce_breath`, `remove_silence` |
| Edição | `EdicaoConfig` | `modelo_whisper`, `limiar_similaridade`, `palavras_gatilho`, `tempo_max_retrocesso_seg` |
| Montagem | `MontagemConfig` | `assets`, `crossfade_ms`, `pausa_threshold_ms`, `normalize_final`, `target_lufs` |

## Dependências externas

| Biblioteca | Finalidade | Observação |
|------------|-----------|------------|
| `openai-whisper` | Transcrição de áudio | Modelo `tiny` é o padrão (CPU-friendly) |
| `pydub` | Manipulação de áudio | Wrapper sobre ffmpeg |
| `numpy` | Processamento numérico | Usado no tratamento de áudio |
| `torch` | Backend do Whisper | Instalado automaticamente com whisper |
| `ffmpeg` | Processamento de áudio | **Obrigatório no sistema** — não é Python package |
| `noisereduce` | Redução de ruído (opcional) | Alternativa ao ffmpeg afftdn |
| `regex` | Detecção de marcadores B1-B5 | Mais expressivo que `re` para alguns casos |

## Fluxo de dados

```
Áudio bruto (MP3/WAV)
       │
       ▼
┌─────────────────────┐
│ 1. Segmentação      │
│ Whisper + regex B#  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 2. Tratamento       │
│ canal → ruído →     │
│ respiração → LUFS   │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 3. Edição           │
│ gatilhos +          │
│ similaridade        │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 4. Montagem         │
│ vinhetas + estrutura│
│ + normalização LUFS │
└─────────┬───────────┘
          │
          ▼
    Áudio final MP3
```

## Estrutura de diretórios

```
gravador_inteligente/
├── app/
│   ├── __init__.py              # pacote
│   ├── pipeline.py              # orquestrador
│   ├── segmentacao_boletins.py  # segmentação
│   ├── tratamento_audio.py      # limpeza
│   ├── edicao_boletins.py       # edição
│   └── montagem_boletins.py     # montagem
├── tests/
│   └── test_edicao.py           # testes de edição
├── docs/
│   ├── arquitetura_projeto.md   # este arquivo
│   ├── ROADMAP.md
│   ├── worklog.md
│   └── IDEA.md
├── output_boletins/             # saída padrão do pipeline
├── boletins_segmentados/        # saída da segmentação
├── logs_edicao/                 # logs de edição
└── temp_processing/             # temporários do tratamento
```

## Pontos de atenção

### Canal morto

Áudios estéreo onde só um canal tem sinal são convertidos para mono automaticamente. Isso é detectado e corrigido no início do tratamento.

### Whisper na CPU

O modelo `tiny` (72MB) é o padrão e funciona na CPU, mas transcrever áudios longos leva tempo. Para uso frequente, transcreva uma vez e reutilize o JSON com `--json-transcricao` na edição.

### Disco

O pipeline cria arquivos intermediários. Com `--manter-intermediarios`, cada boletim gera 3-4 arquivos extras. Limpe manualmente ou use sem a flag para auto-limpeza.

### Assets de vinheta

A montagem precisa de 3 arquivos de áudio:

- `VHT_ABERTURA_BOLETIM.mp3`
- `VHT_PASSAGEM_BOLETIM.mp3`
- `VHT_ENCERRAMENTO_BOLETIM.mp3`

Eles devem estar em `<DIVISOR_WORKSPACE>/assets/vinhetas/boletim/` ou você especifica outro caminho com `--assets-dir`.

## Testabilidade

Os módulos são testáveis isoladamente porque:

- Cada etapa é uma função pura que recebe caminho de entrada e saída
- A configuração é passada explicitamente (sem state global)
- O pipeline logra falhas por etapa sem parar o processamento dos demais boletins
- Os testes de edição mockam a transcrição (não chamam Whisper de verdade)

## Extensibilidade

Para adicionar uma nova etapa ao pipeline:

1. Crie `app/nova_etapa.py` com uma função main `processar(input_path, output_path, config)`
2. Importe no `pipeline.py`
3. Adicione ao `PipelineConfig` o campo `bool` para activar/desactivar
4. Adicione ao loop principal do pipeline (entre tratamento/edição ou após montagem)

## Histórico de versão

- **0.1.0** — Versão inicial com pipeline completo: segmentação, tratamento, edição, montagem, auditoria.
