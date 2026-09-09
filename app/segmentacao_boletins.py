#!/usr/bin/env python3
"""
Módulo de Segmentação de Boletins - Divide gravações contendo múltiplos boletins em arquivos individuais.

Detecta marcadores de boletim (B1, B2, B3, B4, B5) na transcrição do Whisper
e gera arquivos de áudio separados para cada boletim, junto com logs em JSON.
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import regex  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# Configurações padrão

DEFAULT_AUDIO_PATH = "C:/Users/THIAGO/AppData/Local/hermes/attachments/06 JUL B1-B5.mp3"
DEFAULT_OUTPUT_DIR = "boletins_segmentados"
DEFAULT_MODELO = "tiny"  # tiny, base, small, medium, large
DEFAULT_NUM_BOLETINS = 5
DEFAULT_IDIOMA = "pt"



def carregar_modelo_whisper(modelo_nome: str):
    """Carrega o modelo Whisper especificado."""
    import whisper
    logger.info(f"Carregando modelo Whisper '{modelo_nome}'...")
    print(f"Carregando modelo Whisper '{modelo_nome}'...")
    model = whisper.load_model(modelo_nome)
    logger.info("Modelo carregado com sucesso")
    return model


def transcrever_audio(modelo, caminho_audio: str, idioma: str = DEFAULT_IDIOMA):
    """Transcreve o áudio e retorna os segmentos."""
    logger.info("Iniciando transcrição...")
    print("Transcrevendo áudio... (pode levar alguns minutos)")
    
    result = modelo.transcribe(
        caminho_audio,
        language=idioma,
        fp16=False,
        verbose=False
    )
    
    transcricao = result["segments"]
    duracao_total = result["segments"][-1]["end"] if result["segments"] else 0
    
    logger.info(f"Transcrição concluída: {len(transcricao)} segmentos, {duracao_total:.1f}s")
    print(f"Transcrição concluída: {len(transcricao)} segmentos, {duracao_total:.1f}s")
    
    return transcricao, duracao_total


def detectar_marcadores_boletim(transcricao, padrao: str = r"\bB(\d{1,2})\b"):
    """Detecta marcadores B1, B2, B3... na transcrição."""
    regex_marcador = regex.compile(padrao, regex.IGNORECASE)
    
    marcadores_detectados = {}
    
    for seg in transcricao:
        texto = seg["text"].strip()
        match = regex_marcador.search(texto)
        
        if match:
            numero = int(match.group(1))
            if numero not in marcadores_detectados:
                marcadores_detectados[numero] = {
                    "inicio": seg["start"],
                    "fim": seg["end"],
                    "texto": texto
                }
                logger.info(f"Marcador B{numero} encontrado: {seg['start']:.1f}s")
                print(f"  ✓ B{numero}: {seg['start']:.1f}s - '{texto}'")
    
    return marcadores_detectados


def construir_limites_boletins(
    marcadores_detectados: Dict[int, dict],
    duracao_total: float,
    numero_total_boletins: int = DEFAULT_NUM_BOLETINS
) -> List[dict]:
    """
    Constrói a lista completa de limites para todos os boletins.
    
    Estratégia:
    1. Usa marcadores detectados quando disponíveis
    2. Para boletins não detectados, distribui proporcionalmente entre 
       os marcadores conhecidos ou no início/fim
    3. Garante que os limites estejam em ordem cronológica crescente
    4. Se nenhum marcador é detectado além de B1, divide igualmente
    """
    # B1 sempre começa no início
    marcadores: List[dict] = [{
        "numero": 1,
        "inicio": 0.0,
        "fim": None,
        "texto_marcador": "INICIO DA GRAVAÇÃO",
        "detectado": True
    }]
    
    # Registrar quais números foram detectados
    detectados = set(marcadores_detectados.keys())
    
    # Primeiro, adicionar todos os marcadores detectados
    for num in range(2, numero_total_boletins + 1):
        if num in marcadores_detectados:
            marcadores.append({
                "numero": num,
                "inicio": marcadores_detectados[num]["inicio"],
                "fim": None,
                "texto_marcador": marcadores_detectados[num]["texto"],
                "detectado": True
            })
    
    # Se nenhum marcador extra foi detectado, usar divisão igualitária
    if len(marcadores) < 3:  # Só temos B1 ou B1 + 1 detectado
        logger.warning(f"Apenas {len(marcadores)} boletins com marcadores detectados. Usando divisão igualitária.")
        duracao_por_boletin = duracao_total / numero_total_boletins
        
        for num in range(2, numero_total_boletins + 1):
            # Verificar se já existe (detectado)
            if any(m["numero"] == num for m in marcadores):
                continue
            marcadores.append({
                "numero": num,
                "inicio": num * duracao_por_boletin,
                "fim": None,
                "texto_marcador": "ESTIMADO (divisão igual)",
                "detectado": False
            })
    else:
        # Temos marcadores detectados, usar interpolação entre eles
        # Primeiro, ordenar os marcadores conhecidos por tempo
        conhecidos = sorted(
            [m for m in marcadores if m["detectado"]],
            key=lambda x: x["inicio"]
        )
        
        # Para cada número faltante, encontrar posição interpolada
        for num in range(2, numero_total_boletins + 1):
            if any(m["numero"] == num for m in marcadores):
                continue  # Já adicionado (detectado)
            
            # Encontrar os marcadores conhecidos imediatamente antes e depois
            anterior = None
            posterior = None
            
            for m in conhecidos:
                if m["numero"] < num:
                    anterior = m
                elif m["numero"] > num and posterior is None:
                    posterior = m
                    break
            
            if anterior is None and posterior is None:
                # Sem referência, usar posição relativa
                posicao = num / (numero_total_boletins + 1) * duracao_total
            elif anterior is None:
                # Antes do primeiro conhecido
                posicao = posterior["inicio"] / (posterior["numero"] + 1) * num
            elif posterior is None:
                # Depois do último conhecido
                ultimo = conhecidos[-1]
                intervalo = (duracao_total - ultimo["inicio"]) / (numero_total_boletins - ultimo["numero"] + 1)
                posicao = ultimo["inicio"] + intervalo * (num - ultimo["numero"])
            else:
                # Interpolar entre anterior e posterior
                distancia = posterior["inicio"] - anterior["inicio"]
                passo = distancia / (posterior["numero"] - anterior["numero"])
                posicao = anterior["inicio"] + passo * (num - anterior["numero"])
            
            marcadores.append({
                "numero": num,
                "inicio": posicao,
                "fim": None,
                "texto_marcador": "ESTIMADO (interpolado)",
                "detectado": False
            })
    
    # Ordenar por número para garantir a sequência correta
    marcadores.sort(key=lambda x: x["numero"])
    
    # Calcular finais
    for i, marcador in enumerate(marcadores):
        if i < len(marcadores) - 1:
            marcador["fim"] = marcadores[i + 1]["inicio"]
        else:
            marcador["fim"] = duracao_total
        marcador["duracao"] = marcador["fim"] - marcador["inicio"]
    
    # Validar: garantir que inicios são crescentes
    for i in range(1, len(marcadores)):
        if marcadores[i]["inicio"] < marcadores[i-1]["inicio"]:
            logger.warning(
                f"Inconsistência detectada: B{marcadores[i]['numero']} ({marcadores[i]['inicio']:.1f}s) "
                f"antes de B{marcadores[i-1]['numero']} ({marcadores[i-1]['inicio']:.1f}s). "
                f"Ajustando para B{marcadores[i-1]['numero']}.fim = {marcadores[i-1]['fim']:.1f}s"
            )
            marcadores[i]["inicio"] = marcadores[i-1]["fim"]
            marcadores[i]["duracao"] = marcadores[i]["fim"] - marcadores[i]["inicio"]
    
    # Log dos limites calculados
    logger.info("Limites dos boletins calculados:")
    for m in marcadores:
        deteccao = "✓" if m["detectado"] else "○"
        logger.info(
            f"  B{m['numero']}: {m['inicio']:.1f}s → {m['fim']:.1f}s "
            f"({m['duracao']:.1f}s, {m['duracao']/60:.1f}min) [{deteccao}]"
        )
    
    return marcadores


def exportar_boletins(audio, marcadores: List[dict], saida_dir: str) -> List[str]:
    """
    Exporta cada boletim como arquivo MP3 individual.
    """
    from pydub import AudioSegment
    
    os.makedirs(saida_dir, exist_ok=True)
    logger.info(f"Diretório de saída: {saida_dir}")
    
    arquivos_exportados = []
    
    for marcador in marcadores:
        numero = marcador["numero"]
        inicio_ms = int(marcador["inicio"] * 1000)
        fim_ms = int(marcador["fim"] * 1000)
        
        # Validar limites
        if inicio_ms < 0:
            inicio_ms = 0
            logger.warning(f"B{numero}: inicio ajustado para 0s")
        if fim_ms > len(audio):
            fim_ms = len(audio)
            logger.warning(f"B{numero}: fim ajustado para {len(audio)/1000:.1f}s")
        if inicio_ms >= fim_ms:
            logger.error(f"B{numero}: intervalo inválido ({inicio_ms}ms ≥ {fim_ms}ms). Pulando.")
            continue
        
        logger.info(f"Exportando B{numero}: {marcador['inicio']:.1f}s → {marcador['fim']:.1f}s")
        print(f"\nBoletim B{numero}:")
        print(f"  Inicio: {marcador['inicio']:.1f}s")
        print(f"  Fim: {marcador['fim']:.1f}s")
        print(f"  Duracao: {marcador['duracao']:.1f}s ({marcador['duracao']/60:.1f} min)")
        print(f"  Marcador: {marcador['texto_marcador']}")
        
        # Extrair segmento
        segmento = audio[inicio_ms:fim_ms]
        
        # Nome do arquivo
        nome_arquivo = f"B{numero}.mp3"
        caminho_saida = os.path.join(saida_dir, nome_arquivo)
        
        # Exportar
        segmento.export(caminho_saida, format="mp3")
        
        tamanho_mb = os.path.getsize(caminho_saida) / (1024 * 1024)
        print(f"  ✓ Arquivo: {nome_arquivo} ({tamanho_mb:.1f} MB)")
        logger.info(f"Boletim B{numero} exportado: {tamanho_mb:.1f} MB")
        
        arquivos_exportados.append(caminho_saida)
    
    return arquivos_exportados


def gerar_log_segmentacao(
    marcadores: List[dict],
    audio_path: str,
    duracao_total: float,
    saida_dir: str
) -> str:
    """Gera arquivo JSON com o log da segmentação."""
    log_data = {
        "data_geracao": datetime.now().isoformat(),
        "audio_original": str(audio_path),
        "duracao_total_segundos": duracao_total,
        "duracao_total_minutos": round(duracao_total / 60, 2),
        "total_boletins": len(marcadores),
        "boletins": []
    }
    
    for marcador in marcadores:
        log_data["boletins"].append({
            "numero": marcador["numero"],
            "inicio_segundos": round(marcador["inicio"], 2),
            "fim_segundos": round(marcador["fim"], 2),
            "duracao_segundos": round(marcador["duracao"], 2),
            "duracao_minutos": round(marcador["duracao"] / 60, 2),
            "marcador_detectado": marcador["texto_marcador"],
            "detectado_automaticamente": marcador.get("detectado", False)
        })
    
    caminho_log = os.path.join(saida_dir, "log_segmentacao.json")
    with open(caminho_log, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Log de segmentação salvo: {caminho_log}")
    return caminho_log


# =============================================================================
# API de alto nível (para uso via pipeline)
# =============================================================================

@dataclass
class SegmentacaoConfig:
    """Configuração para segmentação de boletins."""
    modelo: str = DEFAULT_MODELO
    numero_boletins: int = DEFAULT_NUM_BOLETINS
    idioma: str = DEFAULT_IDIOMA
    output_dir: str = DEFAULT_OUTPUT_DIR
    sem_transcricao: bool = False
    duracao_total_override: Optional[float] = None  # Usa em vez de transcrever


def segmentar_audio(
    caminho_audio: str | Path,
    config: Optional[SegmentacaoConfig] = None,
    **kwargs,
) -> list[str]:
    """
    Função de alto nível para segmentar áudio de boletins.
    
    Args:
        caminho_audio: Caminho do áudio
        config: Configuração (ou usa padrão)
        **kwargs: Sobrescreve campos da config
    
    Returns:
        Lista de caminhos dos boletins segmentados
    """
    cfg = config or SegmentacaoConfig()
    
    # Sobrescreve com kwargs
    for k, v in kwargs.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    
    audio_path = Path(caminho_audio)
    if not audio_path.exists():
        raise FileNotFoundError(f"Áudio não encontrado: {audio_path}")
    
    # Transcrição
    if cfg.sem_transcricao:
        duracao_total = cfg.duracao_total_override or 514.5
        transcricao = []
    else:
        modelo = carregar_modelo_whisper(cfg.modelo)
        transcricao, duracao_total = transcrever_audio(modelo, str(audio_path), cfg.idioma)
    
    # Detectar marcadores
    marcadores_detectados = detectar_marcadores_boletim(transcricao) if transcricao else {}
    
    # Construir limites
    marcadores = construir_limites_boletins(
        marcadores_detectados, duracao_total, cfg.numero_boletins
    )
    
    # Exportar
    from pydub import AudioSegment
    audio = AudioSegment.from_file(str(audio_path))
    arquivos = exportar_boletins(audio, marcadores, cfg.output_dir)
    
    # Log
    gerar_log_segmentacao(marcadores, str(audio_path), duracao_total, cfg.output_dir)
    
    return arquivos


def main_cli():
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Segmenta áudio de boletins em arquivos individuais."
    )
    parser.add_argument(
        "audio",
        nargs="?",
        default=DEFAULT_AUDIO_PATH,
        help=f"Caminho do áudio (padrão: {DEFAULT_AUDIO_PATH})"
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help=f"Diretório de saída (padrão: {DEFAULT_OUTPUT_DIR})"
    )
    parser.add_argument(
        "-m", "--modelo",
        default=None,
        choices=["tiny", "base", "small"],
        help=f"Modelo Whisper (padrão: {DEFAULT_MODELO})"
    )
    parser.add_argument(
        "-n", "--numero-boletins",
        type=int,
        default=DEFAULT_NUM_BOLETINS,
        help=f"Número total de boletins (padrão: {DEFAULT_NUM_BOLETINS})"
    )
    parser.add_argument(
        "--sem-transcricao",
        action="store_true",
        help="Pula transcrição e usa índices estimados"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Modo verboso"
    )
    
    args = parser.parse_args()
    
    audio_path = args.audio
    output_dir = args.output if args.output else DEFAULT_OUTPUT_DIR
    modelo_nome = args.modelo if args.modelo else DEFAULT_MODELO
    num_boletins = args.numero_boletins
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    print("=" * 60)
    print("SEGMENTADOR DE BOLETINS - TJRN RADIO")
    print("=" * 60)
    print(f"Audio de entrada: {audio_path}")
    print(f"Diretorio de saida: {output_dir}")
    print(f"Modelo Whisper: {modelo_nome}")
    print(f"Numero de boletins: {num_boletins}")
    print()
    
    if not os.path.exists(audio_path):
        logger.error(f"Arquivo não encontrado: {audio_path}")
        sys.exit(1)
    
    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    logger.info(f"Arquivo: {file_size_mb:.1f} MB")
    
    try:
        if args.sem_transcricao:
            logger.warning("Modo sem transcrição - usando índices estimados")
            duracao_total = 514.5
            transcricao = []
        else:
            modelo = carregar_modelo_whisper(modelo_nome)
            transcricao, duracao_total = transcrever_audio(modelo, audio_path)
        
        if transcricao:
            marcadores_detectados = detectar_marcadores_boletim(transcricao)
        else:
            marcadores_detectados = {}
        
        print("\nConstruindo limites dos boletins...")
        marcadores = construir_limites_boletins(marcadores_detectados, duracao_total, num_boletins)
        
        from pydub import AudioSegment
        print("Carregando áudio para corte...")
        audio = AudioSegment.from_file(audio_path)
        logger.info(f"Áudio carregado: {len(audio)/1000:.1f}s")
        
        print("\n" + "=" * 60)
        print("EXPORTANDO BOLETINS")
        print("=" * 60)
        arquivos = exportar_boletins(audio, marcadores, output_dir)
        
        caminho_log = gerar_log_segmentacao(marcadores, audio_path, duracao_total, output_dir)
        
        print("\n" + "=" * 60)
        print("SEGMENTAÇÃO CONCLUÍDA COM SUCESSO!")
        print("=" * 60)
        print(f"Arquivo original: {os.path.basename(audio_path)} ({file_size_mb:.1f} MB)")
        print(f"Duração total: {duracao_total:.1f}s ({duracao_total/60:.1f} min)")
        print(f"Boletins segmentados: {len(marcadores)}")
        print(f"Diretorio de saida: {output_dir}/")
        print()
        
        total_tamanho = 0
        for m in marcadores:
            nome = f"B{m['numero']}.mp3"
            caminho = os.path.join(output_dir, nome)
            if os.path.exists(caminho):
                tamanho_mb = os.path.getsize(caminho) / (1024 * 1024)
                total_tamanho += tamanho_mb
                print(f"  {nome}: {tamanho_mb:.1f} MB ({m['duracao']:.1f}s)")
            else:
                print(f"  {nome}: ❌ Arquivo não gerado")
        
        print(f"\nTotal dos arquivos segmentados: {total_tamanho:.1f} MB")
        print(f"Log: {caminho_log}")
        
    except Exception as e:
        logger.error(f"Erro durante a segmentação: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main_cli()
