"""
Módulo de análise de testes A/B de cashback.
Recebe um CSV com dados diários de grupos de teste,
calcula métricas de negócio, detecta problemas de qualidade,
roda testes estatísticos e gera uma recomendação final
sobre qual variante escalar para 100% do tráfego.
"""

# csv: leitura de arquivos CSV
import csv
# datetime: conversão de strings de data para objetos date
from datetime import datetime
# mean, stdev, median: funções estatísticas básicas (média, desvio padrão, mediana)
from statistics import mean, stdev, median
# scipy.stats: testes estatísticos (t-test de Welch)
from scipy import stats


# ==========================================================================
# PARSING — leitura e normalização dos dados brutos do CSV
# ==========================================================================

def parse_brl(value):
    """
    Converte valores monetários brasileiros (ex: 'R$ 10.273' ou 'R$ 1.234,56')
    para float Python. Necessário porque o CSV usa formato brasileiro com
    ponto como separador de milhar e vírgula como decimal.
    """
    # Remove o símbolo R$ e espaços em volta
    cleaned = value.replace("R$", "").replace(" ", "")
    if "," in cleaned:
        # Formato com decimal: "1.234,56" → remove pontos de milhar, troca vírgula por ponto
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        # Formato sem decimal: "10.273" → os pontos são separadores de milhar, remove todos
        cleaned = cleaned.replace(".", "")
    # Converte a string limpa para número de ponto flutuante
    return float(cleaned)


def load_dataset(filepath):
    """
    Lê o CSV de teste A/B e retorna uma lista de dicionários normalizados.
    Cada dicionário representa um dia de dados de um grupo específico.
    """
    rows = []
    # Abre o arquivo CSV com encoding UTF-8 (necessário para acentos em português)
    with open(filepath, encoding="utf-8") as f:
        # DictReader usa a primeira linha como cabeçalho e cria dicts por linha
        for r in csv.DictReader(f):
            # Converte cada coluna monetária de string BR para float
            vendas = parse_brl(r["vendas totais"])
            comissao = parse_brl(r["comissão".encode().decode()])  # encode/decode garante match do acento
            cashback = parse_brl(r["cashback"])
            rows.append({
                # Data convertida de string "2011-01-15" para objeto datetime
                "data": datetime.strptime(r["Data"], "%Y-%m-%d"),
                # Nome do grupo (ex: "Grupo 1"), com espaços extras removidos
                "grupo": r["Grupos de usuários".encode().decode()].strip(),
                # Nome do parceiro (ex: "Parceiro A"), com espaços extras removidos
                "parceiro": r["Parceiro"].strip(),
                # Número de compradores naquele dia (inteiro)
                "compradores": int(r["compradores"]),
                # Comissão em reais (float)
                "comissao": comissao,
                # Cashback pago em reais (float)
                "cashback": cashback,
                # Vendas totais em reais (float)
                "vendas": vendas,
                # Percentual de cashback sobre vendas naquele dia (evita divisão por zero)
                "cashback_pct": round(cashback / vendas * 100, 2) if vendas else 0,
                # Percentual de comissão sobre vendas naquele dia (evita divisão por zero)
                "comissao_pct": round(comissao / vendas * 100, 2) if vendas else 0,
            })
    return rows


# ==========================================================================
# MÉTRICAS — cálculos de negócio agregados por grupo
# ==========================================================================

def group_by(rows, key="grupo"):
    """
    Agrupa as linhas do CSV pela chave indicada (padrão: "grupo").
    Retorna um dict onde cada chave é o nome do grupo e o valor
    é a lista de linhas (dias) daquele grupo.
    """
    groups = {}
    for r in rows:
        # setdefault cria a lista vazia se a chave não existir, e depois faz append
        groups.setdefault(r[key], []).append(r)
    return groups


def compute_metrics(group_rows):
    """
    Calcula todas as métricas agregadas para um único grupo do teste.
    Recebe a lista de linhas (dias) daquele grupo e retorna um dicionário
    com métricas absolutas, por comprador, de variação e de tendência.
    """
    # Número total de dias no teste para esse grupo
    n_days = len(group_rows)

    # --- Totais absolutos ---
    # Soma de compradores em todos os dias
    total_compradores = sum(r["compradores"] for r in group_rows)
    # Soma de vendas em todos os dias
    total_vendas = sum(r["vendas"] for r in group_rows)
    # Soma de comissão em todos os dias
    total_comissao = sum(r["comissao"] for r in group_rows)
    # Soma de cashback pago em todos os dias
    total_cashback = sum(r["cashback"] for r in group_rows)
    # Margem = lucro líquido = comissão recebida menos cashback pago ao usuário
    margem = total_comissao - total_cashback

    # Listas de valores diários (usadas para t-tests e cálculos de variação)
    daily_buyers = [r["compradores"] for r in group_rows]
    daily_sales = [r["vendas"] for r in group_rows]

    # --- Tendência temporal ---
    # Compara a média da primeira metade do teste com a segunda metade.
    # Uma queda forte pode indicar sazonalidade ou fadiga do teste.
    mid = n_days // 2  # Ponto de corte no meio do período
    first_half = group_rows[:mid]   # Dias da primeira metade
    second_half = group_rows[mid:]  # Dias da segunda metade
    # Média de compradores por dia na primeira metade
    avg_buyers_1h = mean(r["compradores"] for r in first_half)
    # Média de compradores por dia na segunda metade
    avg_buyers_2h = mean(r["compradores"] for r in second_half)
    # Variação percentual de compradores entre as duas metades (negativo = queda)
    trend_buyers = (avg_buyers_2h - avg_buyers_1h) / avg_buyers_1h * 100 if avg_buyers_1h else 0
    # Mesmo cálculo para vendas
    avg_sales_1h = mean(r["vendas"] for r in first_half)
    avg_sales_2h = mean(r["vendas"] for r in second_half)
    trend_sales = (avg_sales_2h - avg_sales_1h) / avg_sales_1h * 100 if avg_sales_1h else 0

    # --- Verificação de cashback fixo ou variável ---
    # Coleta o percentual de cashback de cada dia
    daily_cb_pcts = [r["cashback_pct"] for r in group_rows]
    # Arredonda para 1 casa e pega os valores únicos
    unique_cb_pcts = sorted(set(round(p, 1) for p in daily_cb_pcts))
    # Se só existe 1 valor único, o cashback é fixo (teste controlado)
    # Se existem vários valores, o cashback variou ao longo do teste (problema)
    cashback_is_fixed = len(unique_cb_pcts) == 1

    return {
        # --- Totais absolutos ---
        "n_days": n_days,                       # Dias no teste
        "total_compradores": total_compradores,  # Soma de compradores
        "total_vendas": total_vendas,            # Soma de vendas (R$)
        "total_comissao": total_comissao,        # Soma de comissão recebida (R$)
        "total_cashback": total_cashback,        # Soma de cashback pago (R$)
        "margem": margem,                        # Lucro líquido = comissão - cashback
        # Ticket médio = vendas totais / compradores totais
        "ticket_medio": total_vendas / total_compradores if total_compradores else 0,
        # Percentual de comissão sobre vendas totais
        "comissao_pct": total_comissao / total_vendas * 100 if total_vendas else 0,
        # Percentual de cashback sobre vendas totais
        "cashback_pct": total_cashback / total_vendas * 100 if total_vendas else 0,
        # Percentual de margem sobre vendas totais
        "margem_pct": margem / total_vendas * 100 if total_vendas else 0,
        # ROI = retorno sobre investimento = margem / cashback investido * 100
        # Responde: "para cada R$1 de cashback, quantos R$ de lucro voltaram?"
        "roi": margem / total_cashback * 100 if total_cashback else 0,

        # --- Métricas por comprador (normalizam pelo volume, permitindo comparação justa) ---
        # Quanto de cashback foi gasto por comprador adquirido
        "cashback_por_comprador": total_cashback / total_compradores if total_compradores else 0,
        # Quanto de lucro cada comprador gerou (métrica mais importante do scoring)
        "margem_por_comprador": margem / total_compradores if total_compradores else 0,
        # Quanto cada comprador gastou em média
        "vendas_por_comprador": total_vendas / total_compradores if total_compradores else 0,

        # --- Variação diária (usada para estabilidade e testes estatísticos) ---
        # Média de compradores por dia
        "avg_daily_buyers": mean(daily_buyers),
        # Desvio padrão de compradores por dia (precisa de pelo menos 2 dias)
        "std_daily_buyers": stdev(daily_buyers) if n_days > 1 else 0,
        # Coeficiente de variação (CV) = desvio padrão / média * 100
        # Quanto maior o CV, mais instável é o grupo (mais difícil prever comportamento)
        "cv_buyers": (stdev(daily_buyers) / mean(daily_buyers) * 100) if n_days > 1 and mean(daily_buyers) > 0 else 0,
        # Média de vendas por dia
        "avg_daily_sales": mean(daily_sales),
        # Desvio padrão de vendas por dia
        "std_daily_sales": stdev(daily_sales) if n_days > 1 else 0,
        # Listas brutas de valores diários (passadas para o t-test)
        "daily_buyers": daily_buyers,
        "daily_sales": daily_sales,

        # --- Tendência temporal ---
        # Variação % de compradores entre as duas metades do teste
        "trend_buyers": trend_buyers,
        # Variação % de vendas entre as duas metades do teste
        "trend_sales": trend_sales,

        # --- Controle de cashback ---
        # True se o cashback foi o mesmo todos os dias (teste limpo)
        "cashback_is_fixed": cashback_is_fixed,
        # Lista dos percentuais distintos de cashback encontrados
        "cashback_pct_values": unique_cb_pcts,
    }


# ==========================================================================
# QUALIDADE — detecção de problemas que comprometem a validade do teste
# ==========================================================================

def detect_outliers_iqr(values, factor=1.5):
    """
    Detecta outliers usando o método IQR (Interquartile Range).
    Valores abaixo de Q1 - 1.5*IQR ou acima de Q3 + 1.5*IQR são outliers.
    Retorna os índices dos valores atípicos na lista original.
    """
    # Ordena os valores para calcular quartis
    sorted_v = sorted(values)
    n = len(sorted_v)
    # Q1 = primeiro quartil (25% dos dados estão abaixo)
    q1 = sorted_v[n // 4]
    # Q3 = terceiro quartil (75% dos dados estão abaixo)
    q3 = sorted_v[3 * n // 4]
    # IQR = amplitude interquartil (distância entre Q3 e Q1)
    iqr = q3 - q1
    # Retorna índices dos valores fora dos limites [Q1 - 1.5*IQR, Q3 + 1.5*IQR]
    return [i for i, v in enumerate(values) if v < q1 - factor * iqr or v > q3 + factor * iqr]


def check_quality(groups_metrics):
    """
    Verifica 5 tipos de problemas de qualidade nos dados do teste.
    Cada alerta tem tipo, severidade (critica/alta/media/baixa), grupo afetado
    e uma mensagem explicativa. Alertas geram penalidades no score.
    """
    alerts = []

    # ----- ALERTA 1: Desbalanceamento de tráfego entre grupos -----
    # Se um grupo recebeu muito mais usuários que outro, a aleatorização
    # pode estar comprometida e as métricas não são diretamente comparáveis.
    buyers = {g: m["total_compradores"] for g, m in groups_metrics.items()}
    # Calcula a média de compradores entre todos os grupos
    avg_buyers = mean(buyers.values())
    for g, b in buyers.items():
        # Desvio percentual desse grupo em relação à média
        dev = abs(b - avg_buyers) / avg_buyers * 100
        # Se desvia mais de 20%, dispara alerta de severidade alta
        if dev > 20:
            direction = "acima" if b > avg_buyers else "abaixo"
            alerts.append({
                "tipo": "desbalanceamento",
                "severidade": "alta",
                "grupo": g,
                "msg": (f"{g} tem {b:,} compradores, {dev:.0f}% {direction} da "
                        f"média dos grupos ({avg_buyers:,.0f}). "
                        f"Tráfego desbalanceado compromete a comparação direta entre grupos porque "
                        f"o grupo maior pode ter métricas infladas por volume, não por eficiência do cashback."),
            })

    # ----- ALERTA 2: Margem zero ou negativa -----
    # Se o cashback consome toda a comissão, a operação dá prejuízo.
    # É o problema mais grave — não faz sentido escalar algo que não dá lucro.
    for g, m in groups_metrics.items():
        if m["margem"] <= 0:
            alerts.append({
                "tipo": "margem_zero",
                "severidade": "critica",  # Severidade máxima: -30 pontos
                "grupo": g,
                "msg": (f"{g} opera com margem {'zero' if m['margem'] == 0 else 'negativa'}: "
                        f"cashback de {m['cashback_pct']:.1f}% consome "
                        f"{'toda' if m['margem'] == 0 else 'mais que toda'} "
                        f"a comissão de {m['comissao_pct']:.1f}%. "
                        f"Escalar esse grupo para 100% significa gerar receita líquida zero neste parceiro."),
            })

    # ----- ALERTA 3: Cashback variável ao longo do teste -----
    # Se o percentual de cashback mudou durante o teste, a variável independente
    # não foi controlada. É como mudar a dose no meio de um experimento médico.
    variable_groups = [g for g, m in groups_metrics.items() if not m["cashback_is_fixed"]]
    if variable_groups:
        for g in variable_groups:
            m = groups_metrics[g]
            vals = m["cashback_pct_values"]  # Lista dos percentuais distintos encontrados
            alerts.append({
                "tipo": "cashback_variavel",
                "severidade": "media",  # Severidade média: -5 pontos
                "grupo": g,
                "msg": (f"{g} não tem cashback fixo: o percentual varia entre "
                        f"{min(vals):.1f}% e {max(vals):.1f}% ao longo dos {m['n_days']} dias. "
                        f"Isso pode indicar promoções pontuais ou ajustes manuais, "
                        f"dificultando isolar o efeito do cashback no comportamento de compra."),
            })

    # ----- ALERTA 4: Tendência temporal forte -----
    # Se os compradores caíram (ou subiram) mais de 25% entre a primeira
    # e segunda metade do teste, pode haver sazonalidade ou fadiga.
    for g, m in groups_metrics.items():
        if abs(m["trend_buyers"]) > 25:
            direction = "queda" if m["trend_buyers"] < 0 else "crescimento"
            alerts.append({
                "tipo": "tendencia_temporal",
                "severidade": "media",  # Severidade média: -5 pontos
                "grupo": g,
                "msg": (f"{g} apresenta {direction} de {abs(m['trend_buyers']):.0f}% nos compradores entre "
                        f"a primeira e a segunda metade do teste. Pode ser efeito de sazonalidade, "
                        f"fadiga do teste ou mudança externa que afeta a confiabilidade da comparação."),
            })

    # ----- ALERTA 5: Outliers de compradores -----
    # Se mais de 10% dos dias são atípicos, as médias podem ser enganosas.
    for g, m in groups_metrics.items():
        # Detecta dias com compradores fora do intervalo normal (IQR)
        outlier_idx = detect_outliers_iqr(m["daily_buyers"])
        # Calcula que % dos dias são outliers
        pct_outliers = len(outlier_idx) / len(m["daily_buyers"]) * 100
        if pct_outliers > 10:
            alerts.append({
                "tipo": "outliers",
                "severidade": "baixa",  # Severidade baixa: sem penalidade direta
                "grupo": g,
                "msg": (f"{g} tem {len(outlier_idx)} dias atípicos ({pct_outliers:.0f}% do total). "
                        f"Variabilidade alta (CV de {m['cv_buyers']:.0f}%) reduz a precisão das médias."),
            })

    return alerts


# ==========================================================================
# ESTATÍSTICA — testes de hipótese entre pares de grupos
# ==========================================================================

def run_statistical_tests(groups_metrics):
    """
    Roda o t-test de Welch entre cada par de grupos para 3 métricas:
    vendas diárias, compradores diários e ticket médio diário.

    Usa Welch (equal_var=False) em vez do t-test clássico porque:
    - Os grupos podem ter tamanhos diferentes (ex: Parceiro B)
    - Welch não assume variâncias iguais, o que é mais conservador
    - Reduz falsos positivos em amostras desbalanceadas

    Um p-value < 0.05 significa que a diferença é estatisticamente significativa
    (menos de 5% de chance de ser acaso).
    """
    results = []
    # Ordena os nomes dos grupos para gerar pares sem repetição
    group_names = sorted(groups_metrics.keys())

    # Loop para gerar todos os pares possíveis (ex: G1 vs G2, G1 vs G3, G2 vs G3)
    for i in range(len(group_names)):
        for j in range(i + 1, len(group_names)):
            g1, g2 = group_names[i], group_names[j]
            m1, m2 = groups_metrics[g1], groups_metrics[g2]

            # T-test de Welch para vendas diárias entre os dois grupos
            # t_sales = estatística t (magnitude da diferença), p_sales = p-value
            t_sales, p_sales = stats.ttest_ind(
                m1["daily_sales"], m2["daily_sales"], equal_var=False
            )
            # T-test de Welch para compradores diários
            t_buyers, p_buyers = stats.ttest_ind(
                m1["daily_buyers"], m2["daily_buyers"], equal_var=False
            )

            # Calcula o ticket médio de cada dia (vendas/compradores por dia)
            # para comparar o valor por transação, não o volume bruto
            rpm1 = [s / b if b > 0 else 0 for s, b in zip(m1["daily_sales"], m1["daily_buyers"])]
            rpm2 = [s / b if b > 0 else 0 for s, b in zip(m2["daily_sales"], m2["daily_buyers"])]
            # T-test de Welch para ticket médio diário
            t_rpm, p_rpm = stats.ttest_ind(rpm1, rpm2, equal_var=False)

            results.append({
                "grupo_a": g1,                          # Nome do primeiro grupo no par
                "grupo_b": g2,                          # Nome do segundo grupo no par
                "p_value_vendas": p_sales,              # p-value do teste em vendas
                "significativo_vendas": p_sales < 0.05, # True se a diferença é significativa
                "p_value_compradores": p_buyers,        # p-value do teste em compradores
                "significativo_compradores": p_buyers < 0.05,  # True se significativo
                "p_value_ticket": p_rpm,                # p-value do teste em ticket médio
                "significativo_ticket": p_rpm < 0.05,   # True se significativo
                # Diferença percentual de vendas médias diárias (G2 vs G1)
                "diff_vendas_pct": (m2["avg_daily_sales"] - m1["avg_daily_sales"]) / m1["avg_daily_sales"] * 100,
                # Diferença percentual de compradores médios diários
                "diff_compradores_pct": (m2["avg_daily_buyers"] - m1["avg_daily_buyers"]) / m1["avg_daily_buyers"] * 100,
                # Diferença percentual no ticket médio
                "diff_ticket_pct": (m2["ticket_medio"] - m1["ticket_medio"]) / m1["ticket_medio"] * 100 if m1["ticket_medio"] else 0,
            })

    return results


# ==========================================================================
# DECISÃO — modelo de pontuação que gera a recomendação final
# ==========================================================================

def make_decision(groups_metrics, quality_alerts, stat_tests):
    """
    Calcula um score de 0 a 100 para cada grupo usando 4 critérios ponderados:

    - 35% margem por comprador → lucro real normalizado por volume
    - 25% volume de compradores → capacidade de tração/escala
    - 25% ROI → eficiência do investimento em cashback
    - 15% estabilidade → previsibilidade (inverso do coeficiente de variação)

    Depois aplica penalidades por alertas de qualidade vinculados ao grupo.
    O grupo com maior score final é o recomendado.
    """
    scores = {}     # Score final de cada grupo
    reasoning = {}  # Lista de justificativas por grupo (exibida no relatório)

    # --- Coleta os valores de cada métrica de todos os grupos ---
    # Necessário para normalizar: o melhor grupo em cada métrica recebe nota máxima
    all_mpc = [m["margem_por_comprador"] for m in groups_metrics.values()]    # Todas as margens/comprador
    all_buyers = [m["total_compradores"] for m in groups_metrics.values()]    # Todos os volumes
    all_roi = [m["roi"] for m in groups_metrics.values()]                     # Todos os ROIs
    all_cv = [m["cv_buyers"] for m in groups_metrics.values()]                # Todos os CVs

    # Valor máximo de cada métrica (usado para normalizar de 0 a 1)
    # Se o máximo for 0 ou negativo, usa 1 para evitar divisão por zero
    max_mpc = max(all_mpc) if max(all_mpc) > 0 else 1
    max_buyers = max(all_buyers) if max(all_buyers) > 0 else 1
    max_roi = max(all_roi) if max(all_roi) > 0 else 1
    max_cv = max(all_cv) if max(all_cv) > 0 else 1

    # --- Calcula score de cada grupo ---
    for g, m in groups_metrics.items():
        # Score de margem por comprador: normalizado pelo melhor, multiplicado pelo peso 35
        # Grupo com maior margem/comprador recebe 35 pontos, os outros proporcionalmente
        s_mpc = (m["margem_por_comprador"] / max_mpc) * 35 if max_mpc > 0 else 0

        # Score de volume: normalizado pelo grupo com mais compradores, peso 25
        # Grupo com mais compradores recebe 25 pontos
        s_buyers = (m["total_compradores"] / max_buyers) * 25

        # Score de ROI: normalizado pelo melhor ROI, peso 25
        # Grupo mais eficiente recebe 25 pontos
        s_roi = (m["roi"] / max_roi) * 25 if max_roi > 0 else 0

        # Score de estabilidade: INVERSO do CV (menor CV = mais estável = mais pontos)
        # O grupo mais estável (menor CV) recebe 15 pontos
        # Fórmula: (max_cv - meu_cv) / max_cv → 1 para o mais estável, 0 para o mais instável
        s_stab = ((max_cv - m["cv_buyers"]) / max_cv) * 15 if max_cv > 0 else 0

        # Score bruto = soma dos 4 componentes (máximo teórico: 100)
        score = s_mpc + s_buyers + s_roi + s_stab

        # --- Monta a justificativa detalhada (exibida no relatório) ---
        reasons = []
        reasons.append(f"Margem/comprador R$ {m['margem_por_comprador']:.2f} ({s_mpc:.1f}/35 pts)")
        reasons.append(f"Compradores {m['total_compradores']:,} ({s_buyers:.1f}/25 pts)")
        reasons.append(f"ROI {m['roi']:.0f}% ({s_roi:.1f}/25 pts)")
        reasons.append(f"Estabilidade CV {m['cv_buyers']:.0f}% ({s_stab:.1f}/15 pts)")

        # --- Aplica penalidades por alertas de qualidade ---
        # Só penaliza alertas que pertencem a este grupo específico
        for alert in quality_alerts:
            if alert.get("grupo") == g:
                sev = alert["severidade"]
                if sev == "critica":
                    # Penalidade máxima: -30 pontos (ex: margem zero)
                    score -= 30
                    reasons.append(f"Penalidade -30: {alert['tipo']}")
                elif sev == "alta":
                    # Penalidade forte: -15 pontos (ex: desbalanceamento)
                    score -= 15
                    reasons.append(f"Penalidade -15: {alert['tipo']}")
                elif sev == "media":
                    # Penalidade moderada: -5 pontos (ex: cashback variável, tendência)
                    score -= 5
                    reasons.append(f"Penalidade -5: {alert['tipo']}")
                # Severidade "baixa" não gera penalidade no score

        # Score final: mínimo 0 (não pode ser negativo), arredondado para 1 casa decimal
        scores[g] = round(max(score, 0), 1)
        reasoning[g] = reasons

    # --- Determina o vencedor (grupo com maior score) ---
    winner = max(scores, key=scores.get)
    w = groups_metrics[winner]  # Métricas do grupo vencedor

    # --- Gera a justificativa em texto natural ---
    parts = [f"{winner} é a variante recomendada para escalar a 100% do tráfego."]

    # Ordena grupos por score (maior primeiro)
    ranked = sorted(scores, key=scores.get, reverse=True)
    second = ranked[1] if len(ranked) > 1 else None  # Segundo colocado

    # Se o segundo lugar tem vendas brutas maiores, explica por que mesmo assim perdeu
    # (caso comum: grupo com mais tráfego tem vendas maiores mas margem/comprador menor)
    if second and groups_metrics[second]["total_vendas"] > w["total_vendas"]:
        s = groups_metrics[second]
        parts.append(
            f"Embora {second} tenha vendas brutas maiores "
            f"(R$ {s['total_vendas']:,.0f} vs R$ {w['total_vendas']:,.0f}), "
            f"{winner} gera mais margem por comprador "
            f"(R$ {w['margem_por_comprador']:.2f} vs R$ {s['margem_por_comprador']:.2f}), "
            f"o que importa para a rentabilidade do Méliuz."
        )
    else:
        # Caso geral: o vencedor também lidera em vendas
        parts.append(
            f"Com margem de R$ {w['margem']:,.0f} e ROI de {w['roi']:.0f}%, "
            f"é o grupo que melhor equilibra retorno financeiro e volume."
        )

    # Se o próprio vencedor tem alertas, avisa que há ressalvas
    winner_alerts = [a for a in quality_alerts if a.get("grupo") == winner]
    if winner_alerts:
        parts.append(
            f"Atenção: há {len(winner_alerts)} alerta(s) de qualidade neste grupo que "
            f"devem ser considerados antes da decisão final."
        )

    return {
        "winner": winner,              # Nome do grupo vencedor
        "scores": scores,              # Dict com score de cada grupo
        "reasoning": reasoning,        # Dict com lista de justificativas por grupo
        "justification": " ".join(parts),  # Texto corrido com a justificativa geral
    }


# ==========================================================================
# ORQUESTRADOR — função principal que executa toda a análise
# ==========================================================================

def analyze(filepath):
    """
    Função principal: recebe o caminho de um CSV de teste A/B e retorna
    um dicionário completo com todas as informações para o relatório.

    Fluxo: carregar dados → agrupar → calcular métricas → verificar qualidade
    → rodar testes estatísticos → gerar decisão.
    """
    # 1. Carrega e normaliza os dados do CSV
    rows = load_dataset(filepath)

    # 2. Extrai metadados do teste (parceiro, datas)
    parceiro = rows[0]["parceiro"]  # Nome do parceiro (ex: "Parceiro A")
    data_inicio = min(r["data"] for r in rows).strftime("%d/%m/%Y")  # Primeiro dia do teste
    data_fim = max(r["data"] for r in rows).strftime("%d/%m/%Y")      # Último dia do teste

    # 3. Agrupa as linhas por grupo de teste (ex: "Grupo 1", "Grupo 2", "Grupo 3")
    grouped = group_by(rows)
    # 4. Calcula métricas de negócio para cada grupo
    groups_metrics = {g: compute_metrics(rs) for g, rs in grouped.items()}

    # 5. Verifica problemas de qualidade nos dados (desbalanceamento, margem zero, etc.)
    quality_alerts = check_quality(groups_metrics)
    # 6. Roda testes estatísticos (Welch t-test) entre pares de grupos
    stat_tests = run_statistical_tests(groups_metrics)
    # 7. Gera a decisão final com scores ponderados e penalidades
    decision = make_decision(groups_metrics, quality_alerts, stat_tests)

    # 8. Retorna o pacote completo para o template HTML renderizar
    return {
        "parceiro": parceiro,                       # Nome do parceiro
        "periodo": f"{data_inicio} a {data_fim}",   # Período do teste (ex: "15/01/2011 a 17/04/2011")
        "n_grupos": len(groups_metrics),             # Quantos grupos no teste
        "n_dias": groups_metrics[list(groups_metrics.keys())[0]]["n_days"],  # Dias de teste
        "groups_metrics": groups_metrics,            # Métricas de cada grupo
        "quality_alerts": quality_alerts,            # Lista de alertas de qualidade
        "stat_tests": stat_tests,                    # Resultados dos testes estatísticos
        "decision": decision,                        # Decisão final (vencedor, scores, justificativa)
    }
