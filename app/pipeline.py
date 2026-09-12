#!/usr/bin/env python3
"""
Pipeline Completo de Produção de Boletins.

Orquestra todas as etapas:
    1. Segmentação (se áudio contém múltiplos boletins)
    2. Tratamento de áudio (normalização, redução de ruído, respiração)
    3. Edição (remoção de erros/repetições)
    4. Montagem (inserção de vinhetas)

Uso:
    from app.pipeline import PipelineBoletins

    pipeline = PipelineBoletins()
    resultado = pipeline.executar("audio_bruto.mp3")
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.edicao_boletins import EdicaoConfig, editar_boletim
from app.montagem_boletins import AssetsConfig, MontagemConfig, montar_boletim
from app.segmentacao_boletins import SegmentacaoConfig, segmentar_audio
from app.tratamento_audio import TratamentoConfig
from app.tratamento_audio import process as processar_audio

logger = logging.getLogger(__name__)


# =============================================================================
# Configuração do Pipeline
# =============================================================================


@dataclass
class PipelineConfig:
    """Configuração completa do pipeline de boletins."""

    # --- Segmentação ---
    segmentar: bool = True
    num_boletins: int = 5
    segmentacao_config: SegmentacaoConfig = field(default_factory=SegmentacaoConfig)

    # --- Tratamento ---
    tratar_audio: bool = True
    tratamento_config: TratamentoConfig = field(default_factory=TratamentoConfig)

    # --- Edição ---
    editar: bool = True
    edicao_config: EdicaoConfig = field(default_factory=EdicaoConfig)

    # --- Montagem ---
    montar: bool = True
    montagem_config: MontagemConfig = field(default_factory=MontagemConfig)

    # --- Geral ---
    output_dir: str = "output_boletins"
    manter_intermediarios: bool = True  # Mantém arquivos de cada etapa
    verbose: bool = False
    prefixo: str = ""  # Prefixo para distinguir sets (ex: "03_SET_", "08_SET_")
    auditoria_auto: bool = True  # Rodar auditoria automática após montagem
    limiar_auditoria: float = 0.5  # Threshold para flag de repetições na auditoria


# =============================================================================
# Resultado do Pipeline
# =============================================================================


@dataclass
class ResultadoPipeline:
    """Resultado da execução do pipeline."""

    status: str = "ok"
    input_audio: str = ""
    etapas: list = field(default_factory=list)
    boletins_gerados: list = field(default_factory=list)
    erros: list = field(default_factory=list)
    inicio: str = field(default_factory=lambda: datetime.now().isoformat())
    fim: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "input": self.input_audio,
            "inicio": self.inicio,
            "fim": self.fim,
            "etapas": self.etapas,
            "boletins_gerados": self.boletins_gerados,
            "erros": self.erros,
        }


# =============================================================================
# Pipeline Principal
# =============================================================================


class PipelineBoletins:
    """
    Pipeline completo de produção de boletins.

    Executa sequencialmente:
    1. Segmentação (detecta B1-B5 no áudio bruto)
    2. Tratamento (normaliza, reduz ruído e respiração)
    3. Edição (remove erros de locução e repetições)
    4. Montagem (insere vinhetas e monta estrutura final)
    """

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig()
        self._setup_logging()

    def _setup_logging(self):
        level = logging.DEBUG if self.config.verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
            force=True,
        )

    def executar(
        self,
        audio_input: str | Path,
        output_dir: str | None = None,
    ) -> ResultadoPipeline:
        """
        Executa o pipeline completo.

        Args:
            audio_input: Caminho do áudio bruto (pode conter múltiplos boletins)
            output_dir: Diretório base de saída (sobrescreve config)

        Returns:
            ResultadoPipeline com status e caminhos dos boletins gerados
        """
        audio_input = Path(audio_input)
        base_dir = Path(output_dir or self.config.output_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        resultado = ResultadoPipeline(input_audio=str(audio_input))

        logger.info("=" * 70)
        logger.info("PIPELINE DE BOLETINS - Iniciando")
        logger.info(f"Input: {audio_input}")
        logger.info(f"Output: {base_dir}")
        logger.info("=" * 70)

        try:
            # ================================================================
            # ETAPA 1: Segmentação
            # ================================================================
            if self.config.segmentar:
                logger.info("\n" + "=" * 50)
                logger.info("ETAPA 1: Segmentação de boletins")
                logger.info("=" * 50)

                seg_dir = base_dir / "01_segmentados"
                seg_config = self.config.segmentacao_config
                seg_config.output_dir = str(seg_dir)

                try:
                    boletins_segmentados = segmentar_audio(
                        str(audio_input),
                        config=seg_config,
                    )

                    resultado.etapas.append(
                        {
                            "nome": "segmentacao",
                            "status": "ok",
                            "arquivos": boletins_segmentados,
                            "total": len(boletins_segmentados),
                        }
                    )

                    arquivos_boletins = [Path(b) for b in boletins_segmentados]

                except Exception as e:
                    logger.error(f"Segmentação falhou: {e}")
                    resultado.erros.append(f"segmentacao: {e}")
                    # Usa o próprio áudio como boletim único
                    arquivos_boletins = [audio_input]
                    resultado.etapas.append(
                        {
                            "nome": "segmentacao",
                            "status": "erro",
                            "erro": str(e),
                        }
                    )
            else:
                arquivos_boletins = [audio_input]

            # ================================================================
            # ETAPA 2+3+4: Para cada boletim: Tratar → Editar → Montar
            # ================================================================
            for i, boletim_path in enumerate(arquivos_boletins, 1):
                logger.info(f"\n{'='*70}")
                logger.info(f"BOLETIM {i}/{len(arquivos_boletins)}: {boletim_path.name}")
                logger.info(f"{'='*70}")

                boletim_nome = f"{self.config.prefixo}{boletim_path.stem}"
                current_file = str(boletim_path)

                # --- ETAPA 2: Tratamento ---
                if self.config.tratar_audio:
                    logger.info("\n--- Tratamento de áudio ---")

                    tratado_path = base_dir / f"{boletim_nome}_tratado.mp3"

                    try:
                        res_tratamento = processar_audio(
                            current_file,
                            str(tratado_path),
                            config=self.config.tratamento_config,
                        )

                        resultado.etapas.append(
                            {
                                "nome": f"tratamento_{boletim_nome}",
                                "status": "ok",
                                "arquivo": str(tratado_path),
                                "detalhes": res_tratamento,
                            }
                        )

                        current_file = str(tratado_path)

                    except Exception as e:
                        logger.error(f"Tratamento falhou: {e}")
                        resultado.erros.append(f"tratamento_{boletim_nome}: {e}")
                        resultado.etapas.append(
                            {
                                "nome": f"tratamento_{boletim_nome}",
                                "status": "erro",
                                "erro": str(e),
                            }
                        )

                # --- ETAPA 3: Edição ---
                if self.config.editar:
                    logger.info("\n--- Edição (remoção de erros) ---")

                    editado_path = base_dir / f"{boletim_nome}_editado.mp3"

                    try:
                        res_edicao = editar_boletim(
                            current_file,
                            str(editado_path),
                            config=self.config.edicao_config,
                        )

                        resultado.etapas.append(
                            {
                                "nome": f"edicao_{boletim_nome}",
                                "status": "ok",
                                "arquivo": str(editado_path),
                                "detalhes": res_edicao,
                            }
                        )

                        current_file = str(editado_path)

                    except Exception as e:
                        logger.error(f"Edição falhou: {e}")
                        resultado.erros.append(f"edicao_{boletim_nome}: {e}")
                        resultado.etapas.append(
                            {
                                "nome": f"edicao_{boletim_nome}",
                                "status": "erro",
                                "erro": str(e),
                            }
                        )

                # --- ETAPA 4: Montagem ---
                if self.config.montar:
                    logger.info("\n--- Montagem com vinhetas ---")

                    montado_path = base_dir / f"{boletim_nome}_FINAL.mp3"

                    try:
                        res_montagem = montar_boletim(
                            current_file,
                            str(montado_path),
                            config=self.config.montagem_config,
                        )

                        resultado.etapas.append(
                            {
                                "nome": f"montagem_{boletim_nome}",
                                "status": "ok",
                                "arquivo": str(montado_path),
                                "detalhes": res_montagem,
                            }
                        )

                        resultado.boletins_gerados.append(str(montado_path))

                    except Exception as e:
                        logger.error(f"Montagem falhou: {e}")
                        resultado.erros.append(f"montagem_{boletim_nome}: {e}")
                        resultado.etapas.append(
                            {
                                "nome": f"montagem_{boletim_nome}",
                                "status": "erro",
                                "erro": str(e),
                            }
                        )

            # ================================================================
            # ETAPA 5: Auditoria automática pós-montagem
            # ================================================================
            if self.config.auditoria_auto and resultado.boletins_gerados:
                logger.info(f"\n{'='*70}")
                logger.info("ETAPA 5: Auditoria de qualidade automática")
                logger.info(f"{'='*70}")

                for boletim_path in resultado.boletins_gerados:
                    boletim_nome = Path(boletim_path).stem
                    logger.info(f"Auditoria: {boletim_nome}")

                    try:
                        from app.montagem_boletins import auditar_boletim

                        res_auditoria = auditar_boletim(
                            boletim_path,
                            limiar=self.config.limiar_auditoria,
                        )
                        resultado.etapas.append(
                            {
                                "nome": f"auditoria_{boletim_nome}",
                                "status": "ok" if res_auditoria.get("status") == "ok" else "aviso",
                                "arquivo": boletim_path,
                                "detalhes": res_auditoria,
                            }
                        )
                        if res_auditoria.get("problemas"):
                            for p in res_auditoria["problemas"]:
                                logger.warning(f"  ⚠ {p}")
                                resultado.erros.append(f"auditoria_{boletim_nome}: {p}")
                        else:
                            logger.info("  ✓ Sem problemas detectados")
                    except Exception as e:
                        logger.error(f"  ✗ Auditoria falhou: {e}")
            # ================================================================
            # Finalização e auditoria automática
            # ================================================================
            if resultado.erros:
                resultado.status = "parcial" if resultado.boletins_gerados else "erro"
            else:
                resultado.status = "ok"

            resultado.fim = datetime.now().isoformat()

            # Salvar log do pipeline
            log_path = base_dir / "pipeline_log.json"
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(resultado.to_dict(), f, indent=2, ensure_ascii=False)

            # Resumo
            logger.info(f"\n{'='*70}")
            logger.info(f"PIPELINE CONCLUÍDO - Status: {resultado.status}")
            logger.info(f"Boletins gerados: {len(resultado.boletins_gerados)}")
            logger.info(f"Erros: {len(resultado.erros)}")
            if resultado.boletins_gerados:
                logger.info("Arquivos finais:")
                for b in resultado.boletins_gerados:
                    logger.info(f"  ✓ {b}")
            logger.info(f"Log: {log_path}")
            logger.info(f"{'='*70}")

        except Exception as e:
            resultado.status = "erro"
            resultado.erros.append(str(e))
            resultado.fim = datetime.now().isoformat()
            logger.error(f"Pipeline falhou: {e}")
            raise

        return resultado


# =============================================================================
# CLI
# =============================================================================


def main_cli():
    import argparse

    parser = argparse.ArgumentParser(description="Pipeline completo de produção de boletins")
    parser.add_argument("audio", help="Caminho do áudio bruto")
    parser.add_argument("-o", "--output", default="output_boletins", help="Diretório de saída")
    parser.add_argument("-n", "--num-boletins", type=int, default=5, help="Número de boletins")
    parser.add_argument("--pular-tratamento", action="store_true", help="Pula tratamento de áudio")
    parser.add_argument("--pular-edicao", action="store_true", help="Pula edição de erros")
    parser.add_argument("--pular-montagem", action="store_true", help="Pula montagem com vinhetas")
    parser.add_argument("--pular-segmentacao", action="store_true", help="Pula segmentação")
    parser.add_argument("--modelo", default="tiny", help="Modelo Whisper")
    parser.add_argument("--lufs", type=float, default=-16.0, help="Target LUFS")
    parser.add_argument("--noise-strength", type=float, default=0.5, help="Redução de ruído (0-1)")
    parser.add_argument("--limiar", type=float, default=0.5, help="Limiar de similaridade (0-1)")
    parser.add_argument("--assets-dir", help="Diretório dos assets")
    parser.add_argument(
        "--manter-intermediarios", action="store_true", help="Mantém arquivos intermediários"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Modo verboso")

    args = parser.parse_args()

    # Configurações
    tratamento_config = TratamentoConfig(
        target_lufs=args.lufs,
        noise_reduction_strength=args.noise_strength,
    )

    edicao_config = EdicaoConfig(
        modelo_whisper=args.modelo,
        limiar_similaridade=args.limiar,
    )

    montagem_config = MontagemConfig(
        target_lufs=args.lufs,
    )

    if args.assets_dir:
        montagem_config.assets = AssetsConfig(
            abertura=f"{args.assets_dir}/VHT_ABERTURA_BOLETIM.mp3",
            passagem=f"{args.assets_dir}/VHT_PASSAGEM_BOLETIM.mp3",
            encerramento=f"{args.assets_dir}/VHT_ENCERRAMENTO_BOLETIM.mp3",
        )

    config = PipelineConfig(
        segmentar=not args.pular_segmentacao,
        num_boletins=args.num_boletins,
        tratar_audio=not args.pular_tratamento,
        tratar_config=tratamento_config,
        editar=not args.pular_edicao,
        edicao_config=edicao_config,
        montar=not args.pular_montagem,
        montagem_config=montagem_config,
        output_dir=args.output,
        manter_intermediarios=args.manter_intermediarios,
        verbose=args.verbose,
    )

    pipeline = PipelineBoletins(config)
    resultado = pipeline.executar(args.audio, args.output)

    print("\n" + "=" * 60)
    print("PIPELINE CONCLUÍDO")
    print("=" * 60)
    print(f"Status: {resultado.status}")
    print(f"Boletins gerados: {len(resultado.boletins_gerados)}")
    for b in resultado.boletins_gerados:
        print(f"  ✓ {b}")
    if resultado.erros:
        print(f"Erros ({len(resultado.erros)}):")
        for e in resultado.erros:
            print(f"  ✗ {e}")


if __name__ == "__main__":
    main_cli()
