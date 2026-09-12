"""
Testes para o módulo de montagem de boletins.

Testes com áudio + vinhetas reais (quando disponíveis), e mocks para
detectar_pausa_principal / separar_cabeca_off / montagem genérica.
"""
from pathlib import Path
from unittest.mock import patch

import pytest
from pydub import AudioSegment

from app.montagem_boletins import (
    AssetsConfig,
    MontagemConfig,
    detectar_pausa_principal,
    montar_boletim,
    separar_cabeca_off,
)

# =============================================================================
# Helpers
# =============================================================================

def _criar_audio_silencioso(duracao_ms):
    """Cria um AudioSegment de silêncio com duração fixa (ffmpeg real)."""
    return AudioSegment.silent(duration=duracao_ms)


def _criar_assets(tmp_path):
    """Cria arquivos de assets de teste (mp3 de silêncio) e retorna dict com paths."""
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    assets = {}
    for nome in ["abertura.mp3", "passagem.mp3", "encerramento.mp3"]:
        caminho = assets_dir / nome
        AudioSegment.silent(duration=1000).export(str(caminho), format="mp3")
        assets[nome] = caminho
    return assets_dir, assets


# =============================================================================
# Paths para vinhetas reais e áudio de teste (se disponíveis)
# =============================================================================
REAL_VINHETA_DIR = Path(
    "E:/02_Projetos_Trabalho/Projetos_Ativos/DIVISOR/assets/vinhetas/boletim"
)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_AUDIO_PATH = PROJECT_ROOT / "test_audio.wav"


# =============================================================================
# AssetsConfig
# =============================================================================

def test_assets_config_defaults():
    """AssetsConfig com defaults retorna paths construídos."""
    cfg = AssetsConfig()
    assert "VHT_ABERTURA_BOLETIM.mp3" in cfg.abertura
    assert "VHT_PASSAGEM_BOLETIM.mp3" in cfg.passagem
    assert "VHT_ENCERRAMENTO_BOLETIM.mp3" in cfg.encerramento


def test_assets_config_validate_todos_existentes(tmp_path):
    """validate() retorna lista vazia quando todos os assets existem."""
    _, assets = _criar_assets(tmp_path)
    cfg = AssetsConfig(
        abertura=str(assets["abertura.mp3"]),
        passagem=str(assets["passagem.mp3"]),
        encerramento=str(assets["encerramento.mp3"]),
    )
    errors = cfg.validate()
    assert errors == []


def test_assets_config_validate_falta_alguns(tmp_path):
    """validate() retorna erros quando alguns assets faltam."""
    _, assets = _criar_assets(tmp_path)
    (assets["passagem.mp3"]).unlink()
    (assets["encerramento.mp3"]).unlink()

    cfg = AssetsConfig(
        abertura=str(assets["abertura.mp3"]),
        passagem=str(assets["passagem.mp3"]),
        encerramento=str(assets["encerramento.mp3"]),
    )
    errors = cfg.validate()
    assert len(errors) == 2
    assert "passagem" in errors[0]


# =============================================================================
# Real assets fixture (quando disponíveis)
# =============================================================================

@pytest.fixture
def real_assets():
    """
    Retorna dict com paths das vinhetas reais (se disponíveis), ou None.
    """
    if not REAL_VINHETA_DIR.exists():
        return None

    abertura = REAL_VINHETA_DIR / "VHT_ABERTURA_BOLETIM.mp3"
    passagem = REAL_VINHETA_DIR / "VHT_PASSAGEM_BOLETIM.mp3"
    encerramento = REAL_VINHETA_DIR / "VHT_ENCERRAMENTO_BOLETIM.mp3"

    if not abertura.exists() or not passagem.exists() or not encerramento.exists():
        return None

    return {
        "abertura": str(abertura),
        "passagem": str(passagem),
        "encerramento": str(encerramento),
    }


@pytest.fixture
def real_test_audio():
    """
    Retorna path do áudio de teste real (test_audio.wav), ou None.
    """
    if not TEST_AUDIO_PATH.exists():
        return None
    return str(TEST_AUDIO_PATH)


# =============================================================================
# detectar_pausa_principal
# =============================================================================

def test_detecta_pausa():
    """
    detectar_pausa_principal encontra pausa quando há dois blocos de fala
    separados por silêncio longo nos primeiros 30%.
    """
    audio = _criar_audio_silencioso(10000)
    with patch("pydub.silence.detect_nonsilent", return_value=[(0, 2000), (3000, 10000)]):
        pausa = detectar_pausa_principal(audio, threshold_db=-35, min_pausa_ms=500)
        assert pausa == 2000


def test_detecta_pausa_sem_silêncio_longo():
    """detectar_pausa_principal retorna None se pausa for curta demais."""
    audio = _criar_audio_silencioso(5000)
    with patch("pydub.silence.detect_nonsilent", return_value=[(0, 2300), (2500, 5000)]):
        pausa = detectar_pausa_principal(audio, threshold_db=-35, min_pausa_ms=500)
        assert pausa is None


def test_detecta_pausa_sem_segundo_bloco():
    """detectar_pausa_principal retorna None com apenas um bloco de fala."""
    audio = _criar_audio_silencioso(5000)
    with patch("pydub.silence.detect_nonsilent", return_value=[(0, 5000)]):
        pausa = detectar_pausa_principal(audio, threshold_db=-35, min_pausa_ms=500)
        assert pausa is None


def test_detecta_pausa_limita_busca_a_30_pct():
    """detectar_pausa_principal só busca nos primeiros 30% do áudio."""
    audio = _criar_audio_silencioso(10000)
    with patch("pydub.silence.detect_nonsilent", return_value=[(7000, 10000)]):
        pausa = detectar_pausa_principal(audio, threshold_db=-35, min_pausa_ms=500)
        assert pausa is None


# =============================================================================
# separar_cabeca_off
# =============================================================================

def test_separar_cabeca_off_com_pausa():
    """separar_cabeca_off separa na pausa detectada."""
    audio = _criar_audio_silencioso(10000)
    cabeca, off = separar_cabeca_off(audio, pausa_ms=3000)
    assert len(cabeca) == 3000
    assert len(off) == 7000


def test_separar_cabeca_off_sem_pausa():
    """separar_cabeca_off divide em 1/3 quando não há pausa."""
    audio = _criar_audio_silencioso(9000)
    cabeca, off = separar_cabeca_off(audio, pausa_ms=None)
    assert len(cabeca) == 3000
    assert len(off) == 6000


def test_separar_cabeca_off_auto_detecta():
    """separar_cabeca_off com pausa=None detecta automaticamente."""
    audio = _criar_audio_silencioso(12000)
    with patch("app.montagem_boletins.detectar_pausa_principal", return_value=4000):
        cabeca, off = separar_cabeca_off(audio, pausa_ms=None)
        assert len(cabeca) == 4000
        assert len(off) == 8000


# =============================================================================
# montar_boletim
# =============================================================================

def test_montar_boletim_erro_assets_faltando(tmp_path):
    """montar_boletim falha se algum asset obrigatório faltar."""
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    AudioSegment.silent(duration=100).export(str(assets_dir / "passagem.mp3"), format="mp3")
    AudioSegment.silent(duration=100).export(str(assets_dir / "encerramento.mp3"), format="mp3")

    audio_input = tmp_path / "audio_editado.mp3"
    AudioSegment.silent(duration=5000).export(str(audio_input), format="mp3")

    cfg = MontagemConfig(
        assets=AssetsConfig(
            abertura=str(assets_dir / "abertura.mp3"),  # não existe
            passagem=str(assets_dir / "passagem.mp3"),
            encerramento=str(assets_dir / "encerramento.mp3"),
        )
    )

    with pytest.raises(FileNotFoundError, match="Assets faltando"):
        montar_boletim(str(audio_input), str(tmp_path / "saida.mp3"), config=cfg)


def test_montar_boletim_erro_audio_faltando(tmp_path):
    """montar_boletim falha se áudio de entrada não existir."""
    _, assets = _criar_assets(tmp_path)

    cfg = MontagemConfig(
        assets=AssetsConfig(
            abertura=str(assets["abertura.mp3"]),
            passagem=str(assets["passagem.mp3"]),
            encerramento=str(assets["encerramento.mp3"]),
        )
    )

    with pytest.raises(FileNotFoundError, match="Áudio não encontrado"):
        montar_boletim(str(tmp_path / "inexistente.mp3"), str(tmp_path / "saida.mp3"), config=cfg)


def test_montar_boletim_cria_diretorio_saida(tmp_path):
    """montar_boletim cria o diretório de saída se não existir."""
    _, assets = _criar_assets(tmp_path)

    audio_input = tmp_path / "audio_editado.mp3"
    AudioSegment.silent(duration=5000).export(str(audio_input), format="mp3")

    cfg = MontagemConfig(
        assets=AssetsConfig(
            abertura=str(assets["abertura.mp3"]),
            passagem=str(assets["passagem.mp3"]),
            encerramento=str(assets["encerramento.mp3"]),
        )
    )

    output_dir = tmp_path / "novo" / "subdiretorio"
    output_path = output_dir / "boletim_final.mp3"

    result = montar_boletim(str(audio_input), str(output_path), config=cfg)

    assert output_dir.exists()
    assert result["status"] == "ok"
    assert "output" in result
    assert "duracao_final_s" in result
    assert "estrutura" in result


def test_montagem_config_defaults():
    """MontagemConfig com valores padrão."""
    cfg = MontagemConfig()
    assert cfg.crossfade_ms == 150
    assert cfg.pausa_threshold_ms == 800
    assert cfg.silence_threshold_db == -35
    assert cfg.normalize_final is True
    assert cfg.target_lufs == -16.0
    assert cfg.output_format == "mp3"
    assert cfg.output_bitrate == "192k"
    assert cfg.silence_before_vinheta_ms == 50
    assert cfg.silence_after_vinheta_ms == 100


def test_montagem_config_customizada():
    cfg = MontagemConfig(
        crossfade_ms=300,
        pausa_threshold_ms=1500,
        normalize_final=False,
        target_lufs=-14.0,
    )
    assert cfg.crossfade_ms == 300
    assert cfg.pausa_threshold_ms == 1500
    assert cfg.normalize_final is False
    assert cfg.target_lufs == -14.0


# =============================================================================
# Testes com assets/áudio reais (quando disponíveis)
# =============================================================================

def test_montagem_com_vinheta_real(real_assets, real_test_audio, tmp_path):
    """
    montar_boletim com vinhetas reais + áudio de teste real.
    Valida que crossfade, estrutura e renderização funcionam com arquivos reais.
    """
    if real_assets is None or real_test_audio is None:
        pytest.skip("Assets/vinhetas reais ou áudio de teste não disponíveis")

    audio_input = real_test_audio

    config = MontagemConfig(
        assets=AssetsConfig(
            abertura=real_assets["abertura"],
            passagem=real_assets["passagem"],
            encerramento=real_assets["encerramento"],
        ),
        normalize_final=False,
    )

    result = montar_boletim(audio_input, str(tmp_path / "boletim_real.mp3"), config=config)

    assert result["status"] == "ok"
    assert Path(result["output"]).exists()
    assert result["duracao_final_s"] > 0
    assert result["tamanho_mb"] > 0

    estrutura = result.get("estrutura", {})
    assert estrutura.get("vinheta_abertura_s", 0) > 0
    assert estrutura.get("vinheta_passagem_s", 0) > 0
    assert estrutura.get("vinheta_encerramento_s", 0) > 0
    assert estrutura.get("cabeca_s", 0) > 0
    assert estrutura.get("off_s", 0) > 0


def test_montagem_com_vinheta_real_lufs(real_assets, real_test_audio, tmp_path):
    """
    Variante com normalização LUFS habilitada.
    Pode gerar aviso de loudness fora do target — ok para áudio de teste.
    """
    if real_assets is None or real_test_audio is None:
        pytest.skip("Assets/vinhetas reais ou áudio de teste não disponíveis")

    config = MontagemConfig(
        assets=AssetsConfig(
            abertura=real_assets["abertura"],
            passagem=real_assets["passagem"],
            encerramento=real_assets["encerramento"],
        ),
        normalize_final=True,
        target_lufs=-16.0,
    )

    result = montar_boletim(
        real_test_audio,
        str(tmp_path / "boletim_lufs.mp3"),
        config=config,
    )

    assert result["status"] == "ok"
    assert Path(result["output"]).exists()
    assert result["duracao_final_s"] > 0
    assert "estrutura" in result


def test_auditar_boletim_com_arquivo_real(real_test_audio, tmp_path, real_assets):
    """
    auditar_boletim() encontra arquivo montado com vinhetas reais e
    reporta medidas de LUFS/duração (pode gerar aviso de loudness).
    """
    if real_assets is None or real_test_audio is None:
        pytest.skip("Assets/vinhetas reais ou áudio de teste não disponíveis")

    config = MontagemConfig(
        assets=AssetsConfig(
            abertura=real_assets["abertura"],
            passagem=real_assets["passagem"],
            encerramento=real_assets["encerramento"],
        ),
        normalize_final=True,
        target_lufs=-16.0,
    )

    output_path = tmp_path / "boletim_auditoria.mp3"
    result_montagem = montar_boletim(real_test_audio, str(output_path), config=config)
    assert result_montagem["status"] == "ok"

    from app.montagem_boletins import auditar_boletim

    auditoria = auditar_boletim(str(output_path), limiar=0.5)
    assert auditoria["status"] in ("ok", "aviso")
    assert "medidas" in auditoria
    assert "lufs_integrated" in auditoria["medidas"]
    assert "duracao_s" in auditoria["medidas"]


def test_montagem_imports():
    """Confirma que todos os componentes de montagem importam sem erro."""
    assert AssetsConfig is not None
    assert MontagemConfig is not None
    assert callable(detectar_pausa_principal)
    assert callable(separar_cabeca_off)
    assert callable(montar_boletim)
