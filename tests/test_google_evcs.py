from src.google_evcs import merge_station_sources


def _row(source, name, lat, lon, connections=None):
    return {
        "id": source, "name": name, "latitude": lat, "longitude": lon,
        "distance_m": 10.0, "connections": connections or [],
        "number_of_points": None, "address": "", "sources": [source],
    }


def test_cross_source_duplicates_are_merged_and_technical_data_is_preserved():
    ocm = _row(
        "Open Charge Map", "Volvo Campinas", -22.9, -47.05,
        [{"connector": "CCS", "power_kw": 50, "quantity": 1, "current": "DC"}],
    )
    google = _row("Google Places", "Volvo Estação de Carregamento", -22.9001, -47.0501)
    google.update(
        google_place_id="abc", url="https://maps.google.com/", maximum_power_kw=60,
        estimated_total_power_kw=60,
    )
    rows, duplicates = merge_station_sources([ocm], [google])
    assert duplicates == 1 and len(rows) == 1
    assert rows[0]["sources"] == ["Open Charge Map", "Google Places"]
    assert rows[0]["connections"][0]["power_kw"] == 50
    assert rows[0]["maximum_power_kw"] == 60


def test_distant_or_unrelated_google_station_is_not_merged():
    ocm = _row("Open Charge Map", "Posto A", -22.9, -47.05)
    google = _row("Google Places", "Posto B", -22.91, -47.06)
    rows, duplicates = merge_station_sources([ocm], [google])
    assert duplicates == 0 and len(rows) == 2


def test_only_one_google_record_can_merge_into_each_ocm_record():
    ocm = _row("Open Charge Map", "Shopping Campinas", -22.9, -47.05)
    google_a = _row("Google Places A", "Carregador A", -22.9, -47.05)
    google_b = _row("Google Places B", "Carregador B", -22.90001, -47.05001)
    google_a.update(google_place_id="a", url="a")
    google_b.update(google_place_id="b", url="b")
    rows, duplicates = merge_station_sources([ocm], [google_a, google_b])
    assert duplicates == 1 and len(rows) == 2
