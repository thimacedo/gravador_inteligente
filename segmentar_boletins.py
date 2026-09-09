#!/usr/bin/env python3
"""Segmenta audio de boletins em arquivos individuais."""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# Configuracoes
AUDIO_PATH = "C:/Users/THIAGO/AppData/Local/hermes/attachments/06 JUL B1-B5.mp3"
SAIDA_DIR = "boletins_segmentados"
MODELO_WHISPER = "tiny"  # tiny para menos memoria

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    print("=" * 60)
    print("SEGMENTADOR DE BOLETINS - TJRN RADIO")
    print("=" * 60)
    print(f"Audio: {AUDIO_PATH}")
    print(f"Modelo: {MODELO_WHISPER}")
    print()
    
    if not os.path.exists(AUDIO_PATH):
        logger.error(f"Arquivo nao encontrado: {AUDIO_PATH}")
        sys.exit(1)
    
    file_size_mb = os.path.getsize(AUDIO_PATH) / (1024 * 1024)
    logger.info(f"Arquivo: {file_size_mb:.1f} MB")
    
    # Importar
    logger.info("Importando Whisper...")
    import whisper
    
    # Carregar modelo
    logger.info(f"Carregando modelo '{MODELO_WHISPER}'...")
    print("Carregando modelo Whisper tiny...")
    model = whisper.load_model(MODELO_WHISPER)
    logger.info("Modelo carregado")
    
    # Transcrever
    logger.info("Transcrevendo...")
    print("Transcrevendo audio...")
    
    result = model.transcribe(
        AUDIO_PATH,
        language="pt",
        fp16=False,
        verbose=False
    )
    
    transcricao = result["segments"]
    duracao_total = result["segments"][-1]["end"] if result["segments"] else 0
    
    logger.info(f"Transcricao: {len(transcricao)} segmentos, {duracao_total:.1f}s")
    print(f"Transcricao concluida: {len(transcricao)} segmentos")
    
    # Detectar marcadores B1-B5
    print("\nDetectando marcadores...")
    import regex
    padrao = r"\bB(\d{1,2})\b"
    regex_marcador = regex.compile(padrao, regex.IGNORECASE)
    
    marcadores_detectados = {}
    
    for seg in transcricao:
        texto = seg["text"].strip()
        match = regex_marcador.search(texto)
        if match:
            numero = int(match.group(1))
            if numero not in marcadores_detectados:
                marcadores_detectados[numero] = seg["start"]
                print(f"  Marcador B{numero}: {seg['start']:.1f}s")
    
    print(f"\nDetectados: {sorted(marcadores_detectados.keys())}")
    
    # Construir marcadores completos
    print("\nConstruindo limites dos boletins...")
    
    marcadores = []
    
    # B1 no inicio
    marcadores.append({"numero": 1, "inicio": 0.0, "fim": None, "texto": "INICIO"})
    
    for num in range(2, 6):
        if num in marcadores_detectados:
            marcadores.append({
                "numero": num,
                "inicio": marcadores_detectados[num],
                "fim": None,
                "texto": f"Detectado"
            })
        else:
            logger.warning(f"B{num} nao detectado, estimando...")
            if num == 2:
                marcadores.append({"numero": 2, "inicio": 60, "fim": None, "texto": "Estimado"})
            elif num == 3:
                marcadores.append({"numero": 3, "inicio": 160, "fim": None, "texto": "Estimado"})
            elif num == 4:
                marcadores.append({"numero": 4, "inicio": marcadores_detectados.get(4, duracao_total * 0.6), "fim": None, "texto": "Estimado"})
            elif num == 5:
                marcadores.append({"numero": 5, "inicio": duracao_total * 0.8, "fim": None, "texto": "Estimado"})
    
    # Calcular finais
    for i, m in enumerate(marcadores):
        m["fim"] = marcadores[i + 1]["inicio"] if i < len(marcadores) - 1 else duracao_total
        m["duracao"] = m["fim"] - m["inicio"]
    
    # Criar diretorio
    os.makedirs(SAIDA_DIR, exist_ok=True)
    logger.info(f"Diretorio: {SAIDA_DIR}")
    
    # Carregar audio
    from pydub import AudioSegment
    print("Carregando arquivo de audio...")
    audio = AudioSegment.from_file(AUDIO_PATH)
    logger.info(f"Audio carregado: {len(audio)/1000:.1f}s")
    
    # Exportar
    print("\n" + "=" * 60)
    print("EXPORTANDO BOLETINS")
    print("=" * 60)
    
    for m in marcadores:
        numero = m["numero"]
        inicio_ms = int(m["inicio"] * 1000)
        fim_ms = int(m["fim"] * 1000)
        
        print(f"\nBoletim B{numero}:")
        print(f"  Inicio: {m['inicio']:.1f}s")
        print(f"  Fim: {m['fim']:.1f}s")
        print(f"  Duracao: {m['duracao']:.1f}s ({m['duracao']/60:.1f} min)")
        
        segmento = audio[inicio_ms:fim_ms]
        
        nome_arquivo = f"B{numero}.mp3"
        caminho_saida = os.path.join(SAIDA_DIR, nome_arquivo)
        
        segmento.export(caminho_saida, format="mp3")
        
        tamanho_mb = os.path.getsize(caminho_saida) / (1024 * 1024)
        print(f"  Arquivo: {nome_arquivo} ({tamanho_mb:.1f} MB)")
        logger.info(f"B{numero} exportado: {tamanho_mb:.1f} MB")
    
    # Gerar log
    log_data = {
        "data": datetime.now().isoformat(),
        "audio": str(AUDIO_PATH),
        "duracao_total_seg": duracao_total,
        "duracao_total_min": round(duracao_total / 60, 2),
        "modelo": MODELO_WHISPER,
        "total_boletins": len(marcadores),
        "boletins": []
    }
    
    for m in marcadores:
        log_data["boletins"].append({
            "numero": m["numero"],
            "inicio_seg": round(m["inicio"], 2),
            "fim_seg": round(m["fim"], 2),
            "duracao_seg": round(m["duracao"], 2),
            "duracao_min": round(m["duracao"] / 60, 2)
        })
    
    caminho_log = os.path.join(SAIDA_DIR, "log_segmentacao.json")
    with open(caminho_log, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Log salvo: {caminho_log}")
    
    # Resumo final
    print("\n" + "=" * 60)
    print("CONCLUIDO!")
    print("=" * 60)
    print(f"Audio original: 06 JUL B1-B5.mp3 ({file_size_mb:.1f} MB)")
    print(f"Duracao total: {duracao_total:.1f}s ({duracao_total/60:.1f} min)")
    print(f"Boletins: {len(marcadores)}")
    print()
    for m in marcadores:
        print(f"  B{m['numero']}: {m['inicio']:.1f}s - {m['fim']:.1f}s ({m['duracao']:.1f}s)")
    print()
    print("Arquivos gerados:")
    for m in marcadores:
        nome = f"B{m['numero']}.mp3"
        caminho = os.path.join(SAIDA_DIR, nome)
        tamanho_mb = os.path.getsize(caminho) / (1024 * 1024)
        print(f"  {nome}: {tamanho_mb:.1f} MB")
    print(f"\nLog: {caminho_log}")

if __name__ == "__main__":
    main()
