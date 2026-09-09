"""
Testes para o módulo de edição de boletins.
"""

from app.edicao_boletins import (
    EdicaoConfig,
    OperacaoDeEdicao,
    detectar_gatilhos,
    detectar_repeticoes,
    normalizar_texto,
    similaridade_texto,
)


def test_textos_identicos():
    assert similaridade_texto("Olá mundo", "Olá mundo") == 1.0

def test_textos_totalmente_diferentes():
    assert similaridade_texto("casa", "elefante") < 0.3

def test_textos_semelhantes():
    sim = similaridade_texto("O rato roeu a roupa", "O rato roeu a roupa do rei")
    assert sim > 0.8

def test_case_insensitive():
    assert similaridade_texto("Olá Mundo", "olá mundo") == 1.0

def test_textos_vazios():
    assert similaridade_texto("", "") == 1.0
    assert similaridade_texto("", "algo") < 0.5

def test_remove_pontuacao():
    assert normalizar_texto("Olá, mundo!") == "olá mundo"

def test_remove_whitespace_excessivo():
    assert normalizar_texto("  Olá   mundo  ") == "olá mundo"

def test_lowercase():
    assert normalizar_texto("OLÁ MUNDO") == "olá mundo"

def test_texto_vazio():
    assert normalizar_texto("") == ""

def test_apenas_pontuacao():
    assert normalizar_texto("!!!") == ""

def test_com_tags_html():
    resultado = normalizar_texto("Olá <b>mundo</b>")
    assert "olá" in resultado
    assert "mundo" in resultado

def test_detecta_repete():
    frases = [
        {"texto": "O boletim de hoje", "inicio": 0, "fim": 3000, "palavras": []},
        {"texto": "repete O boletim de hoje", "inicio": 4000, "fim": 7000, "palavras": []},
    ]
    
    cortes = detectar_gatilhos(
        frases,
        palavras_gatilho=("repete", "novamente"),
        tempo_retrocesso_padrao_ms=8000,
        pausa_minima_para_corte_ms=1000,
    )
    
    assert len(cortes) == 1
    inicio, fim, gatilho = cortes[0]
    assert gatilho == "repete"
    assert inicio < 4000
    assert fim == 7000

def test_detecta_novamente():
    frases = [
        {"texto": "Primeira frase erro", "inicio": 0, "fim": 3000, "palavras": []},
        {"texto": "Agora novamente a frase correta", "inicio": 5000, "fim": 8000, "palavras": []},
    ]
    
    cortes = detectar_gatilhos(
        frases,
        palavras_gatilho=("repete", "novamente"),
        tempo_retrocesso_padrao_ms=8000,
        pausa_minima_para_corte_ms=1000,
    )
    
    assert len(cortes) == 1
    assert cortes[0][2] == "novamente"

def test_sem_gatilhos():
    frases = [
        {"texto": "Frase um", "inicio": 0, "fim": 3000, "palavras": []},
        {"texto": "Frase dois", "inicio": 5000, "fim": 8000, "palavras": []},
    ]
    
    cortes = detectar_gatilhos(
        frases,
        palavras_gatilho=("repete", "novamente"),
        tempo_retrocesso_padrao_ms=8000,
        pausa_minima_para_corte_ms=1000,
    )
    
    assert len(cortes) == 0

def test_pausa_limpa():
    frases = [
        {"texto": "Frase correta antes", "inicio": 0, "fim": 3000, "palavras": []},
        {"texto": "repete Frase correta antes", "inicio": 5000, "fim": 8000, "palavras": []},
    ]
    
    cortes = detectar_gatilhos(
        frases,
        palavras_gatilho=("repete",),
        tempo_retrocesso_padrao_ms=8000,
        pausa_minima_para_corte_ms=1000,
    )
    
    assert len(cortes) == 1
    inicio, fim, _ = cortes[0]
    assert inicio == 3150
    assert fim == 8000

def test_gatilho_no_inicio():
    frases = [
        {"texto": "repete Isso é um teste", "inicio": 0, "fim": 3000, "palavras": []},
    ]
    
    cortes = detectar_gatilhos(
        frases,
        palavras_gatilho=("repete",),
        tempo_retrocesso_padrao_ms=8000,
        pausa_minima_para_corte_ms=1000,
    )
    
    assert len(cortes) == 1
    inicio, fim, _ = cortes[0]
    assert inicio >= 0
    assert fim == 3000

def test_detecta_repeticao_perfeita():
    frases = [
        {"texto": "O boletim de hoje tem muitas notícias", "inicio": 0, "fim": 4000, "palavras": []},
        {"texto": "Algum texto intermediário", "inicio": 5000, "fim": 7000, "palavras": []},
        {"texto": "O boletim de hoje tem muitas notícias", "inicio": 8000, "fim": 12000, "palavras": []},
    ]
    
    cortes = detectar_repeticoes(
        frases,
        limiar_similaridade=0.6,
        tempo_max_retrocesso_seg=25,
    )
    
    assert len(cortes) >= 1
    inicio, fim, idx_manter, sim = cortes[0]
    assert sim >= 0.6
    assert idx_manter == 2
    assert inicio == 0
    assert fim == 8000

def test_nao_detecta_textos_diferentes():
    frases = [
        {"texto": "Primeira frase completamente diferente", "inicio": 0, "fim": 3000, "palavras": []},
        {"texto": "Segunda frase também muito diferente", "inicio": 4000, "fim": 7000, "palavras": []},
    ]
    
    cortes = detectar_repeticoes(
        frases,
        limiar_similaridade=0.8,
        tempo_max_retrocesso_seg=25,
    )
    
    assert len(cortes) == 0

def test_limita_por_janela_temporal():
    """Não deve detectar repetições fora da janela temporal."""
    frases = [
        {"texto": "Frase inicial unica", "inicio": 0, "fim": 3000, "palavras": []},
    ]
    for t in range(4000, 27000, 2000):
        frases.append({
            "texto": f"Conteudo totalmente diferente numero {t} com texto variado",
            "inicio": t, "fim": t + 1000, "palavras": []
        })
    
    cortes = detectar_repeticoes(
        frases,
        limiar_similaridade=0.5,
        tempo_max_retrocesso_seg=2,
    )
    
    assert len(cortes) == 0

def test_mais_de_uma_repeticao():
    """Testa detecção de múltiplas repetições."""
    frases = [
        {"texto": "O boletim de hoje", "inicio": 0, "fim": 2000, "palavras": []},
        {"texto": "A economia cresceu", "inicio": 3000, "fim": 5000, "palavras": []},
        {"texto": "O boletim de hoje", "inicio": 6000, "fim": 8000, "palavras": []},
        {"texto": "Novo tema abordado", "inicio": 9000, "fim": 11000, "palavras": []},
        {"texto": "A economia cresceu", "inicio": 12000, "fim": 14000, "palavras": []},
    ]
    
    cortes = detectar_repeticoes(
        frases,
        limiar_similaridade=0.6,
        tempo_max_retrocesso_seg=25,
    )
    
    assert len(cortes) >= 2, f"Esperado >= 2 cortes, got {len(cortes)}"

def test_config_default():
    cfg = EdicaoConfig()
    
    assert cfg.limiar_similaridade == 0.65
    assert cfg.tempo_max_retrocesso_seg == 25.0
    assert len(cfg.palavras_gatilho) > 0
    assert "repete" in cfg.palavras_gatilho

def test_config_customizada():
    cfg = EdicaoConfig(
        limiar_similaridade=0.8,
        tempo_max_retrocesso_seg=15.0,
        palavras_gatilho=("repete", "outra vez"),
        gerar_log_exclusoes=False,
    )
    
    assert cfg.limiar_similaridade == 0.8
    assert cfg.tempo_max_retrocesso_seg == 15.0
    assert cfg.palavras_gatilho == ("repete", "outra vez")
    assert cfg.gerar_log_exclusoes is False

def test_criacao_default():
    op = OperacaoDeEdicao(
        tipo="gatilho",
        inicio_ms=1000,
        fim_ms=5000,
        texto_excluido="texto velho",
        texto_mantem="texto novo",
        gatilho="repete",
    )
    
    assert op.tipo == "gatilho"
    assert op.inicio_ms == 1000
    assert op.fim_ms == 5000
    assert op.gatilho == "repete"
    assert op.similaridade is None

def test_com_similaridade():
    op = OperacaoDeEdicao(
        tipo="repeticao",
        inicio_ms=2000,
        fim_ms=6000,
        texto_excluido="frase antiga",
        texto_mantem="frase nova",
        similaridade=0.85,
    )
    
    assert op.similaridade == 0.85
    assert op.gatilho is None
