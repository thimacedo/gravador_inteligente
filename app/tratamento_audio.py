#!/usr/bin/env python3
"""
Módulo de Tratamento de Áudio - Pipeline de normalização e limpeza.

Etapas (cada uma opcional/chamável independentemente):
1. normalize_volume() - Normaliza volume para padrão podcast (-16 LUFS)
2. reduce_noise() - Redução de ruído de fundo via noisereduce ou ffmpeg afftdn
3. reduce_breath() - Redução de respiração (preserva fonemas)
4. remove_silence() - Remove silêncios longos opcionais
5. process() - Pipeline completo de tratamento
"""

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# Configuração
# =============================================================================

@dataclass
class TratamentoConfig:
    """Configurações para o pipeline de tratamento de áudio."""
    
    # --- Normalização de volume ---
    target_lufs: float = -16.0  # Padrão podcast (Spotify/YouTube)
    target_peak_db: float = -1.0  # Peak máximo em dB
    normalize: bool = True
    
    # --- Redução de ruído ---
    reduce_noise: bool = True
    noise_reduction_strength: float = 0.5  # 0.0 a 1.0
    noise_sample_duration_ms: int = 500  # ms de amostra de ruído (início do áudio)
    noise_method: str = "auto"  # "auto", "noisereduce_lib", "ffmpeg_afftdn"
    
    # --- Redução de respiração ---
    reduce_breath: bool = True
    breath_threshold_db: float = -30  # Abaixo disso pode ser respiração
    breath_attenuation_db: float = -6  # Atenuação em dB para respirações
    breath_min_duration_ms: int = 50  # Duração mínima para considerar respiração
    breath_max_duration_ms: int = 300  # Duração máxima para considerar respiração
    
    # --- Remoção de silêncios ---
    remove_silence: bool = False  # Não remove silêncios por padrão (pode cortar pausas naturais)
    silence_threshold_db: int = -40
    min_silence_len_ms: int = 2000
    keep_silence_ms: int = 300
    
    # --- Geral ---
    output_format: str = "mp3"
    output_bitrate: str = "128k"
    sample_rate: int = 44100
    channels: int = 2  # stereo
    temp_dir: str = "temp_processing"
    verbose: bool = False


# =============================================================================
# Utilitários
# =============================================================================

def get_audio_info(path: str | Path) -> dict:
    """Retorna informações sobre o arquivo de áudio via ffprobe."""
    path = str(path)
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe falhou: {r.stderr}")
    
    info = json.loads(r.stdout)
    fmt = info.get("format", {})
    streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    
    if not streams:
        raise ValueError("Nenhum stream de áudio encontrado")
    
    audio_stream = streams[0]
    return {
        "duration": float(fmt.get("duration", 0)),
        "size_bytes": int(fmt.get("size", 0)),
        "bit_rate": fmt.get("bit_rate"),
        "codec": audio_stream.get("codec_name"),
        "sample_rate": int(audio_stream.get("sample_rate", 0)),
        "channels": int(audio_stream.get("channels", 0)),
    }


def measure_lufs(path: str | Path) -> dict:
    """Mede LUFS (loudness) do áudio usando ffmpeg loudnorm filter."""
    path = str(path)
    cmd = [
        "ffmpeg", "-i", path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-"
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    
    # Extrai JSON do stderr
    output = r.stderr
    try:
        # Encontra o bloco JSON no output
        start = output.index("{")
        end = output.rindex("}") + 1
        data = json.loads(output[start:end])
        return {
            "input_i": float(data.get("input_i", 0)),  # Input integrated loudness
            "input_tp": float(data.get("input_tp", 0)),  # Input true peak
            "input_lra": float(data.get("input_lra", 0)),  # Input loudness range
            "input_thresh": float(data.get("input_thresh", 0)),
        }
    except (ValueError, KeyError):
        logger.warning("Não foi possível medir LUFS")
        return {"input_i": 0, "input_tp": 0, "input_lra": 0, "input_thresh": 0}


def load_audio_to_numpy(path: str | Path) -> tuple[np.ndarray, int]:
    """Carrega áudio para numpy array (mono) via ffmpeg."""
    path = str(path)
    cmd = [
        "ffmpeg", "-i", path,
        "-ac", "1",  # mono
        "-ar", "44100",
        "-f", "s16le",  # PCM 16-bit signed
        "-acodec", "pcm_s16le",
        "-v", "quiet",
        "pipe:1"
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ao carregar áudio: {r.stderr.decode()}")
    
    audio_array = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    return audio_array, 44100


def save_numpy_to_audio(audio: np.ndarray, path: str | Path, sample_rate: int = 44100):
    """Salva numpy array como arquivo de áudio via ffmpeg."""
    path = str(path)
    # Converte de volta para int16
    audio_int16 = (audio * 32767).astype(np.int16)
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        "-i", "pipe:0",
        "-acodec", "libmp3lame",
        "-b:a", "128k",
        path
    ]
    r = subprocess.run(cmd, input=audio_int16.tobytes(), capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ao salvar áudio: {r.stderr.decode()}")


# =============================================================================
# Etapa 0: Detecção e Correção de Canal Morto
# =============================================================================

def detectar_canal_morto(path: str | Path, threshold_db: float = 30.0) -> dict:
    """
    Detecta se o áudio stereo tem áudio apenas em um canal.
    
    Returns:
        dict com:
        - is_stereo: bool
        - is_asymmetric: bool
        - left_db: float
        - right_db: float
        - diff_db: float
        - active_channel: str ("left", "right", "both")
    """
    path = str(path)
    
    # Verificar número de canais
    cmd_info = ['ffprobe', '-v', 'quiet', '-select_streams', 'a:0', 
                '-show_entries', 'stream=channels', '-of', 'csv=p=0', path]
    r = subprocess.run(cmd_info, capture_output=True, text=True)
    channels = int(r.stdout.strip()) if r.stdout.strip().isdigit() else 1
    
    if channels < 2:
        return {
            "is_stereo": False,
            "is_asymmetric": False,
            "left_db": 0,
            "right_db": 0,
            "diff_db": 0,
            "active_channel": "mono",
        }
    
    # Medir volume de cada canal
    import re
    
    cmd_l = ['ffmpeg', '-i', path, '-af', 'pan=mono|c0=FL,volumedetect', '-f', 'null', '-']
    r_l = subprocess.run(cmd_l, capture_output=True, text=True)
    
    cmd_r = ['ffmpeg', '-i', path, '-af', 'pan=mono|c0=FR,volumedetect', '-f', 'null', '-']
    r_r = subprocess.run(cmd_r, capture_output=True, text=True)
    
    l_match = re.search(r'mean_volume: ([-\d.]+) dB', r_l.stderr)
    r_match = re.search(r'mean_volume: ([-\d.]+) dB', r_r.stderr)
    
    left_db = float(l_match.group(1)) if l_match else -99.0
    right_db = float(r_match.group(1)) if r_match else -99.0
    
    diff = abs(left_db - right_db)
    
    if diff > threshold_db and left_db > right_db:
        active = "left"
    elif diff > threshold_db and right_db > left_db:
        active = "right"
    else:
        active = "both"
    
    return {
        "is_stereo": True,
        "is_asymmetric": diff > threshold_db,
        "left_db": left_db,
        "right_db": right_db,
        "diff_db": diff,
        "active_channel": active,
    }


def corrigir_canal_morto(input_path: str | Path, output_path: str | Path) -> dict:
    """
    Se o áudio é stereo assimétrico (áudio só em um canal),
    converte para mono usando apenas o canal ativo.
    
    Returns:
        dict com status e info
    """
    info = detectar_canal_morto(input_path)
    
    if not info["is_asymmetric"]:
        return {"status": "ok", "action": "none", "info": info}
    
    channel = info["active_channel"]
    logger.info(f"Canal morto detectado! Audio apenas no canal {channel} "
                f"(diff={info['diff_db']:.1f}dB). Convertendo para mono...")
    
    # Extrair apenas o canal ativo e salvar como mono
    if channel == "left":
        pan_filter = "pan=mono|c0=FL"
    else:
        pan_filter = "pan=mono|c0=FR"
    
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", pan_filter,
        "-ar", "44100",
        str(output_path)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    
    if r.returncode != 0:
        raise RuntimeError(f"Falha ao corrigir canal: {r.stderr}")
    
    logger.info(f"  Convertido para mono (canal {channel})")
    return {"status": "ok", "action": "converted_to_mono", "channel": channel, "info": info}


# =============================================================================
# Etapa 1: Normalização de Volume
# =============================================================================

def normalize_volume(
    input_path: str | Path,
    output_path: str | Path,
    target_lufs: float = -16.0,
    target_peak_db: float = -1.0,
) -> dict:
    """
    Normaliza volume para padrão podcast usando ffmpeg loudnorm (two-pass).
    
    Padrão podcast: -16 LUFS (Spotify/YouTube), peak máximo -1 dB.
    """
    input_path = str(input_path)
    output_path = str(output_path)
    
    logger.info(f"Normalizando volume para {target_lufs} LUFS...")
    
    # PASSO 1: Medir loudness atual
    cmd_measure = [
        "ffmpeg", "-i", input_path,
        "-af", f"loudnorm=I={target_lufs}:TP={target_peak_db}:LRA=11:print_format=json",
        "-f", "null", "-"
    ]
    r = subprocess.run(cmd_measure, capture_output=True, text=True)
    
    # Extrair medição do stderr
    measured = {}
    try:
        output = r.stderr
        start = output.index("{")
        end = output.rindex("}") + 1
        measured = json.loads(output[start:end])
    except (ValueError, KeyError):
        logger.warning("Medição LUFS falhou, usando normalização simples")
    

    # PASSO 2: Aplicar normalização (single-pass com loudnorm)
    # Single-pass é suficiente para a maioria dos casos e evita problemas de parsing
    filter_str = f"loudnorm=I={target_lufs}:TP={target_peak_db}:LRA=11"
    
    cmd_apply = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", filter_str,
        "-ar", "44100",
        output_path
    ]
    r = subprocess.run(cmd_apply, capture_output=True, text=True)
    
    if r.returncode != 0:
        raise RuntimeError(f"Normalização falhou: {r.stderr}")
    
    # Medir resultado
    result_info = measure_lufs(output_path)
    logger.info(f"  Volume normalizado: {result_info['input_i']:.1f} LUFS")
    
    return {
        "status": "ok",
        "target_lufs": target_lufs,
        "result_lufs": result_info["input_i"],
        "result_peak": result_info["input_tp"],
    }


# =============================================================================
# Etapa 2: Redução de Ruído
# =============================================================================

def reduce_noise(
    input_path: str | Path,
    output_path: str | Path,
    strength: float = 0.5,
    sample_duration_ms: int = 500,
    method: str = "auto",
) -> dict:
    """
    Reduz ruído de fundo do áudio.
    
    Métodos:
    - "noisereduce_lib": Usa biblioteca noisereduce (Python, mais preciso)
    - "ffmpeg_afftdn": Usa ffmpeg afftdn (mais rápido, sem dependências extras)
    - "auto": Escolhe automaticamente
    """
    input_path = str(input_path)
    output_path = str(output_path)
    
    logger.info(f"Reduzindo ruído de fundo (força={strength:.0%})...")
    
    # Escolher método
    if method == "auto":
        try:
            import noisereduce as nr
            method = "noisereduce_lib"
        except ImportError:
            method = "ffmpeg_afftdn"
    
    if method == "noisereduce_lib":
        return _reduce_noise_noisereduce(input_path, output_path, strength, sample_duration_ms)
    else:
        return _reduce_noise_ffmpeg(input_path, output_path, strength)


def _reduce_noise_noisereduce(
    input_path: str,
    output_path: str,
    strength: float,
    sample_duration_ms: int,
) -> dict:
    """Redução de ruído via biblioteca noisereduce."""
    import noisereduce as nr
    from pydub import AudioSegment
    
    logger.info("  Usando noisereduce (biblioteca Python)...")
    
    # Carregar áudio
    audio = AudioSegment.from_file(input_path)
    sample_rate = audio.frame_rate
    
    # Converter para numpy (mono)
    audio_mono = audio.set_channels(1)
    audio_array = np.array(audio_mono.get_array_of_samples(), dtype=np.float32)
    
    # Normalizar para [-1, 1]
    if audio_array.dtype == np.int16:
        audio_array = audio_array / 32768.0
    elif audio_array.dtype == np.int32:
        audio_array = audio_array / 2147483648.0
    
    # Amostra de ruído (primeiros N ms)
    noise_samples = int(sample_rate * sample_duration_ms / 1000)
    noise_clip = audio_array[:noise_samples]
    
    # Aplicar redução
    reduced = nr.reduce_noise(
        y=audio_array,
        y_noise=noise_clip,
        sr=sample_rate,
        prop_decrease=strength,
        stationary=True,
    )
    
    # Converter de volta para int16
    reduced_int16 = (reduced * 32767).clip(-32768, 32767).astype(np.int16)
    
    # Salvar
    result = AudioSegment(
        reduced_int16.tobytes(),
        frame_rate=sample_rate,
        sample_width=2,
        channels=1,
    )
    
    # Se original era stereo, duplicar
    if audio.channels == 2:
        result = result.set_channels(2)
    
    result.export(output_path, format="mp3", bitrate="128k")
    
    logger.info("  Redução de ruído concluída (noisereduce)")
    return {"status": "ok", "method": "noisereduce_lib", "strength": strength}


def _reduce_noise_ffmpeg(input_path: str, output_path: str, strength: float) -> dict:
    """Redução de ruído via ffmpeg afftdn."""
    logger.info("  Usando ffmpeg afftdn...")
    
    # afftdn params: nr=noise reduction amount (0-100), nf=noise floor
    nr_amount = int(strength * 100)  # 0-100
    
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", f"afftdn=nf=-40:nr={nr_amount}",
        "-ar", "44100",
        output_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    
    if r.returncode != 0:
        raise RuntimeError(f"Redução de ruído ffmpeg falhou: {r.stderr}")
    
    logger.info("  Redução de ruído concluída (ffmpeg afftdn)")
    return {"status": "ok", "method": "ffmpeg_afftdn", "strength": strength}


# =============================================================================
# Etapa 3: Redução de Respiração
# =============================================================================

def reduce_breath(
    input_path: str | Path,
    output_path: str | Path,
    threshold_db: float = -30,
    attenuation_db: float = -6,
    min_duration_ms: int = 50,
    max_duration_ms: int = 300,
) -> dict:
    """
    Reduz a intensidade da respiração sem eliminar fonemas.
    
    Estratégia: Detecta segmentos curtos e de baixa energia que se encaixam
    no padrão de respiração e aplica atenuação suave.
    
    Usa análise de energia em janelas curtas para identificar respirações.
    """
    from pydub import AudioSegment
    from pydub.silence import detect_nonsilent
    
    input_path = str(input_path)
    output_path = str(output_path)
    
    logger.info("Reduzindo respiração...")
    
    audio = AudioSegment.from_file(input_path)
    
    # Encontra segmentos não-silêncios (fala)
    nonsilent_ranges = detect_nonsilent(
        audio,
        min_silence_len=min_duration_ms,
        silence_thresh=threshold_db,
    )
    
    # Identifica "intervalos" entre fala que podem ser respiração
    breath_segments = []
    for i in range(len(nonsilent_ranges) - 1):
        end_current = nonsilent_ranges[i][1]
        start_next = nonsilent_ranges[i + 1][0]
        gap_duration = start_next - end_current
        
        # Respiração: gap entre 50ms e 300ms com energia baixa
        if min_duration_ms <= gap_duration <= max_duration_ms:
            # Verifica energia no gap
            gap_audio = audio[end_current:start_next]
            if gap_audio.dBFS < threshold_db + 10:  # Próximo do silêncio
                breath_segments.append((end_current, start_next))
    
    if not breath_segments:
        logger.info("  Nenhuma respiração detectada")
        audio.export(output_path, format="mp3", bitrate="128k")
        return {"status": "ok", "breaths_found": 0}
    
    # Aplicar atenuação nas respirações
    attenuation_factor = 10 ** (attenuation_db / 20)  # Converte dB para fator linear
    
    result = AudioSegment.empty()
    pointer = 0
    
    for start, end in breath_segments:
        # Adiciona áudio antes da respiração
        result += audio[pointer:start]
        
        # Atenua a respiração
        breath = audio[start:end]
        breath = breath.apply_gain(attenuation_db)  # Reduz volume
        
        result += breath
        pointer = end
    
    # Adiciona restante
    if pointer < len(audio):
        result += audio[pointer:]
    
    result.export(output_path, format="mp3", bitrate="128k")
    
    logger.info(f"  {len(breath_segments)} respirações atenuadas em {attenuation_db}dB")
    return {"status": "ok", "breaths_found": len(breath_segments), "attenuation_db": attenuation_db}


# =============================================================================
# Etapa 4: Remoção de Silêncios Longos
# =============================================================================

def remove_silence(
    input_path: str | Path,
    output_path: str | Path,
    threshold_db: int = -40,
    min_silence_len_ms: int = 2000,
    keep_silence_ms: int = 300,
) -> dict:
    """Remove silêncios longos, mantendo pequenas pausas naturais."""
    from pydub import AudioSegment
    from pydub.silence import split_on_silence
    
    input_path = str(input_path)
    output_path = str(output_path)
    
    logger.info(f"Removendo silêncios > {min_silence_len_ms}ms...")
    
    audio = AudioSegment.from_file(input_path)
    
    chunks = split_on_silence(
        audio,
        min_silence_len=min_silence_len_ms,
        silence_thresh=threshold_db,
        keep_silence=keep_silence_ms,
    )
    
    if not chunks:
        logger.warning("  Áudio inteiro seria removido. Mantendo original.")
        audio.export(output_path, format="mp3", bitrate="128k")
        return {"status": "skipped", "reason": "all_silence"}
    
    result = AudioSegment.empty()
    for chunk in chunks:
        result += chunk
    
    result.export(output_path, format="mp3", bitrate="128k")
    
    original_duration = len(audio) / 1000
    new_duration = len(result) / 1000
    removed = original_duration - new_duration
    
    logger.info(f"  Removido {removed:.1f}s de silêncio ({original_duration:.1f}s → {new_duration:.1f}s)")
    
    return {
        "status": "ok",
        "original_duration_s": original_duration,
        "new_duration_s": new_duration,
        "removed_s": removed,
    }


# =============================================================================
# Pipeline Completo
# =============================================================================

def process(
    input_path: str | Path,
    output_path: str | Path,
    config: Optional[TratamentoConfig] = None,
) -> dict:
    """
    Pipeline completo de tratamento de áudio.
    
    Executa as etapas na ordem correta:
    0. Correção de canal morto (stereo assimétrico → mono)
    1. Redução de ruído (antes da normalização para não amplificar ruído)
    2. Redução de respiração
    3. Remoção de silêncios longos (se habilitado)
    4. Normalização de volume (por último para ajustar nível final)
    
    Args:
        input_path: Caminho do áudio original
        output_path: Caminho do áudio tratado
        config: Configurações de tratamento
    
    Returns:
        Dict com status e resultados de cada etapa
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    cfg = config or TratamentoConfig()
    
    if not input_path.exists():
        raise FileNotFoundError(f"Áudio não encontrado: {input_path}")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Criar diretório temporário
    temp_dir = Path(cfg.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    results = {
        "input": str(input_path),
        "output": str(output_path),
        "etapas": [],
    }
    
    current_file = str(input_path)
    temp_files = []
    
    try:
        # Etapa 0: Correção de canal morto (stereo assimétrico)
        canal_info = detectar_canal_morto(current_file)
        if canal_info["is_asymmetric"]:
            canal_output = temp_dir / f"{input_path.stem}_canal_fix.mp3"
            temp_files.append(canal_output)
            
            r = corrigir_canal_morto(current_file, canal_output)
            results["etapas"].append({"nome": "correcao_canal", **r})
            current_file = str(canal_output)
            logger.info(f"Correção de canal aplicada: {r.get('channel', '?')}")
        
        # Etapa 1: Redução de ruído
        if cfg.reduce_noise:
            noise_output = temp_dir / f"{input_path.stem}_denoised.mp3"
            temp_files.append(noise_output)
            
            r = reduce_noise(
                current_file, noise_output,
                strength=cfg.noise_reduction_strength,
                sample_duration_ms=cfg.noise_sample_duration_ms,
                method=cfg.noise_method,
            )
            results["etapas"].append({"nome": "reducao_ruido", **r})
            current_file = str(noise_output)
        
        # Etapa 2: Redução de respiração
        if cfg.reduce_breath:
            breath_output = temp_dir / f"{input_path.stem}_breath.mp3"
            temp_files.append(breath_output)
            
            r = reduce_breath(
                current_file, breath_output,
                threshold_db=cfg.breath_threshold_db,
                attenuation_db=cfg.breath_attenuation_db,
                min_duration_ms=cfg.breath_min_duration_ms,
                max_duration_ms=cfg.breath_max_duration_ms,
            )
            results["etapas"].append({"nome": "reducao_respiracao", **r})
            current_file = str(breath_output)
        
        # Etapa 3: Remoção de silêncios longos
        if cfg.remove_silence:
            silence_output = temp_dir / f"{input_path.stem}_nosilence.mp3"
            temp_files.append(silence_output)
            
            r = remove_silence(
                current_file, silence_output,
                threshold_db=cfg.silence_threshold_db,
                min_silence_len_ms=cfg.min_silence_len_ms,
                keep_silence_ms=cfg.keep_silence_ms,
            )
            results["etapas"].append({"nome": "remocao_silencio", **r})
            current_file = str(silence_output)
        
        # Etapa 4: Normalização de volume (sempre por último)
        if cfg.normalize:
            r = normalize_volume(
                current_file, output_path,
                target_lufs=cfg.target_lufs,
                target_peak_db=cfg.target_peak_db,
            )
            results["etapas"].append({"nome": "normalizacao_volume", **r})
        else:
            # Sem normalização, apenas copia o resultado
            from pydub import AudioSegment
            audio = AudioSegment.from_file(current_file)
            audio.export(str(output_path), format=cfg.output_format, bitrate=cfg.output_bitrate)
        
        # Info final
        final_info = get_audio_info(output_path)
        results["duracao_final_s"] = final_info["duration"]
        results["tamanho_final_mb"] = round(final_info["size_bytes"] / (1024 * 1024), 2)
        results["status"] = "ok"
        
        logger.info(f"✅ Tratamento concluído: {output_path.name} ({final_info['duration']:.1f}s)")
        
    finally:
        # Limpar arquivos temporários
        for f in temp_files:
            if f.exists():
                f.unlink()
    
    return results


# =============================================================================
# CLI
# =============================================================================

def main_cli():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Trata áudio de boletins: normaliza volume, reduz ruído e respiração"
    )
    parser.add_argument("audio", help="Caminho do arquivo de áudio")
    parser.add_argument("-o", "--output", help="Caminho do arquivo de saída")
    parser.add_argument("--no-normalize", action="store_true", help="Pula normalização de volume")
    parser.add_argument("--no-denoise", action="store_true", help="Pula redução de ruído")
    parser.add_argument("--no-breath", action="store_true", help="Pula redução de respiração")
    parser.add_argument("--remove-silence", action="store_true", help="Remove silêncios longos")
    parser.add_argument("--lufs", type=float, default=-16.0, help="Target LUFS (padrão: -16)")
    parser.add_argument("--noise-strength", type=float, default=0.5, help="Força da redução de ruído (0-1)")
    parser.add_argument("--breath-db", type=float, default=-6, help="Atenuação da respiração em dB")
    parser.add_argument("-v", "--verbose", action="store_true", help="Modo verboso")
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )
    
    config = TratamentoConfig(
        normalize=not args.no_normalize,
        reduce_noise=not args.no_denoise,
        reduce_breath=not args.no_breath,
        remove_silence=args.remove_silence,
        target_lufs=args.lufs,
        noise_reduction_strength=args.noise_strength,
        breath_attenuation_db=args.breath_db,
        verbose=args.verbose,
    )
    
    output = args.output or Path(args.audio).stem + "_tratado.mp3"
    
    resultado = process(args.audio, output, config)
    
    print("\n" + "=" * 60)
    print("RESULTADO DO TRATAMENTO")
    print("=" * 60)
    print(f"Status: {resultado['status']}")
    print(f"Entrada: {resultado['input']}")
    print(f"Saída: {resultado['output']}")
    print(f"Duração final: {resultado.get('duracao_final_s', '?')}s")
    print(f"Tamanho final: {resultado.get('tamanho_final_mb', '?')} MB")
    print("\nEtapas executadas:")
    for etapa in resultado.get("etapas", []):
        nome = etapa.get("nome", "?")
        status = etapa.get("status", "?")
        extra = ""
        if "result_lufs" in etapa:
            extra = f" → {etapa['result_lufs']:.1f} LUFS"
        elif "breaths_found" in etapa:
            extra = f" ({etapa['breaths_found']} respirações)"
        elif "method" in etapa:
            extra = f" [{etapa['method']}]"
        print(f"  ✓ {nome}: {status}{extra}")


if __name__ == "__main__":
    main_cli()
