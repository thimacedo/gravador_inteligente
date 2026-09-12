# IDEA — Índice de Documentação do Projeto

Este arquivo indexa todos os documentos do projeto para fácil consulta.

## README

| Arquivo | Descrição |
|--------|-----------|
| `README.md` | Documentação principal: o que é, como instalar, como usar, estrutura, limitações |

## Documentação técnica

| Arquivo | Descrição |
|--------|-----------|
| `docs/arquitetura_projeto.md` | Arquitetura do sistema: módulos, fluxo de dados, configuração, dependências |
| `docs/ROADMAP.md` | Status atual de cada componente e próximos passos priorizados |
| `docs/worklog.md` | Registro cronológico de atividades e decisões |

## Configuração

| Arquivo | Descrição |
|--------|-----------|
| `.env.example` | Variáveis de ambiente necessárias (copiar para `.env`) |
| `pyproject.toml` | Dependências, metadados do projeto, configurações de formatação |

## Código

| Arquivo | Descrição |
|--------|-----------|
| `app/pipeline.py` | Orquestrador do pipeline completo |
| `app/segmentacao_boletins.py` | Segmentação de áudio em boletins individuais |
| `app/tratamento_audio.py` | Limpeza: canal morto, ruído, respiração, silêncio, LUFS |
| `app/edicao_boletins.py` | Detecção e remoção de repetições de locução |
| `app/montagem_boletins.py` | Montagem final com vinhetas |
| `app/__init__.py` | Pacote principal |

## Testes

| Arquivo | Descrição |
|--------|-----------|
| `tests/test_edicao.py` | Testes do módulo de edição (22 testes) |

## Outros

| Arquivo | Descrição |
|--------|-----------|
| `.gitignore` | Arquivos e diretórios ignorados pelo git |
