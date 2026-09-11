from pathlib import Path

from process_bdgd_cloud import _feeder_column, _safe, _source_for_gdal


def test_safe_partition_name():
    assert _safe("AL/01 A") == "AL_01_A"


def test_feeder_column_priority():
    assert _feeder_column(["COD_ID", "CTMT"]) == "CTMT"
    assert _feeder_column(["COD_ID"]) == "COD_ID"


def test_zip_virtual_path(tmp_path: Path):
    source = tmp_path / "base.gdb.zip"
    source.write_bytes(b"x")
    assert _source_for_gdal(source).startswith("/vsizip/")
