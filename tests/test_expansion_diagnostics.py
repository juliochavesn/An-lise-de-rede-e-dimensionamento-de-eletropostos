from src.expansion_diagnostics import analyze_expansion_need


def test_expansion_and_storage_screening():
    data = {
        "time_index": range(4), "dt_h": 1.0,
        "grid_limit_kw": {0: 10, 1: 0, 2: 0, 3: 10},
        "local_load_kw": {0: 5, 1: 6, 2: 8, 3: 5},
        "request_kw": {0: 3, 1: 4, 2: 4, 3: 3},
    }
    limits = {
        "bess_eta_dis": 0.8, "bess_soc_min_frac": 0.1,
        "bess_soc_max_frac": 0.9, "bess_e_max_kwh": 10,
    }
    result = analyze_expansion_need(data, limits)
    assert result["local_load_case"]["reinforcement_to_eliminate_deficit_kw"] == 8
    assert result["full_instantaneous_demand_case"]["reinforcement_to_eliminate_deficit_kw"] == 12
    assert result["storage_screening"]["longest_zero_residual_hours"] == 2
    assert result["storage_screening"]["stored_energy_required_kwh"] == 17.5
    assert result["storage_screening"]["indicative_nominal_bess_required_kwh"] == 21.875
    assert result["improved_local_support_case"]["remaining_local_deficit_intervals"] == 0
