"""Regras comuns de qualidade cadastral BDGD.

SITCONT é situação CONTÁBIL, não SIT_ATIV. AT2 não existe no campo;
SF, NIM e BOP representam bens operacionais apesar da situação contábil.
Referência: ANEEL, Manual BDGD, seção 4.4.1 (CP 041/2020).
Código 0/desconhecido não autoriza inferir operação.
"""

OPERATIONAL_ACCOUNTING_CODES = frozenset({"AT1", "SF", "NIM", "BOP", "COM"})


def local_utm_epsg(latitude, longitude):
    """UTM/WGS84 com hemisfério correto, inclusive no norte do Brasil."""
    import math
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not -80 <= latitude <= 84 or not -180 <= longitude <= 180:
        raise ValueError("Coordenadas fora do domínio UTM.")
    zone = min(60, int((longitude + 180) // 6) + 1)
    return (32700 if latitude < 0 else 32600) + zone


def operational_rows(frame, column):
    if column not in frame:
        return frame
    codes = frame[column].astype(str).str.strip().str.upper()
    allowed = OPERATIONAL_ACCOUNTING_CODES if column == "SITCONT" else {"AT"}
    return frame.loc[codes.isin(allowed)].copy()
