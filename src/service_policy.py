"""Política de atendimento auditável e independente dos limites elétricos."""
import math

def describe_policy(policy=None):
    p = normalize_policy(policy)
    if p["mode"] == "maximum":
        return "Máximo atendimento (referência)"
    period = {"monthly": "mensal", "daily": "diária", "none": "sem proteção adicional"}[p["period"]]
    guarantee = "rígida" if p["strict"] else "preferencial com melhor esforço"
    return (f"Econômico: meta {100*p['target']:g}% ({guarantee}); proteção {period}"
            + (f" {100*p['period_target']:g}%" if p["period"] != "none" else "")
            + f"; não atendimento R$ {p['unserved_penalty']:g}/kWh; espera R$ {p['waiting_penalty']:g}/kWh·h")

def normalize_policy(policy=None):
    p = dict(mode="maximum", target=0.98, period="monthly", period_target=0.95, strict=False,
             unserved_penalty=0.0, waiting_penalty=0.0)
    p.update(policy or {})
    if p["mode"] not in {"maximum", "economic"} or p["period"] not in {"monthly", "daily", "none"}:
        raise ValueError("Modo ou período de atendimento inválido.")
    for k in ("target", "period_target", "unserved_penalty", "waiting_penalty"):
        p[k] = float(p[k])
        if not math.isfinite(p[k]) or p[k] < 0:
            raise ValueError("Metas e penalidades devem ser finitas e não negativas.")
    if p["target"] > 1 or p["period_target"] > 1:
        raise ValueError("Metas devem estar entre 0 e 1.")
    if not isinstance(p["strict"], bool):
        raise ValueError("A opção de meta rígida deve ser booleana.")
    return p

def write_service_parameters(file, data, tariff, delay):
    p = normalize_policy(tariff.get("service_policy"))
    economic = p["mode"] == "economic"
    file.write(f"param economic_service_mode := {int(economic)};\n")
    file.write(f"param strict_service_targets := {int(economic and p['strict'])};\n")
    for name, value in (("service_target", p["target"]), ("period_service_target", p["period_target"]),
                        ("ev_unserved_cost", p["unserved_penalty"]), ("ev_waiting_cost", p["waiting_penalty"])):
        file.write(f"param {name} := {value};\n")
    indices = list(data["time_index"])
    arrivals = indices if economic else []
    file.write("set EA := " + " ".join(map(str, arrivals)) + ";\n")
    file.write("set EV_ARCS := " + " ".join(f"({a},{t})" for i,a in enumerate(arrivals)
        for t in indices[i:min(i+delay,len(indices))]) + ";\n")
    groups = {}
    if economic and p["period"] != "none":
        stamps = data.get("timestamps")
        calendar_groups = {}
        for i,a in enumerate(indices):
            if stamps is not None and stamps[i] is not None:
                key = str(stamps[i])[:10 if p["period"] == "daily" else 7]
                groups[a] = calendar_groups.setdefault(key, len(calendar_groups) + 1)
            else:
                groups[a] = (int(i * data["dt_h"] // 24) + 1 if p["period"] == "daily"
                             else int(data["month_of_t"][a]))
    file.write("set QG := " + " ".join(map(str, sorted(set(groups.values())))) + ";\n")
    if groups:
        file.write("param quality_group :=\n" + "\n".join(f"{a} {g}" for a,g in groups.items()) + "\n;\n")
