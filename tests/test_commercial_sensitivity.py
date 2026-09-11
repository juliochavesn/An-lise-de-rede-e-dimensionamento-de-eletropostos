from main import build_relative_values


def test_relative_sensitivity_tracks_reference_price():
    settings = {
        "factors": [0.75, 0.90, 1.10, 1.25],
        "include_base": True,
    }

    cases = build_relative_values(2.00, settings)

    assert cases == [
        (0.75, 1.50),
        (0.9, 1.80),
        (1.0, 2.00),
        (1.1, 2.20),
        (1.25, 2.50),
    ]
