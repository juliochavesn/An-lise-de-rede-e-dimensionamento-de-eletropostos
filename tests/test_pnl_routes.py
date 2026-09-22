import pandas as pd

from src.pnl_routes import corridor_label, saturation_class


def test_corridor_label_combines_flags():
    assert corridor_label({
        "d_corredor_domestico": 1,
        "d_corredor_exportacao": 1,
        "d_corredor_integracao": 0,
    }) == "Doméstico + Exportação"
    assert corridor_label({}) == "Não classificado"


def test_saturation_classes_are_explicit():
    assert saturation_class(pd.NA) == "Não informada"
    assert saturation_class(0.59) == "Baixa (<60%)"
    assert saturation_class(0.60) == "Moderada (60–80%)"
    assert saturation_class(0.80) == "Alta (80–100%)"
    assert saturation_class(1.00) == "Crítica (≥100%)"
