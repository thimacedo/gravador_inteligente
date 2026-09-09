#!/usr/bin/env python3
"""
Módulo de Montagem de Boletins - Monta boletins com vinhetas e estrutura de rádio.

Receita do boletim:
    VHT_ABERTURA_BOLETIM (vinheta de abertura)
    Cabeça (manchete da notícia até o primeiro silêncio longo/pausa)
    VHT_PASSAGEM_BOLETIM (vinheta de passagem)
    OFF (corpo da notícia, após a pausa)
    VHT_ENCERRAMENTO_BOLETIM (vinheta de encerramento)

Os caminhos dos assets são configuráveis via AssetsConfig.
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydub import AudioSegment

logger = logging.getLogger(__name__)

# Caminho base do workspace (DIVISOR)
WORKSPACE_DIR = os.environ.get(
    "DIVISOR_WORKSPACE",
    "E:/02_Projetos_Trabalho/Projetos_Ativos/DIVISOR"
)

# Caminho padrão dos assets de vinhetas (relativo ao workspace)
ASSETS_BOLETIM_DIR = os.path.join(WORKSPACE_DIR, "assets", "vinhetas", "boletim")


# =============================================================================
# Configuração
# =============================================================================

@dataclass
class AssetsConfig:
    """Caminhos dos assets de vinhetas."""
    
    abertura: str = field(default=os.path.join(ASSETS_BOLETIM_DIR, "VHT_ABERTURA_BOLETIM.mp3"))
    passagem: str = field(default=os.path.join(ASSETS_BOLETIM_DIR, "VHT_PASSAGEM_BOLETIM.mp3"))
    encerramento: str = field(default=os.path.join(ASSETS_BOLETIM_DIR, "VHT_ENCERRAMENTO_BOLETIM.mp3"))
    
    def validate(self) -> list[str]:
        """Verifica se todos os assets existem. Retorna lista de erros."""
        errors = []
        for nome, caminho in [
            ("abertura", self.abertura),
            ("passagem", self.passagem),
            ("encerramento", self.encerramento),
        ]:
            if not os.path.exists(caminho):
                errors.append(f"Asset '{nome}' não encontrado: {caminho}")
        return errors


@dataclass
class MontagemConfig:
    """Configurações para a montagem do boletim."""
    
    # Assets
    assets: AssetsConfig = field(default_factory=AssetsConfig)
    
    # Crossfade entre vinhetas e áudio (ms)
    crossfade_ms: int = 150
    
    # Duração do silence detector para separar "cabeça" de "off"
    # Pausas maiores que isso separam manchete do corpo
    pausa_threshold_ms: int = 800
    
    # Threshold de silêncio para detecção de pausa (dBFS)
    silence_threshold_db: int = -35
    
    # Se deve normalizar o áudio final
    normalize_final: bool = True
    target_lufs: float = -16.0
    
    # Formato de saída
    output_format: str = "mp3"
    output_bitrate: str = "192k"
    
    # Duração de silence a adicionar antes/depois das vinhetas (ms)
    silence_before_vinheta_ms: int = 50
    silence_after_vinheta_ms: int = 100


# =============================================================================
# Funções de detecção de estrutura
# =============================================================================

def detectar_pausa_principal(
    audio: AudioSegment,
    threshold_db: int = -35,
    min_pausa_ms: int = 500,
    search_window_pct: float = 0.3,
) -> Optional[int]:
    """
    Detecta a primeira pausa longa no áudio (separa cabeça de off).
    
    Procura pelo primeiro silêncio longo nos primeiros X% do áudio.
    Isso separa a manchete (cabeça) do corpo da notícia (off).
    
    Args:
        audio: Áudio completo
        threshold_db: Threshold para considerar silêncio
        min_pausa_ms: Duração mínima da pausa
        search_window_pct: Porcentagem inicial do áudio para buscar (0.0-1.0)
    
    Returns:
        Timestamp (ms) do início da pausa, ou None se não encontrar
    """
    from pydub.silence import detect_nonsilent
    
    # Limita a busca aos primeiros X% do áudio
    search_end = int(len(audio) * search_window_pct)
    audio_search = audio[:search_end]
    
    # Encontra faixas de áudio (não-silêncio)
    nonsilent = detect_nonsilent(
        audio_search,
        min_silence_len=min_pausa_ms,
        silence_thresh=threshold_db,
    )
    
    if len(nonsilent) < 2:
        # Não encontrou separação clara
        logger.info("Pausa principal não detectada (áudio contínuo)")
        return None
    
    # A pausa é o espaço entre o primeiro e o segundo segmento não-silêncio
    primeira_fala_end = nonsilent[0][1]
    segunda_fala_start = nonsilent[1][0]
    pausa_duration = segunda_fala_start - primeira_fala_end
    
    if pausa_duration >= min_pausa_ms:
        logger.info(
            f"Pausa detectada: {primeira_fala_end/1000:.1f}s - "
            f"{segunda_fala_start/1000:.1f}s ({pausa_duration}ms)"
        )
        return primeira_fala_end
    
    return None


def separar_cabeca_off(
    audio: AudioSegment,
    pausa_ms: Optional[int] = None,
    config: Optional[MontagemConfig] = None,
) -> tuple[AudioSegment, AudioSegment]:
    """
    Separa o áudio em cabeça (manchete) e off (corpo).
    
    Se pausa_ms é None, tenta detectar automaticamente.
    
    Returns:
        (cabeca, off) - dois segmentos de áudio
    """
    cfg = config or MontagemConfig()
    
    if pausa_ms is None:
        pausa_ms = detectar_pausa_principal(
            audio,
            threshold_db=cfg.silence_threshold_db,
            min_pausa_ms=cfg.pausa_threshold_ms,
        )
    
    if pausa_ms is None:
        # Sem pausa detectada: divide no primeiro terço
        split_point = len(audio) // 3
        logger.info(f"Sem pausa, dividindo em 1/3 ({split_point/1000:.1f}s)")
        return audio[:split_point], audio[split_point:]
    
    # Separa na pausa
    cabeca = audio[:pausa_ms]
    off = audio[pausa_ms:]
    
    logger.info(
        f"Cabeça: {len(cabeca)/1000:.1f}s | OFF: {len(off)/1000:.1f}s"
    )
    
    return cabeca, off


# =============================================================================
# Montagem
# =============================================================================

def montar_boletim(
    audio_editado: str | Path,
    output_path: str | Path,
    config: Optional[MontagemConfig] = None,
    pausa_override_ms: Optional[int] = None,
) -> dict:
    """
    Monta o boletim completo com vinhetas.
    
    Estrutura:
        VHT_ABERTURA + CABEÇA + VHT_PASSAGEM + OFF + VHT_ENCERRAMENTO
    
    Args:
        audio_editado: Áudio já editado (sem erros/repetições)
        output_path: Caminho do arquivo final
        config: Configurações de montagem
        pausa_override_ms: Se definido, usa essa posição de pausa em vez de detectar
    
    Returns:
        Dict com informações da montagem
    """
    cfg = config or MontagemConfig()
    audio_editado = Path(audio_editado)
    output_path = Path(output_path)
    
    # Validar assets
    errors = cfg.assets.validate()
    if errors:
        for e in errors:
            logger.error(e)
        raise FileNotFoundError(f"Assets faltando: {errors}")
    
    if not audio_editado.exists():
        raise FileNotFoundError(f"Áudio não encontrado: {audio_editado}")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"=== Montando boletim: {audio_editado.name} ===")
    
    # Carregar áudio e vinhetas
    audio = AudioSegment.from_file(str(audio_editado))
    vht_abertura = AudioSegment.from_file(cfg.assets.abertura)
    vht_passagem = AudioSegment.from_file(cfg.assets.passagem)
    vht_encerramento = AudioSegment.from_file(cfg.assets.encerramento)
    
    logger.info(f"Áudio base: {len(audio)/1000:.1f}s")
    logger.info(f"Vinheta abertura: {len(vht_abertura)/1000:.1f}s")
    logger.info(f"Vinheta passagem: {len(vht_passagem)/1000:.1f}s")
    logger.info(f"Vinheta encerramento: {len(vht_encerramento)/1000:.1f}s")
    
    # Separar cabeça e off
    cabeca, off = separar_cabeca_off(audio, pausa_override_ms, cfg)
    
    # Silêncios para spacing
    silence_short = AudioSegment.silent(duration=cfg.silence_before_vinheta_ms)
    silence_medium = AudioSegment.silent(duration=cfg.silence_after_vinheta_ms)
    
    # Montar com crossfade
    crossfade = cfg.crossfade_ms
    
    logger.info("Montando estrutura...")
    
    # Parte 1: Abertura + Cabeça
    parte1 = vht_abertura + silence_short
    if crossfade > 0 and len(parte1) > crossfade and len(cabeca) > crossfade:
        parte1 = parte1.append(cabeca, crossfade=crossfade)
    else:
        parte1 = parte1 + cabeca
    
    # Parte 2: Passagem + Off
    parte2 = vht_passagem + silence_short
    if crossfade > 0 and len(parte2) > crossfade and len(off) > crossfade:
        parte2 = parte2.append(off, crossfade=crossfade)
    else:
        parte2 = parte2 + off
    
    # Parte 3: Encerramento
    parte3 = vht_encerramento
    
    # Juntar tudo com pequenos espaçamentos
    resultado = parte1 + silence_medium + parte2 + silence_medium + parte3
    
    # Normalização final
    if cfg.normalize_final:
        logger.info("Normalizando volume final...")
        # Usa pydub para normalização simples (peak normalization)
        # Para LUFS precisos, usaria ffmpeg loudnorm
        from app.tratamento_audio import normalize_volume
        temp_path = output_path.with_suffix(".tmp.mp3")
        resultado.export(str(temp_path), format="mp3", bitrate="192k")
        normalize_volume(temp_path, output_path, target_lufs=cfg.target_lufs)
        temp_path.unlink(missing_ok=True)
    else:
        resultado.export(str(output_path), format=cfg.output_format, bitrate=cfg.output_bitrate)
    
    # Info final
    final_info = {
        "status": "ok",
        "audio_base": str(audio_editado),
        "output": str(output_path),
        "duracao_base_s": round(len(audio) / 1000, 2),
        "duracao_final_s": round(len(resultado) / 1000, 2),
        "tamanho_mb": round(output_path.stat().st_size / (1024 * 1024), 2),
        "estrutura": {
            "vinheta_abertura_s": round(len(vht_abertura) / 1000, 2),
            "cabeca_s": round(len(cabeca) / 1000, 2),
            "vinheta_passagem_s": round(len(vht_passagem) / 1000, 2),
            "off_s": round(len(off) / 1000, 2),
            "vinheta_encerramento_s": round(len(vht_encerramento) / 1000, 2),
        },
    }
    
    logger.info(
        f"✅ Boletim montado: {output_path.name} "
        f"({final_info['duracao_final_s']:.1f}s, {final_info['tamanho_mb']:.1f}MB)"
    )
    
    return final_info


def montar_boletins_lote(
    arquivos_audio: list[str | Path],
    output_dir: str | Path,
    config: Optional[MontagemConfig] = None,
    prefixo: str = "boletim_",
) -> list[dict]:
    """
    Monta múltiplos boletins em lote.
    
    Args:
        arquivos_audio: Lista de caminhos de áudio editados
        output_dir: Diretório de saída
        config: Configurações de montagem
        prefixo: Prefixo para nomes dos arquivos de saída
    
    Returns:
        Lista de resultados por boletim
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    resultados = []
    
    for i, audio_path in enumerate(arquivos_audio, 1):
        audio_path = Path(audio_path)
        nome_saida = f"{prefixo}{i}.mp3"
        output_path = output_dir / nome_saida
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Montando boletim {i}/{len(arquivos_audio)}: {audio_path.name}")
        logger.info(f"{'='*60}")
        
        try:
            resultado = montar_boletim(audio_path, output_path, config)
            resultados.append(resultado)
        except Exception as e:
            logger.error(f"Erro ao montar {audio_path.name}: {e}")
            resultados.append({
                "status": "erro",
                "audio_base": str(audio_path),
                "erro": str(e),
            })
    
    # Resumo
    sucessos = sum(1 for r in resultados if r.get("status") == "ok")
    total_duracao = sum(r.get("duracao_final_s", 0) for r in resultados if r.get("status") == "ok")
    
    logger.info(f"\n{'='*60}")
    logger.info(f"RESUMO: {sucessos}/{len(arquivos_audio)} boletins montados")
    logger.info(f"Tempo total: {total_duracao:.1f}s")
    logger.info(f"{'='*60}")
    
    return resultados


# =============================================================================
# CLI
# =============================================================================

def main_cli():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Monta boletins com vinhetas (abertura + cabeça + passagem + off + encerramento)"
    )
    parser.add_argument("audio", help="Caminho do áudio editado")
    parser.add_argument("-o", "--output", help="Caminho do arquivo de saída")
    parser.add_argument("--assets-dir", help="Diretório dos assets (sobrescreve padrão)")
    parser.add_argument("--crossfade", type=int, default=150, help="Crossfade em ms")
    parser.add_argument("--pausa-ms", type=int, help="Posição manual da pausa (ms)")
    parser.add_argument("--no-normalize", action="store_true", help="Pula normalização final")
    parser.add_argument("--lufs", type=float, default=-16.0, help="Target LUFS")
    parser.add_argument("-v", "--verbose", action="store_true", help="Modo verboso")
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )
    
    # Configurar assets
    assets = AssetsConfig()
    if args.assets_dir:
        assets = AssetsConfig(
            abertura=f"{args.assets_dir}/VHT_ABERTURA_BOLETIM.mp3",
            passagem=f"{args.assets_dir}/VHT_PASSAGEM_BOLETIM.mp3",
            encerramento=f"{args.assets_dir}/VHT_ENCERRAMENTO_BOLETIM.mp3",
        )
    
    config = MontagemConfig(
        assets=assets,
        crossfade_ms=args.crossfade,
        normalize_final=not args.no_normalize,
        target_lufs=args.lufs,
    )
    
    output = args.output or Path(args.audio).stem + "_montado.mp3"
    
    resultado = montar_boletim(args.audio, output, config, pausa_override_ms=args.pausa_ms)
    
    print("\n" + "=" * 60)
    print("RESULTADO DA MONTAGEM")
    print("=" * 60)
    print(f"Status: {resultado['status']}")
    
    if resultado['status'] == 'ok':
        print(f"Áudio base: {resultado['audio_base']}")
        print(f"Output: {resultado['output']}")
        print(f"Duração base: {resultado['duracao_base_s']}s")
        print(f"Duração final: {resultado['duracao_final_s']}s")
        print(f"Tamanho: {resultado['tamanho_mb']} MB")
        print("\nEstrutura:")
        for parte, dur in resultado['estrutura'].items():
            print(f"  {parte}: {dur}s")
    else:
        print(f"Erro: {resultado.get('erro', 'Erro desconhecido')}")


if __name__ == "__main__":
    main_cli()
