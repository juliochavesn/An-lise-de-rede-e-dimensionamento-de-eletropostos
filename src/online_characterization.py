"""Caracterização, não hosting capacity. Sem chamadas ao motor elétrico/AMPL."""
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime

CONT_PACKAGE = "indicadores-coletivos-de-continuidade-dec-e-fec"
TARIFF_PACKAGE = "tarifas-distribuidoras-energia-eletrica"
CONT_FIELDS = ["SigAgente", "NumCNPJ", "IdeConjUndConsumidoras", "DscConjUndConsumidoras",
               "SigIndicador", "AnoIndice", "NumPeriodoIndice", "VlrIndiceEnviado", "DatGeracaoConjuntoDados"]
TARIFF_FIELDS = ["SigAgente", "NumCNPJDistribuidora", "DatInicioVigencia", "DatFimVigencia",
                 "DscBaseTarifaria", "DscSubGrupo", "DscModalidadeTarifaria", "DscClasse", "DscSubClasse",
                 "DscDetalhe", "NomPostoTarifario", "DscUnidadeTerciaria", "SigAgenteAcessante", "VlrTUSD", "VlrTE",
                 "DscREH", "DatGeracaoConjuntoDados"]


def numeric(value):
    try:
        text = str(value).strip()
        # ANEEL decimal comma; optional grouped thousands only with a comma.
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        number = float(text)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def nonnegative(value):
    n = numeric(value)
    return n if n is not None and n >= 0 else None


def reference_date(row, description=""):
    value = str(row.get("DATA_BASE") or "")
    for fmt in ("%d%b%Y:%H:%M:%S.%f", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            # API may use seven fractional digits, Python supports six.
            trimmed = re.sub(r"(\.\d{6})\d+$", r"\1", value) if "%H" in fmt else value[:10]
            parsed = datetime.strptime(trimmed, fmt).date()
            return parsed.isoformat(), "campo DATA_BASE"
        except ValueError:
            pass
    match = re.search(r"Posição\s+em\s+(\d{2}/\d{2}/\d{4})", description, flags=re.I)
    if match and not value:
        try:
            return datetime.strptime(match[1], "%d/%m/%Y").date().isoformat(), "descrição do recurso ANEEL (não campo individual)"
        except ValueError:
            pass
    return None, "referência ausente ou inválida"


def monthly_characterization(consumers):
    grouped = defaultdict(list)
    for row in consumers:
        # Never mix distributors, circuits, UCMT/UCAT, reference dates or status.
        key = (str(row.get("DIST") or "—"), row.get("kind", "—"), row.get("reference_date"),
               str(row.get("CTMT") or row.get("CTAT") or "—"), str(row.get("SIT_ATIV") or "não informado"))
        grouped[key].append(row)
    result = []
    for (dist, kind, ref, circuit, status), rows in sorted(grouped.items(), key=lambda kv: str(kv[0])):
        months = []
        for month in range(1, 13):
            suffix = f"{month:02d}"
            energy, demand, peak, offpeak, dic, fic = [], [], [], [], [], []
            inconsistent = 0
            for row in rows:
                if kind == "UCAT":
                    ep, ef = nonnegative(row.get("ENE_P_" + suffix)), nonnegative(row.get("ENE_F_" + suffix))
                    e = ep + ef if ep is not None and ef is not None else None
                    dp, df = nonnegative(row.get("DEM_P_" + suffix)), nonnegative(row.get("DEM_F_" + suffix))
                    if dp is not None: peak.append(dp)
                    if df is not None: offpeak.append(df)
                    d = max(dp, df) if dp is not None and df is not None else None
                else:
                    e, d = nonnegative(row.get("ENE_" + suffix)), nonnegative(row.get("DEM_" + suffix))
                if e is not None: energy.append(e)
                if d is not None: demand.append(d)
                if e is not None and e > 0 and d == 0: inconsistent += 1
                for prefix, values in (("DIC_", dic), ("FIC_", fic)):
                    val = nonnegative(row.get(prefix + suffix))
                    if val is not None: values.append(val)
            months.append({"month": month, "energy_kwh_reported": sum(energy) if energy else None,
                           "energy_reported_count": len(energy), "energy_zero_count": energy.count(0),
                           "demand_max_individual_kw": max(demand) if demand else None,
                           "demand_reported_count": len(demand), "demand_zero_count": demand.count(0),
                           "demand_peak_max_individual_kw": max(peak) if peak else None,
                           "demand_offpeak_max_individual_kw": max(offpeak) if offpeak else None,
                           "dic_max_individual_h": max(dic) if dic else None, "dic_reported_count": len(dic),
                           "fic_max_individual": max(fic) if fic else None, "fic_reported_count": len(fic),
                           "positive_energy_zero_demand_count": inconsistent})
        contracts = [nonnegative(r.get("DEM_CONT")) for r in rows]
        contracts = [n for n in contracts if n is not None]
        result.append({"distributor_id": dist, "kind": kind, "reference_date": ref, "circuit": circuit,
                       "registration_status": status, "consumer_count": len(rows), "months": months,
                       "contracted_demand_max_individual_kw": max(contracts) if contracts else None,
                       "contracted_demand_reported_count": len(contracts),
                       "annual_energy_complete": all(m["energy_reported_count"] == len(rows) for m in months),
                       "annual_energy_kwh_reported": sum(m["energy_kwh_reported"] for m in months if m["energy_kwh_reported"] is not None) if any(m["energy_kwh_reported"] is not None for m in months) else None})
    return result


def discover(client, package, resource_name):
    data, source = client.action("package_show", {"id": package}, ttl=86400)
    matches = [r for r in data.get("resources", []) if r.get("name") == resource_name and r.get("datastore_active")]
    if len(matches) != 1:
        raise RuntimeError(f"Recurso DataStore único não encontrado: {resource_name}.")
    return matches[0], source


def search_pages(client, resource, filters, fields, sort="_id asc", maximum=3000):
    schema, schema_source = client.action("datastore_search", {"resource_id": resource["id"], "limit": 0})
    if not (set(fields) | {"_id"}).issubset({f["id"] for f in schema.get("fields", [])}):
        raise ValueError("Esquema ANEEL alterado: campos necessários ausentes.")
    rows, sources, seen, total = [], [schema_source], set(), None
    while len(rows) < maximum:
        data, source = client.action("datastore_search", {"resource_id": resource["id"],
            "filters": json.dumps(filters), "fields": ",".join(["_id"] + fields), "sort": sort,
            "limit": min(1000, maximum - len(rows)), "offset": len(rows)})
        batch = data.get("records")
        if not isinstance(batch, list) or not isinstance(data.get("total"), int):
            raise ValueError("Resposta ANEEL sem registros/contagem válidos.")
        if total is not None and total != data["total"]:
            raise RuntimeError("Base alterada durante a paginação; atualize a consulta.")
        total = data["total"]
        if not batch and len(rows) < total:
            raise RuntimeError("Paginação interrompida; resultado não pode ser considerado completo.")
        sources.append(source)
        for row in batch:
            if row.get("_id") is None or row["_id"] in seen:
                raise RuntimeError("Paginação com registros repetidos ou sem identificador.")
            seen.add(row["_id"])
            rows.append({field: row.get(field) for field in fields})
        if len(rows) >= total:
            break
    return {"records": rows, "sources": sources, "total": total,
            "status": "partial" if len(rows) < total else "ok", "resource_id": resource["id"]}


def cnpj(value):
    value = re.sub(r"[./\-\s]", "", str(value or ""))
    return value.zfill(14) if value.isdigit() and 1 <= len(value) <= 14 else None


def continuity(client, consumers):
    # Up to ten nearby declared sets, no invented concession/distributor match.
    keys = []
    for row in sorted(consumers, key=lambda r: r.get("distance_m", float("inf"))):
        conj = str(row.get("CONJ") or "").strip()
        ref = row.get("reference_date")
        if conj.isdigit() and int(conj) > 0 and ref:
            key = (str(row.get("DIST")), str(int(conj)), int(ref[:4]))
            if key not in keys: keys.append(key)
    chosen = keys[:10]
    empty = {"status": "unavailable", "records": [], "sources": [], "candidates": [], "query_sets": chosen,
             "omitted_set_count": max(0, len(keys) - 10), "association": "Candidato por CONJ/ano; equivalência DIST–CNPJ e conexão física no ponto não homologadas."}
    if not chosen:
        return dict(empty, note="Sem CONJ e referência válidos nos consumidores retornados.")
    resource, source = discover(client, CONT_PACKAGE, "indicadores-continuidade-coletivos-2020-2029")
    years = sorted({year - n for _, _, year in chosen for n in range(3) if year - n >= 2020})
    data = search_pages(client, resource, {"IdeConjUndConsumidoras": sorted({k[1] for k in chosen}),
        "AnoIndice": years, "SigIndicador": ["DEC", "FEC"]}, CONT_FIELDS)
    records, candidates = [], {}
    for row in data["records"]:
        set_id = str(row.get("IdeConjUndConsumidoras"))
        year, period = numeric(row.get("AnoIndice")), numeric(row.get("NumPeriodoIndice"))
        if year is None or period is None or year != int(year) or period != int(period): continue
        matched = [k for k in chosen if k[1] == set_id and k[2] - 2 <= year <= k[2]]
        identity = cnpj(row.get("NumCNPJ"))
        if not matched or not identity or row.get("SigIndicador") not in ("DEC", "FEC"): continue
        records.append(dict(row, cnpj=identity, year=int(year), period=int(period),
                            value=nonnegative(row.get("VlrIndiceEnviado"))))
        # Tariff candidate only if found in the UC's own reference year.
        same_year = [k for k in matched if k[2] == year]
        if same_year:
            candidates[(identity, str(row.get("SigAgente")))] = {"cnpj": identity, "agent": str(row.get("SigAgente")),
                "association": empty["association"]}
    return dict(empty, status="partial" if data["status"] == "partial" or len(keys) > 10 else "ok",
                records=records, candidates=list(candidates.values()), sources=[source] + data["sources"],
                total=data["total"], note="DEC/FEC do conjunto, não da coordenada. Períodos 1–12 são apresentados separadamente de outros períodos; não há soma automática nem inferência de autonomia BESS.")


def tariff_rows(records, on_date, subgroup):
    accepted, invalid_dates = [], 0
    for row in records:
        try:
            start = date.fromisoformat(str(row.get("DatInicioVigencia"))[:10])
            end = date.fromisoformat(str(row.get("DatFimVigencia"))[:10])
            if end < start: raise ValueError
        except ValueError:
            invalid_dates += 1
            continue
        if not start <= on_date <= end or row.get("DscSubGrupo") != subgroup or row.get("DscBaseTarifaria") != "Tarifa de Aplicação":
            continue
        te, tusd = numeric(row.get("VlrTE")), numeric(row.get("VlrTUSD"))
        unit = str(row.get("DscUnidadeTerciaria") or "")
        accepted.append(dict(row, te=te, tusd=tusd, unit="R$/" + unit,
            energy_te_plus_tusd_brl_kwh=(te + tusd) / 1000 if unit == "MWh" and te is not None and tusd is not None else None))
    return accepted, invalid_dates


def tariffs(client, candidates, subgroup="A4", on_date=None):
    reference = date.fromisoformat(on_date) if isinstance(on_date, str) else (on_date or date.today())
    if subgroup not in ("A1", "A2", "A3", "A3a", "A4", "AS", "B1", "B2", "B3", "B4"):
        raise ValueError("Subgrupo tarifário não reconhecido.")
    identifiers = sorted({r["cnpj"] for r in candidates if cnpj(r.get("cnpj"))})
    result = {"status": "unavailable", "records": [], "sources": [], "subgroup": subgroup,
              "on_date": reference.isoformat(), "candidate_cnpjs": identifiers,
              "note": "Referência tarifária por CNPJ candidato. Não é seleção automática da tarifa do eletroposto nem atualização da otimização. TE+TUSD não representa a fatura completa; confirme tributos, bandeiras e demais condições."}
    if not identifiers:
        return result
    resource, source = discover(client, TARIFF_PACKAGE, "tarifas-homologadas-distribuidoras-energia-eletrica.csv")
    data = search_pages(client, resource, {"NumCNPJDistribuidora": identifiers, "DscSubGrupo": subgroup,
        "DscBaseTarifaria": "Tarifa de Aplicação"}, TARIFF_FIELDS, sort="DatInicioVigencia desc,_id asc")
    # Defensive post-filter: never accept an unexpected distributor from the API.
    raw = [r for r in data["records"] if cnpj(r.get("NumCNPJDistribuidora")) in identifiers]
    rows, invalid = tariff_rows(raw, reference, subgroup)
    return dict(result, records=rows, sources=[source] + data["sources"], total=data["total"],
                invalid_dates=invalid, status="partial" if invalid or data["status"] == "partial" else "ok")


def enrich(client, consumers, subgroup="A4", on_date=None):
    result = {"monthly": monthly_characterization(consumers), "warnings": []}
    try:
        result["continuity"] = continuity(client, consumers)
    except Exception as exc:
        result["continuity"] = {"status": "error", "records": [], "candidates": [], "sources": [], "note": str(exc)}
        result["warnings"].append("Continuidade: " + str(exc))
    try:
        result["tariffs"] = tariffs(client, result["continuity"]["candidates"], subgroup, on_date)
    except Exception as exc:
        result["tariffs"] = {"status": "error", "records": [], "sources": [], "subgroup": subgroup, "on_date": str(on_date or date.today()), "note": str(exc)}
        result["warnings"].append("Tarifas: " + str(exc))
    return result
