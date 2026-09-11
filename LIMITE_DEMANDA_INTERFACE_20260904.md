# Limite de demanda contratada na interface

Backup: backups/pre_limite_demanda_interface_20260904.tar.gz.

Na análise detalhada BDGD, a opção "Limitar demanda contratada" fica desmarcada por padrão. Desmarcada, a execução usa limit_source=bdgd, sem teto comercial imposto pelo usuário. Marcada, exige um teto positivo em kW e usa limit_source=minimum: o limite de importação é o menor entre o perfil BDGD e o teto; o contrato otimizado também não pode exceder o teto. O teto é máximo, não valor fixo. Não altera a configuração permanente de limit_source nem remove restrições físicas.

O subprocesso recebe explicitamente fonte e teto por execução, sem herdar teto anterior no modo livre. A interface não aceita fallback manual em caso de falha da análise BDGD. Os parâmetros são arquivados em simulation_inputs.json na pasta exclusiva da execução.

Resultados incluem energia atendida, fração atendida, energia expirada, pendência final e custo de demanda. A comparação conserva até 10 execuções na sessão e filtra entradas comparáveis. Pode ser baixada em CSV. Cada caso redimensiona os equipamentos; não representa operação de FV/BESS fixos. O histórico da tela é de sessão; os arquivos de cada execução permanecem no disco.

O modelo continua lexicográfico: máximo atendimento, mínima espera agregada e mínimo custo. Logo, um contrato alto para poucas horas não é necessariamente erro de solução: decorre da prioridade do atendimento. O controle permite explorar esse compromisso sem alterar os objetivos. A espera é agregada por energia, não fila individual de veículos. Um teto muito baixo pode inviabilizar a carga local obrigatória.

Validação: 102 testes automatizados, incluindo interação da interface, comparação, transporte e persistência dos parâmetros e semântica dos limites. Ensaio controlado AMPL/HiGHS sem nova consulta BDGD: pico breve de recarga, contrato livre de 170 kW versus teto de 80 kW; ambos atenderam aproximadamente 850 kWh, com maior espera no caso limitado. Não são resultados de um ponto real.

Um ensaio com ruído numérico revelou falsa inviabilidade no presolve por diferenças da ordem de 1e-15. Foi explicitada presolve_eps=1e-9 no AMPL para tratar arredondamento; os limites e as prioridades físicas não foram relaxados deliberadamente.
