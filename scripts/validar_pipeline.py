#!/usr/bin/env python3
"""
Validador automático do pipeline de boletins.

Roda o pipeline end-to-end com áudio de teste e gera relatório de qualidade
em JSON para baseline e comparação futura com áudio de produção.
"""
import argparse
import json
import sys
from pathlib import Path

# Adiciona o diretório raiz do projeto ao path para importar o pacote 'app'
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.pipeline import PipelineBoletins, PipelineConfig


def validar_pipeline(
    audio_input: str,
    output_dir: str = "output_validacao",
    assets_dir: str | None = None,
    pular_segmentacao: bool = True,
    pular_tratamento: bool = False,
    modelo: str = "tiny",
    lufs: float = -16.0,
    noise_strength: float = 0.5,
    limiar: float = 0.5,
) -> dict:
    """
    Executa pipeline completo e retorna relatório de validação.
    """
    config = PipelineConfig(
        segmentar=not pular_segmentacao,
        num_boletins=5,
        tratar_audio=not pular_tratamento,
        tratamento_config=None,  # será sobrescrito abaixo
        editar=True,
        edicao_config=None,  # será sobrescrito
        montar=True,
        montagem_config=None,  # será sobrescrito
        output_dir=output_dir,
        manter_intermediarios=True,
        verbose=False,
    )

    # Configurações detalhadas
    from app.tratamento_audio import TratamentoConfig
    from app.edicao_boletins import EdicaoConfig
    from app.montagem_boletins import MontagemConfig, AssetsConfig

    config.tratamento_config = TratamentoConfig(
        target_lufs=lufs,
        noise_reduction_strength=noise_strength,
    )

    config.edicao_config = EdicaoConfig(
        modelo_whisper=modelo,
        limiar_similaridade=limiar,
    )

    if assets_dir:
        config.montagem_config = MontagemConfig(
            assets=AssetsConfig(
                abertura=f"{assets_dir}/VHT_ABERTURA_BOLETIM.mp3",
                passagem=f"{assets_dir}/VHT_PASSAGEM_BOLETIM.mp3",
                encerramento=f"{assets_dir}/VHT_ENCERRAMENTO_BOLETIM.mp3",
            ),
            target_lufs=lufs,
        )
    else:
        config.montagem_config = MontagemConfig(target_lufs=lufs)

    pipeline = PipelineBoletins(config)
    resultado = pipeline.executar(audio_input, output_dir)

    # Extrair métricas de auditoria
    auditorias = []
    for etapa in resultado.etapas:
        if etapa.get("nome", "").startswith("auditoria"):
            auditorias.append(etapa.get("detalhes", {}))

    # Resumo de qualidade
    boletins_final = resultado.boletins_gerados
    tem_auditoria_aviso = any(
        a.get("status") == "aviso" for a in auditorias
    )
    tem_auditoria_ok = any(
        a.get("status") == "ok" for a in auditorias
    )

    relatorio = {
        "data_validacao": Path(output_dir).exists() and (
            Path(output_dir) / "pipeline_log.json"
        ).exists()
        and json.loads(
            open(Path(output_dir) / "pipeline_log.json", encoding="utf-8").read()
        ).get("fim", "")
        or "",
        "audio_entrada": str(audio_input),
        "output_dir": output_dir,
        "status_pipeline": resultado.status,
        "boletins_gerados": len(boletins_final),
        "boletins_caminhos": boletins_final,
        "etapas_status": [
            {"nome": e.get("nome", ""), "status": e.get("status", "")}
            for e in resultado.etapas
        ],
        "auditorias": auditorias,
        "tem_problemas_auditoria": tem_auditoria_aviso,
        "tem_auditorias_ok": tem_auditoria_ok,
        "erros": resultado.erros,
        "resumo": (
            "PASSO" if resultado.status == "parcial"
            else "OK" if resultado.status == "ok"
            else "FALHA"
        ),
    }

    return relatorio


def main():
    parser = argparse.ArgumentParser(
        description="Valida o pipeline de boletins com áudio de teste"
    )
    parser.add_argument(
        "audio",
        nargs="?",
        default="test_audio.wav",
        help="Caminho do áudio de teste (padrão: test_audio.wav)",
    )
    parser.add_argument(
        "-o", "--output",
        default="output_validacao",
        help="Diretório de saída (padrão: output_validacao)",
    )
    parser.add_argument(
        "--assets-dir",
        help="Diretório dos assets de vinheta (opcional)",
    )
    parser.add_argument(
        "--rodar-tratamento",
        action="store_true",
        help="Executa tratamento de áudio (ruído, respiração, LUFS)",
    )
    parser.add_argument(
        "--modelo",
        default="tiny",
        choices=["tiny", "base", "small"],
        help="Modelo Whisper",
    )
    parser.add_argument(
        "--lufs",
        type=float,
        default=-16.0,
        help="Target LUFS",
    )
    parser.add_argument(
        "--limiar",
        type=float,
        default=0.5,
        help="Limiar de similaridade para repetições",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime relatório em JSON (padrão: print legível)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Log detalhado",
    )

    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"ERRO: áudio não encontrado: {audio_path}", file=sys.stderr)
        sys.exit(1)

    relatorio = validar_pipeline(
        str(audio_path),
        output_dir=args.output,
        assets_dir=args.assets_dir,
        pular_tratamento=not args.rodar_tratamento,
        modelo=args.modelo,
        lufs=args.lufs,
        limiar=args.limiar,
    )

    if args.json:
        print(json.dumps(relatorio, indent=2, ensure_ascii=False))
    else:
        # Print legível
        print("=" * 60)
        print("RELATÓRIO DE VALIDAÇÃO DO PIPELINE")
        print("=" * 60)
        print(f"Áudio: {relatorio['audio_entrada']}")
        print(f"Status: {relatorio['status_pipeline'].upper()}")
        print(f"Boletins gerados: {relatorio['boletins_gerados']}")
        print()
        print("Etapas:")
        for e in relatorio["etapas_status"]:
            icon = "✓" if e["status"] in ("ok", "sucesso") else "⚠" if e["status"] in ("aviso", "parcial") else "✗"
            print(f"  {icon} {e['nome']}: {e['status']}")
        print()
        if relatorio["auditorias"]:
            print("Auditorias:")
            for a in relatorio["auditorias"]:
                status = a.get("status", "?")
                problemas = a.get("problemas", [])
                medidas = a.get("medidas", {})
                icon = "✓" if status == "ok" else "⚠"
                print(f"  {icon} status: {status}")
                if problemas:
                    for p in problemas:
                        print(f"      - {p}")
                if medidas:
                    print(f"      medidas: {json.dumps(medidas, indent=6, ensure_ascii=False)}")
        print()
        if relatorio["erros"]:
            print(f"Erros ({len(relatorio['erros'])}):")
            for e in relatorio["erros"]:
                print(f"  ✗ {e}")
        print()
        print(f"Resumo: {relatorio['resumo']}")
        print("=" * 60)

    # Retorna código de saída baseado no status
    if relatorio["status_pipeline"] == "erro":
        sys.exit(2)
    elif relatorio["tem_problemas_auditoria"]:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
