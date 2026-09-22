import pandas as pd

from src.pnl_routes import GTYPE_LABELS, corridor_label, gtype_label, saturation_class


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


def test_official_gtype_dictionary_is_exposed():
    assert gtype_label(1) == "Rodoviário"
    assert gtype_label("2") == "Ferroviário"
    assert gtype_label(12) == "Transbordo portuário"
    assert gtype_label(18) == "Interseção: navegação interior e longo curso"
    assert gtype_label(999) == "Classe modal não documentada (999)"
    assert set(GTYPE_LABELS) == {1, 2, 4, 6, 7, 12, 13, 15, 16, 17, 18}
