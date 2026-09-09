"""
Módulo de Edição de Boletins - Detecção e remoção automática de erros de locução.

Duas estratégias:
1. Palavras-gatilho ("repete", "novamente", "de novo") com timestamps do Whisper
2. Detecção de repetições via similaridade de texto (janela deslizante com difflib)

Uso de modelo tiny (72MB) para evitar timeouts em CPU sem GPU.
"""

import argparse
import difflib
import json
import logging
import re
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydub import AudioSegment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuração
# =============================================================================

@dataclass
class EdicaoConfig:
    """Configurações para o processo de edição de boletins."""
    
    # Modelo Whisper - tiny é recomendado para CPU sem GPU
    modelo_whisper: str = "tiny"
    
    # Limiar de similaridade para detectar repetições (0.0-1.0)
    # 0.65 = 65% de similaridade já considera repetição
    limiar_similaridade: float = 0.65
    
    # Janela temporal máxima para comparação de repetições (segundos)
    # Só compara com frases das últimas N segundos
    tempo_max_retrocesso_seg: float = 25.0
    
    # Palavras-gatilho que indicam correção imediata
    palavras_gatilho: tuple = (
        "repete", "novamente", "de novo", "volta", "refaça", "outra vez",
    )
    
    # Tempo padrão de retrocesso para gatilhos (ms)
    tempo_retrocesso_padrao_ms: int = 8000
    
    # Pausa mínima (ms) que indica início de erro antes do gatilho
    pausa_minima_para_corte_ms: int = 1000
    
    # Idioma da transcrição
    idioma: str = "pt"
    
    # Diretório para logs de edição
    diretorio_logs: str = "logs_edicao"
    
    # Gerar log detalhado de exclusões
    gerar_log_exclusoes: bool = True
    
    # Tempo de silêncio considerado "pausa" em ms
    silence_thresh_db: int = -40
    
    # Tempo mínimo de silêncio para considerar pausa (ms)
    min_silence_len_ms: int = 1000


@dataclass
class OperacaoDeEdicao:
    """Registra uma operação de corte/exclusão para log."""
    
    tipo: str  # "gatilho" ou "repeticao"
    inicio_ms: int
    fim_ms: int
    texto_excluido: str = ""
    texto_mantem: str = ""
    similaridade: Optional[float] = None
    gatilho: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# =============================================================================
# Funções de comparação de texto
# =============================================================================

def similaridade_texto(a: str, b: str) -> float:
    """Retorna similaridade (0.0-1.0) entre duas strings usando SequenceMatcher."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def normalizar_texto(texto: str) -> str:
    """Normaliza texto para comparação: lowercase, remove pontuação, normaliza espaços."""
    texto = texto.lower().strip()
    texto = re.sub(r'[.,!?;:]', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto)
    return texto.strip()


def extrair_palavras_gatilho(texto: str, palavras_gatilho: tuple) -> Optional[str]:
    """Retorna a palavra-gatilho encontrada no texto, ou None."""
    texto_lower = texto.lower()
    for gatilho in palavras_gatilho:
        if gatilho in texto_lower:
            return gatilho
    return None


# =============================================================================
# Transcrição
# =============================================================================

def transcrever_audio(
    caminho_audio: str | Path,
    modelo: str = "tiny",
    idioma: str = "pt",
) -> list[dict]:
    """
    Transcreve áudio com Whisper, retornando segmentos com timestamps.
    
    Returns:
        Lista de dicts com: texto, inicio (ms), fim (ms), palavras (lista)
    """
    logger.info(f"Carregando modelo Whisper '{modelo}'...")
    import whisper
    model = whisper.load_model(modelo)
    
    logger.info(f"Transcrevendo {Path(caminho_audio).name}...")
    resultado = model.transcribe(str(caminho_audio), language=idioma)
    
    frases = []
    for segment in resultado["segments"]:
        texto = segment["text"].strip()
        if not texto:
            continue
        frases.append({
            "texto": texto,
            "inicio": int(segment["start"] * 1000),
            "fim": int(segment["end"] * 1000),
            "palavras": [],  # Whisper normal não tem timestamps de palavras
        })
    
    logger.info(f"Transcrição concluída: {len(frases)} segmentos")
    return frases


def carregar_transcricao_existente(caminho_json: str | Path) -> list[dict]:
    """Carrega transcrição de um arquivo JSON pré-existente (evita retestado)."""
    with open(caminho_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    frases = []
    for seg in data.get("segments", data.get("transcricao", [])):
        frases.append({
            "texto": seg.get("text", ""),
            "inicio": int(seg.get("start", 0) * 1000),
            "fim": int(seg.get("end", 0) * 1000),
            "palavras": [],
        })
    
    logger.info(f"Transcrição carregada: {len(frases)} segmentos de {caminho_json}")
    return frases


# =============================================================================
# Detecção de erros
# =============================================================================

def detectar_gatilhos(
    frases: list[dict],
    palavras_gatilho: tuple,
    tempo_retrocesso_padrao_ms: int = 8000,
    pausa_minima_para_corte_ms: int = 1000,
) -> list[tuple[int, int, str]]:
    """
    Detecta ocorrências de palavras-gatilho (repete, novamente, etc.)
    e retorna cortes (inicio_ms, fim_ms, gatilho).
    
    Para cada gatilho, estende o corte para trás para capturar o erro anterior.
    """
    cortes = []
    
    for i, frase in enumerate(frases):
        gatilho = extrair_palavras_gatilho(frase["texto"], palavras_gatilho)
        if not gatilho:
            continue
        
        # Ponto final do comando (onde o locutor disse "repete")
        tempo_fim_comando = frase["fim"]
        
        # Ponto inicial do erro: volta X ms antes do gatilho
        tempo_inicio_erro = max(0, frase["inicio"] - tempo_retrocesso_padrao_ms)
        
        # Se houve pausa grande antes do gatilho, usa o fim da frase anterior
        if i > 0:
            frase_anterior = frases[i - 1]
            pausa = frase["inicio"] - frase_anterior["fim"]
            if pausa > pausa_minima_para_corte_ms:
                tempo_inicio_erro = frase_anterior["fim"] + 150  # pequena margem
        
        cortes.append((tempo_inicio_erro, tempo_fim_comando, gatilho))
        
        logger.info(
            f"🚨 GATILHO: '{gatilho}' em {frase['inicio']/1000:.1f}s. "
            f"Cortando {tempo_inicio_erro/1000:.1f}s → {tempo_fim_comando/1000:.1f}s"
        )
    
    return cortes


def detectar_repeticoes(
    frases: list[dict],
    limiar_similaridade: float = 0.65,
    tempo_max_retrocesso_seg: float = 25.0,
    min_tamanho_texto: int = 15,
) -> list[tuple[int, int, int, float]]:
    """
    Detecta repetições textuais usando janela deslizante com difflib.SequenceMatcher.
    
    Compara cada frase com as 4 anteriores (ou dentro da janela temporal).
    Se similaridade >= limiar, considera repetição e marca o primeiro para exclusão.
    
    Returns:
        Lista de (inicio_corte_ms, fim_corte_ms, idx_frase_manter, similaridade)
    """
    cortes = []
    indices_ignorados: set[int] = set()
    
    for i, frase_atual in enumerate(frases):
        if i in indices_ignorados:
            continue
        
        texto_atual = normalizar_texto(frase_atual["texto"])
        
        # Ignora frases muito curtas (não vale a pena comparar)
        if len(texto_atual) < min_tamanho_texto:
            continue
        
        # Janela: olha para trás até 4 frases ou até o limite temporal
        inicio_janela = max(0, i - 4)
        
        for j in range(inicio_janela, i):
            if j in indices_ignorados:
                continue
            
            frase_passada = frases[j]
            
            # Verifica limite temporal
            intervalo_seg = (frase_atual["inicio"] - frase_passada["fim"]) / 1000
            if intervalo_seg > tempo_max_retrocesso_seg:
                continue
            
            texto_passado = normalizar_texto(frase_passada["texto"])
            
            if len(texto_passado) < min_tamanho_texto:
                continue
            
            sim = similaridade_texto(texto_atual, texto_passado)
            
            if sim >= limiar_similaridade:
                # Determina o início do corte (onde o erro começou)
                # Pega o fim da frase anterior ao erro, ou o início do erro
                inicio_corte = frase_passada["inicio"]
                if j > 0:
                    inicio_corte = max(inicio_corte, frases[j - 1]["fim"] + 100)
                
                # Fim do corte: início da versão correta
                fim_corte = frase_atual["inicio"]
                
                cortes.append((inicio_corte, fim_corte, i, sim))
                indices_ignorados.add(j)  # Evita reprocessar
                
                logger.info(
                    f"🔁 REPETIÇÃO ({sim*100:.1f}%): "
                    f"Apagando v1='{frase_passada['texto'][:60]}...' "
                    f"({frase_passada['inicio']/1000:.1f}s) | "
                    f"Mantendo v2='{frase_atual['texto'][:60]}...' "
                    f"({frase_atual['inicio']/1000:.1f}s)"
                )
                break  # Sai do loop interno, essa frase já foi resolvida
    
    return cortes


# =============================================================================
# Aplicação de cortes
# =============================================================================

def aplicar_cortes_audio(
    audio: AudioSegment,
    cortes: list[tuple[int, int]],
    saida: str | Path,
) -> AudioSegment:
    """
    Aplica cortes ao áudio e exporta o resultado.
    
    Cortes: lista de (inicio_ms, fim_ms) a serem removidos.
    """
    cortes_unicos = sorted(list(set(cortes)), key=lambda x: x[0])
    
    if not cortes_unicos:
        logger.warning("Nenhum corte para aplicar")
        # Exporta original se não houver cortes
        Path(saida).parent.mkdir(parents=True, exist_ok=True)
        audio.export(str(saida), format=Path(saida).suffix.lstrip(".").lower() or "mp3")
        return audio
    
    logger.info(f"Aplicando {len(cortes_unicos)} cortes ao áudio...")
    
    # Remove cortes sobrepostos ou contidos em outros
    cortes_filtrados = []
    for inicio, fim in cortes_unicos:
        # Ignora cortes inválidos
        if inicio >= fim:
            logger.warning(f"Corte inválido: {inicio}ms ≥ {fim}ms, ignorando")
            continue
        cortes_filtrados.append((inicio, fim))
    
    if not cortes_filtrados:
        logger.warning("Todos os cortes eram inválidos")
        audio.export(str(saida), format="mp3")
        return audio
    
    cortes_filtrados = sorted(cortes_filtrados, key=lambda x: x[0])
    
    audio_final = AudioSegment.empty()
    ponteiro = 0
    
    for inicio, fim in cortes_filtrados:
        if inicio > ponteiro:
            audio_final += audio[ponteiro:inicio]
        ponteiro = max(ponteiro, fim)
    
    if ponteiro < len(audio):
        audio_final += audio[ponteiro:]
    
    Path(saida).parent.mkdir(parents=True, exist_ok=True)
    
    formato = Path(saida).suffix.lstrip(".").lower() or "mp3"
    audio_final.export(str(saida), format=formato)
    
    logger.info(f"✨ Áudio editado exportado: '{Path(saida).name}' ({len(audio_final)/1000:.1f}s)")
    return audio_final


# =============================================================================
# Logs
# =============================================================================

def gerar_log_edicao(
    operacoes: list[OperacaoDeEdicao],
    caminho_audio_original: str | Path,
    caminho_audio_editado: str | Path,
    log_path: Optional[str | Path] = None,
) -> str:
    """Gera arquivo JSON com log detalhado da edição."""
    if log_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = Path("logs_edicao") / f"log_edicao_{timestamp}.json"
    
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    
    total_excluido = sum(op.fim_ms - op.inicio_ms for op in operacoes if op.fim_ms > op.inicio_ms)
    
    log_data = {
        "metadata": {
            "data_geracao": datetime.now().isoformat(),
            "audio_original": str(caminho_audio_original),
            "audio_editado": str(caminho_audio_editado),
            "total_excluido_ms": total_excluido,
            "total_operacoes": len(operacoes),
            "total_excluido_s": round(total_excluido / 1000, 2),
        },
        "operacoes": [
            {
                "tipo": op.tipo,
                "inicio_ms": op.inicio_ms,
                "fim_ms": op.fim_ms,
                "duracao_ms": op.fim_ms - op.inicio_ms if op.fim_ms > op.inicio_ms else 0,
                "texto_excluido": op.texto_excluido[:300],
                "texto_mantem": op.texto_mantem[:300],
                "similaridade_percent": round(op.similaridade * 100, 1) if op.similaridade else None,
                "gatilho": op.gatilho,
            }
            for op in operacoes
        ],
    }
    
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)
    
    logger.info(f"📋 Log de edição gerado: '{Path(log_path).name}'")
    return str(log_path)


# =============================================================================
# Função principal de edição
# =============================================================================

def editar_boletim(
    caminho_audio: str | Path,
    saida: Optional[str | Path] = None,
    config: Optional[EdicaoConfig] = None,
    transcricao_previa: Optional[list[dict]] = None,
    transcricao_json: Optional[str | Path] = None,
) -> dict:
    """
    Função principal que orquestra a edição de um boletim de áudio.
    
    Args:
        caminho_audio: Caminho do arquivo de áudio
        saida: Caminho do arquivo de saída (opcional)
        config: Configurações de edição
        transcricao_previa: Transcrição já existente (evita retestado)
        transcricao_json: Caminho JSON com transcrição prévia
    
    Returns:
        Dict com status, caminhos, estatísticas e operações
    """
    caminho_audio = Path(caminho_audio)
    
    if not caminho_audio.exists():
        raise FileNotFoundError(f"Áudio não encontrado: {caminho_audio}")
    
    cfg = config or EdicaoConfig()
    
    if saida is None:
        saida = caminho_audio.stem + "_editado.mp3"
    saida = Path(saida)
    
    logger.info(f"=== Iniciando edição: {caminho_audio.name} ===")
    
    # 1. Transcrição (ou carrega prévia)
    if transcricao_previa is not None:
        frases = transcricao_previa
        logger.info(f"Usando transcrição prévia: {len(frases)} segmentos")
    elif transcricao_json is not None:
        frases = carregar_transcricao_existente(transcricao_json)
    else:
        frases = transcrever_audio(
            caminho_audio,
            modelo=cfg.modelo_whisper,
            idioma=cfg.idioma,
        )
    
    if not frases:
        logger.warning("Nenhuma frase transcrita. Retornando áudio original.")
        Path(saida).parent.mkdir(parents=True, exist_ok=True)
        audio = AudioSegment.from_file(str(caminho_audio))
        audio.export(str(saida), format="mp3")
        return {
            "status": "sucesso",
            "audio_editado": str(saida),
            "cortadas": 0,
            "frases_analisadas": 0,
            "msg": "Nenhuma frase transcrita",
        }
    
    logger.info(f"Analisando {len(frases)} segmentos de fala...")
    
    # 2. Detecção de gatilhos
    cortes_gatilho = detectar_gatilhos(
        frases,
        cfg.palavras_gatilho,
        cfg.tempo_retrocesso_padrao_ms,
        cfg.pausa_minima_para_corte_ms,
    )
    
    # 3. Detecção de repetições
    cortes_repeticao = detectar_repeticoes(
        frases,
        cfg.limiar_similaridade,
        cfg.tempo_max_retrocesso_seg,
    )
    
    # 4. Combina cortes e prepara operações de log
    todos_cortes: list[tuple[int, int]] = []
    operacoes: list[OperacaoDeEdicao] = []
    
    for inicio, fim, gatilho in cortes_gatilho:
        todos_cortes.append((inicio, fim))
        operacoes.append(OperacaoDeEdicao(
            tipo="gatilho",
            inicio_ms=inicio,
            fim_ms=fim,
            texto_excluido="",
            texto_mantem="",
            gatilho=gatilho,
        ))
    
    for inicio, fim, idx_manter, sim in cortes_repeticao:
        todos_cortes.append((inicio, fim))
        texto_excluido = ""
        if idx_manter < len(frases):
            texto_excluido = frases[idx_manter]["texto"]
        operacoes.append(OperacaoDeEdicao(
            tipo="repeticao",
            inicio_ms=inicio,
            fim_ms=fim,
            texto_excluido=texto_excluido,
            texto_mantem="",
            similaridade=sim,
        ))
    
    # 5. Carrega áudio e aplica cortes
    audio = AudioSegment.from_file(str(caminho_audio))
    audio_final = aplicar_cortes_audio(audio, todos_cortes, saida)
    
    # 6. Gera log
    log_path = None
    if cfg.gerar_log_exclusoes and operacoes:
        log_path = gerar_log_edicao(
            operacoes,
            caminho_audio,
            saida,
        )
    
    duracao_original = len(audio) / 1000
    duracao_final = len(audio_final) / 1000
    tempo_economizado = duracao_original - duracao_final
    
    logger.info(
        f"=== Concluído: {duracao_original:.1f}s → {duracao_final:.1f}s "
        f"(economizado {tempo_economizado:.1f}s, {len(todos_cortes)} cortes) ==="
    )
    
    return {
        "status": "sucesso",
        "audio_original": str(caminho_audio),
        "audio_editado": str(saida),
        "log_edicao": log_path,
        "cortadas": len(todos_cortes),
        "frases_analisadas": len(frases),
        "duracao_original_s": round(duracao_original, 2),
        "duracao_final_s": round(duracao_final, 2),
        "tempo_economizado_s": round(tempo_economizado, 2),
        "operacoes": [
            {
                "tipo": op.tipo,
                "inicio_s": round(op.inicio_ms / 1000, 2),
                "fim_s": round(op.fim_ms / 1000, 2),
                "duracao_s": round((op.fim_ms - op.inicio_ms) / 1000, 2),
                "texto_excluido": op.texto_excluido[:200],
                "similaridade_percent": round(op.similaridade * 100, 1) if op.similaridade else None,
                "gatilho": op.gatilho,
            }
            for op in operacoes
        ],
    }


def editar_boletins_diretorio(
    diretorio_entrada: str | Path,
    diretorio_saida: Optional[str | Path] = None,
    modelo: str = "tiny",
    limiar_similaridade: float = 0.65,
    tempo_janela_seg: float = 25.0,
    palavras_gatilho: Optional[tuple] = None,
) -> list[dict]:
    """
    Edita todos os arquivos de áudio em um diretório.
    
    Args:
        diretorio_entrada: Diretório com arquivos a editar
        diretorio_saida: Diretório de saída (opcional)
        modelo: Modelo Whisper
        limiar_similaridade: Threshold para detecção de repetições
        tempo_janela_seg: Janela temporal para comparação
        palavras_gatilho: Lista customizada de gatilhos
    
    Returns:
        Lista de resultados por arquivo
    """
    entrada = Path(diretorio_entrada)
    saida = Path(diretorio_saida) if diretorio_saida else entrada / "editados"
    
    if not entrada.exists():
        raise FileNotFoundError(f"Diretório não encontrado: {entrada}")
    
    saida.mkdir(parents=True, exist_ok=True)
    
    # Encontra arquivos de áudio
    extensoes = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
    arquivos_audio = [f for f in entrada.iterdir() 
                      if f.is_file() and f.suffix.lower() in extensoes]
    
    if not arquivos_audio:
        logger.warning(f"Nenhum arquivo de áudio encontrado em {entrada}")
        return []
    
    logger.info(f"Encontrados {len(arquivos_audio)} arquivos para editar")
    
    config = EdicaoConfig(
        modelo_whisper=modelo,
        limiar_similaridade=limiar_similaridade,
        tempo_max_retrocesso_seg=tempo_janela_seg,
        palavras_gatilho=palavras_gatilho or cfg.palavras_gatilho,
        gerar_log_exclusoes=True,
        diretorio_logs=str(saida / "logs"),
    )
    
    resultados = []
    for arquivo in arquivos_audio:
        logger.info(f"\n{'='*60}")
        logger.info(f"Editando: {arquivo.name}")
        logger.info(f"{'='*60}")
        
        nome_saida = arquivo.stem + "_editado" + arquivo.suffix
        caminho_saida = saida / nome_saida
        
        try:
            resultado = editar_boletim(arquivo, caminho_saida, config)
            resultados.append(resultado)
        except Exception as e:
            logger.error(f"Erro ao editar {arquivo.name}: {e}")
            resultados.append({
                "status": "erro",
                "arquivo": str(arquivo),
                "erro": str(e),
            })
    
    # Resumo
    total_original = sum(r.get("duracao_original_s", 0) for r in resultados if r.get("status") == "sucesso")
    total_final = sum(r.get("duracao_final_s", 0) for r in resultados if r.get("status") == "sucesso")
    total_cortes = sum(r.get("cortadas", 0) for r in resultados if r.get("status") == "sucesso")
    
    logger.info(f"\n{'='*60}")
    logger.info(f"RESUMO: {len(resultados)} arquivos processados")
    logger.info(f"  Sucesso: {sum(1 for r in resultados if r.get('status') == 'sucesso')}")
    logger.info(f"  Erros: {sum(1 for r in resultados if r.get('status') == 'erro')}")
    logger.info(f"  Duração original: {total_original:.1f}s")
    logger.info(f"  Duração final: {total_final:.1f}s")
    logger.info(f"  Economizado: {total_original - total_final:.1f}s")
    logger.info(f"  Cortes aplicados: {total_cortes}")
    logger.info(f"{'='*60}")
    
    return resultados


# =============================================================================
# CLI
# =============================================================================

def main_cli():
    parser = argparse.ArgumentParser(
        description="Edita boletins de áudio removendo erros e repetições de locução"
    )
    parser.add_argument("audio", nargs="?", help="Caminho do arquivo de áudio original")
    parser.add_argument("-o", "--output", help="Caminho do arquivo de saída")
    parser.add_argument("-m", "--modelo", default="tiny", 
                       choices=["tiny", "base", "small", "medium", "large"],
                       help="Modelo Whisper (padrão: tiny)")
    parser.add_argument("-l", "--limiar", type=float, default=0.65,
                       help="Limiar de similaridade para repetições (0.0-1.0)")
    parser.add_argument("-w", "--janela", type=float, default=25.0,
                       help="Janela de retrocesso em segundos")
    parser.add_argument("--sem-log", action="store_true",
                       help="Não gera log de exclusões")
    parser.add_argument("--json-transcricao", help="Usa transcrição de arquivo JSON existente")
    parser.add_argument("--dir", help="Diretório com múltiplos áudios para editar")
    parser.add_argument("--output-dir", help="Diretório de saída para edição em massa")
    parser.add_argument("-v", "--verbose", action="store_true",
                       help="Modo verboso")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.dir:
        # Modo edição em massa
        resultados = editar_boletins_diretorio(
            args.dir,
            args.output_dir,
            modelo=args.modelo,
            limiar_similaridade=args.limiar,
            tempo_janela_seg=args.janela,
        )
        
        print("\n" + "=" * 60)
        print("RESULTADOS DA EDIÇÃO EM MASSA")
        print("=" * 60)
        
        for r in resultados:
            if r["status"] == "sucesso":
                print(f"✓ {Path(r['audio_original']).name}: "
                      f"{r['duracao_original_s']}s → {r['duracao_final_s']}s "
                      f"({r['cortadas']} cortes, -{r['tempo_economizado_s']}s)")
            else:
                print(f"✗ {Path(r.get('arquivo', r['audio_original'])).name}: "
                      f"ERRO - {r.get('erro', 'Erro desconhecido')}")
        
        total_economizado = sum(r.get("tempo_economizado_s", 0) for r in resultados if r.get("status") == "sucesso")
        print(f"\nTotal economizado: {total_economizado:.1f}s")
        
    elif args.audio:
        # Modo edição individual
        config = EdicaoConfig(
            modelo_whisper=args.modelo,
            limiar_similaridade=args.limiar,
            tempo_max_retrocesso_seg=args.janela,
            gerar_log_exclusoes=not args.sem_log,
        )
        
        transcricao = None
        if args.json_transcricao:
            transcricao = carregar_transcricao_existente(args.json_transcricao)
        
        resultado = editar_boletim(args.audio, args.output, config, transcricao_previa=transcricao)
        
        print("\n" + "=" * 60)
        print("RESULTADO DA EDIÇÃO")
        print("=" * 60)
        print(f"Status: {resultado['status']}")
        
        if resultado['status'] == 'sucesso':
            print(f"Áudio original: {resultado['audio_original']}")
            print(f"Áudio editado:  {resultado['audio_editado']}")
            print(f"Frases analisadas: {resultado['frases_analisadas']}")
            print(f"Cortes aplicados: {resultado['cortadas']}")
            print(f"Duração: {resultado['duracao_original_s']}s → {resultado['duracao_final_s']}s")
            print(f"Economizado: {resultado['tempo_economizado_s']}s")
            
            if resultado.get("operacoes"):
                print("\nOperações realizadas:")
                for op in resultado["operacoes"]:
                    tipo_str = f"[{op['tipo']}]"
                    if op.get("gatilho"):
                        tipo_str += f" '{op['gatilho']}'"
                    elif op.get("similaridade_percent") is not None:
                        tipo_str += f" {op['similaridade_percent']:.1f}%"
                    print(f"  {tipo_str}: {op['inicio_s']}s → {op['fim_s']}s "
                          f"({op['duracao_s']}s)")
            
            if resultado.get("log_edicao"):
                print(f"\nLog: {resultado['log_edicao']}")
        else:
            print(f"Erro: {resultado.get('erro', 'Erro desconhecido')}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main_cli()
