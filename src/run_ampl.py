"""
Interface Python para execução do modelo AMPL.

Este módulo usa amplpy para:
- carregar o arquivo .mod;
- carregar o arquivo .dat;
- selecionar o solver;
- resolver o problema;
- coletar variáveis e parâmetros para pós-processamento.
"""

import os

from amplpy import AMPL


_LICENSE_READY = False


def prepare_ampl_runtime(env=None):
    """Ativa, quando configurada, a licença AMPL mantida fora do código."""
    global _LICENSE_READY
    if _LICENSE_READY:
        return
    env = os.environ if env is None else env
    license_uuid = str(env.get("AMPL_LICENSE_UUID", "")).strip()
    if license_uuid:
        try:
            from amplpy import modules
            modules.activate(license_uuid)
        except Exception as error:
            raise RuntimeError(
                "Não foi possível ativar a licença AMPL definida no ambiente. "
                "Confirme o segredo AMPL_LICENSE_UUID e a conectividade do servidor."
            ) from error
    _LICENSE_READY = True


class AmplSolveError(RuntimeError):
    """Erro de solução contendo o status devolvido pelo AMPL."""

    def __init__(self, solve_result, solve_message=None):
        self.solve_result = str(solve_result)
        self.solve_message = (
            str(solve_message) if solve_message is not None else None
        )
        message = (
            "Modelo não resolvido corretamente: "
            f"{self.solve_result}"
        )
        if self.solve_message:
            message += f" ({self.solve_message})"
        super().__init__(message)


def solve_ampl_case(
    model_path,
    data_path,
    solver_name="highs",
    relax_integrality=False,
):
    """
    Resolve um caso de otimização usando AMPL.

    Parâmetros:
    model_path  : caminho para o arquivo .mod;
    data_path   : caminho para o arquivo .dat;
    solver_name : solver AMPL a ser utilizado.

    Retorna:
    ampl : objeto AMPL com solução carregada.
    """

    prepare_ampl_runtime()
    ampl = AMPL()
    # Evita falsa inviabilidade no presolve por arredondamento (ex.: 1e-15)
    # quando importação e limite contratual coincidem. Não é folga física em kW.
    ampl.set_option("presolve_eps", 1e-9)
    ampl.set_option("solver", solver_name)
    if relax_integrality:
        ampl.set_option("relax_integrality", 1)
    ampl.read(str(model_path))
    ampl.read_data(str(data_path))
    if int(ampl.get_value("economic_service_mode")) == 1:
        # Em metas flexíveis, encontra antes o menor déficit tecnicamente
        # possível. Assim, insuficiência da rede produz curtailment mensurado,
        # não uma falsa inviabilidade; depois o custo decide sem piorá-lo.
        if int(ampl.get_value("strict_service_targets")) == 0:
            ampl.eval("objective Service_Target_Shortfall;")
            ampl.solve()
            status = str(ampl.get_value("solve_result"))
            if status != "solved":
                message = ampl.get_value("solve_message")
                ampl.close()
                raise AmplSolveError(status, message)
            shortfall = float(ampl.get_value("Service_Target_Shortfall"))
            ampl.get_parameter("target_shortfall_ceiling_kwh").set(max(0.0, shortfall + 1e-7))
        ampl.eval("objective Total_Cost;")
        ampl.solve()
        status = str(ampl.get_value("solve_result"))
        if status != "solved":
            message = ampl.get_value("solve_message")
            ampl.close()
            raise AmplSolveError(status, message)
        return ampl
    # Etapa 1: encontra o maior atendimento tecnicamente possível
    # para a combinação de tecnologias do cenário.
    ampl.eval("objective EV_Service_Objective;")
    ampl.solve()
    solve_result = str(ampl.get_value("solve_result"))

    if solve_result != "solved":
        try:
            solve_message = ampl.get_value("solve_message")
        except Exception:
            solve_message = None
        ampl.close()
        raise AmplSolveError(solve_result, solve_message)

    maximum_served_energy = float(
        ampl.get_value("EV_Service_Objective")
    )
    ampl.get_parameter(
        "served_energy_quality_floor_kwh"
    ).set(max(0.0, maximum_served_energy - 1e-7))

    # Etapa 2: entre as soluções de atendimento máximo, minimiza
    # o backlog acumulado e, portanto, o tempo total de espera.
    ampl.eval("objective EV_Backlog_Objective;")
    ampl.solve()
    solve_result = str(ampl.get_value("solve_result"))
    if solve_result != "solved":
        try:
            solve_message = ampl.get_value("solve_message")
        except Exception:
            solve_message = None
        ampl.close()
        raise AmplSolveError(solve_result, solve_message)

    minimum_backlog = float(
        ampl.get_value("EV_Backlog_Objective")
    )
    ampl.get_parameter(
        "backlog_quality_ceiling_kwh"
    ).set(max(0.0, minimum_backlog + 1e-7))

    # Etapa 3: minimiza custo sem reduzir o atendimento máximo nem
    # aumentar o menor backlog acumulado encontrado na etapa 2.
    ampl.eval("objective Total_Cost;")
    ampl.solve()
    solve_result = str(ampl.get_value("solve_result"))
    if solve_result != "solved":
        try:
            solve_message = ampl.get_value("solve_message")
        except Exception:
            solve_message = None
        ampl.close()
        raise AmplSolveError(solve_result, solve_message)

    return ampl
