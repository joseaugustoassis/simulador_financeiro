import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import requests
from datetime import datetime
import json

# Define uma função de formatação de moeda para o padrão brasileiro
def format_brl(val):
    """
    Formata um valor numérico para a moeda brasileira (R$).
    Ex: 1234567.89 -> 'R$ 1.234.567,89'
    """
    # Garante que o valor seja float antes de formatar
    val = float(val)
    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# -------------------------------------------------------------
# Requisitos do Trabalho
# - Projeto de investimento: 'Compra de imóvel' (exemplo no código)
# - Simular com/sem aportes (fixos/variáveis)
# - Diferentes taxas de juros (fixas/variáveis, mensais/anuais)
# - Períodos em meses e anos (com conversor para dias)
# - Simulação de Imposto de Renda (incide ou não)
# - Relatório de análise comparativa
# - **EXTRA**: Adicionar Valor de Entrada e Amortizações Extraordinárias
# - **EXTRA**: Adicionar total das parcelas pagas no SAC x Tabela Price
# -------------------------------------------------------------

# -----------------------------
# Funções de Dados e Cálculo
# -----------------------------

def get_selic():
    """Busca a taxa Selic no Banco Central. Retorna (taxa, data) e 13% como fallback."""
    url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
    try:
        response = requests.get(url).json()
        selic = float(response[0]['valor']) / 100
        data = response[0]['data']
        # Converte a data para o formato brasileiro
        data_obj = datetime.strptime(data, '%d/%m/%Y').date()
        hoje = datetime.now().date()

        # Se a data da API for futura, usa a data atual
        if data_obj > hoje:
            data_para_exibir = hoje
        else:
            data_para_exibir = data_obj

        # Formata a data para DD/MM/YYYY
        data_formatada = data_para_exibir.strftime('%d/%m/%Y')

        return selic, data_formatada
    except:
        return 0.13, "Data não disponível"

def get_cdi():
    """Calcula o CDI a partir da Selic. CDI ≈ 99,75% da Selic."""
    return get_selic()[0] * 0.9975

def get_poupanca():
    """
    Calcula a taxa de rendimento anual da poupança com base na Selic.
    - Se Selic > 8.5% a.a., poupança = 0.5% a.m. (aprox. 6.17% a.a.)
    - Se Selic <= 8.5% a.a., poupança = 70% da Selic
    """
    selic_anual = get_selic()[0]
    if selic_anual > 0.085:
        # 0.5% ao mês, convertendo para anual
        return (1 + 0.005)**12 - 1
    else:
        return selic_anual * 0.70

def calcular_ir_regressivo(meses, rendimento):
    """
    Calcula o Imposto de Renda com base na tabela regressiva para renda fixa.
    Alíquotas:
    - até 6 meses: 22.5%
    - 6 a 12 meses: 20%
    - 12 a 24 meses: 17.5%
    - acima de 24 meses: 15%
    """
    if meses <= 6:
        aliquota = 0.225
    elif meses <= 12:
        aliquota = 0.20
    elif meses <= 24:
        aliquota = 0.175
    else:
        aliquota = 0.15
    return rendimento * aliquota

def simular_investimento_detalhado(
    valor_inicial,
    tipo_aporte,
    aporte_mensal_base,
    variacao_aporte,
    aportes_customizados,
    taxa_anual_base,
    variacao_taxa_mensal,
    meses,
    incide_ir=False
):
    """
    Simula o investimento mês a mês, retornando um DataFrame detalhado.
    - Suporta diferentes tipos de aportes variáveis e taxas variáveis.
    - Calcula o IR regressivo.
    """
    dados_mensais = []
    saldo = valor_inicial
    capital_total = valor_inicial

    # A taxa mensal é calculada a partir da taxa anual base
    taxa_mensal = (1 + taxa_anual_base) ** (1/12) - 1

    for mes in range(1, meses + 1):
        # Lógica para o aporte variável
        if tipo_aporte == "Fixo":
            aporte_do_mes = aporte_mensal_base
        elif tipo_aporte == "Variação Linear":
            aporte_do_mes = aporte_mensal_base + (mes - 1) * variacao_aporte
        elif tipo_aporte == "Variação Percentual":
            # Calcula o aporte com base no crescimento anual
            aporte_do_mes = aporte_mensal_base * (1 + variacao_aporte)**((mes - 1) // 12)
        elif tipo_aporte == "Aportes Customizados":
            aporte_do_mes = aporte_mensal_base + aportes_customizados.get(mes, 0)
        else: # Tipo inválido, assume fixo
            aporte_do_mes = aporte_mensal_base

        # Juros do mês com taxa variável
        juros_do_mes = saldo * taxa_mensal

        # Saldo bruto atualizado
        saldo += juros_do_mes + aporte_do_mes
        capital_total += aporte_do_mes

        # Variação da taxa para o próximo mês
        taxa_mensal *= (1 + variacao_taxa_mensal)

        # Guarda os dados para o DataFrame
        dados_mensais.append({
            'Mês': mes,
            'Aporte': aporte_do_mes,
            'Juros (R$)': juros_do_mes,
            'Saldo Bruto (R$)': saldo,
            'Capital Acumulado (R$)': capital_total
        })

    # Cria o DataFrame
    df_detalhado = pd.DataFrame(dados_mensais)

    # Cálculos finais
    saldo_bruto = df_detalhado.loc[meses - 1, 'Saldo Bruto (R$)']

    # Calcula o capital investido de forma mais precisa
    capital_investido = valor_inicial + df_detalhado['Aporte'].sum()
    rendimento_bruto = saldo_bruto - capital_investido

    ir_pago = 0.0
    if incide_ir:
        ir_pago = calcular_ir_regressivo(meses, rendimento_bruto)

    saldo_liquido = saldo_bruto - ir_pago

    return saldo_bruto, ir_pago, saldo_liquido, df_detalhado, capital_investido

def calcular_sac(principal, taxa_mensal, meses, amort_extra_valor, meses_extra_amort):
    """Calcula a tabela de amortização SAC com amortização extraordinária."""
    tabela = []
    saldo_devedor = principal
    juros_total = 0
    parcela_total = 0
    amortizacao_fixa = principal / meses

    for mes in range(1, meses + 1):
        if saldo_devedor <= 0:
            # Se o saldo devedor já foi pago, todas as colunas são zero
            tabela.append({
                'Mês': mes,
                'Juros': 0,
                'Amortização': 0,
                'Parcela': 0,
                'Saldo Devedor': 0
            })
            continue

        juros = saldo_devedor * taxa_mensal

        amortizacao_mes = amortizacao_fixa

        # Adiciona amortização extraordinária se o mês estiver na lista
        if mes in meses_extra_amort:
            amortizacao_mes += amort_extra_valor

        parcela = amortizacao_mes + juros

        saldo_devedor_anterior = saldo_devedor
        saldo_devedor -= amortizacao_mes

        # Garante que o saldo devedor não seja negativo
        if saldo_devedor < 0:
            amortizacao_mes = saldo_devedor_anterior - (amort_extra_valor if mes in meses_extra_amort else 0)
            amortizacao_mes += juros
            saldo_devedor = 0
            parcela = amortizacao_mes + juros

        juros_total += juros
        parcela_total += parcela

        tabela.append({
            'Mês': mes,
            'Juros': juros,
            'Amortização': amortizacao_mes,
            'Parcela': parcela,
            'Saldo Devedor': saldo_devedor
        })

    return pd.DataFrame(tabela), juros_total, parcela_total

def calcular_price(principal, taxa_mensal, meses, amort_extra_valor, meses_extra_amort):
    """Calcula a tabela de amortização Tabela Price com amortização extraordinária."""
    tabela = []
    saldo_devedor = principal
    juros_total = 0
    parcela_total = 0

    # Cálculo da parcela fixa
    try:
        parcela_fixa = principal * ((1 + taxa_mensal)**meses * taxa_mensal) / ((1 + taxa_mensal)**meses - 1)
    except ZeroDivisionError:
        parcela_fixa = 0

    for mes in range(1, meses + 1):
        if saldo_devedor <= 0:
            # Se o saldo devedor já foi pago, todas as colunas são zero
            tabela.append({
                'Mês': mes,
                'Juros': 0,
                'Amortização': 0,
                'Parcela': 0,
                'Saldo Devedor': 0
            })
            continue

        juros = saldo_devedor * taxa_mensal
        amortizacao = parcela_fixa - juros

        saldo_devedor_anterior = saldo_devedor

        # Adiciona amortização extraordinária se o mês estiver na lista
        if mes in meses_extra_amort:
            saldo_devedor -= amort_extra_valor

        saldo_devedor -= amortizacao

        # Garante que o saldo devedor não seja negativo
        if saldo_devedor < 0:
            amortizacao = saldo_devedor_anterior - (amort_extra_valor if mes in meses_extra_amort else 0)
            amortizacao += juros
            saldo_devedor = 0

        juros_total += juros
        parcela_total += (parcela_fixa + (amort_extra_valor if mes in meses_extra_amort else 0))

        tabela.append({
            'Mês': mes,
            'Juros': juros,
            'Amortização': amortizacao,
            'Parcela': parcela_fixa,
            'Saldo Devedor': saldo_devedor
        })

    return pd.DataFrame(tabela), juros_total, parcela_total

# -----------------------------
# Configuração Streamlit
# -----------------------------
st.set_page_config(layout="wide")

st.sidebar.header("Configurações")
aba = st.sidebar.radio(
    "Escolha uma aba:",
    ["Análise Comparativa (com Taxas de Juros Atuais)",
     "Simulação Manual Detalhada",
     "Conversor de Períodos",
     "Conversor de Taxas de Juros",
     "SAC x Tabela Price"]
)

st.title("📊 Simulador de Investimentos")
st.markdown("---")

# -----------------------------
# Aba 1 - Análise Comparativa (com Taxas de Juros Atuais)
# -----------------------------
if aba == "Análise Comparativa (com Taxas de Juros Atuais)":
    st.header("Relatório comparativo de investimentos")
    st.markdown("Compare a rentabilidade de diferentes tipos de investimentos em um único relatório.")

    # Busca as taxas de juros atuais e a data da coleta
    selic, selic_data = get_selic()
    cdi = get_cdi()
    poupanca_taxa = get_poupanca()

    # Mostra as taxas de juros que estão sendo aplicadas
    st.info(f"**Taxas de Juros Atuais (Informações do Banco Central do Brasil):**\n\n"
            f"- **Última atualização:** {selic_data}\n"
            f"- **Selic Anual:** {selic:.2%} (utilizada para o Tesouro Selic)\n"
            f"- **CDI Anual:** {cdi:.2%} (utilizada para CDB e LCI/LCA)\n"
            f"- **Poupança Anual:** {poupanca_taxa:.2%}")

    # Adiciona o campo para o objetivo do investimento
    objetivo = st.text_input("Qual o objetivo do seu investimento?", "Comprar uma casa")

    col1, col2 = st.columns(2)
    with col1:
        valor_inicial = st.number_input("Valor inicial (R$)", 0.0, step=100.0, key="comp1", help="O valor que você já possui para investir no início.")
        perc_cdb = st.number_input("Porcentagem do CDI para CDB (%)", value=110.0, step=1.0, help="Representa o percentual do CDI que o seu investimento renderá.")
        perc_lci = st.number_input("Porcentagem do CDI para LCI/LCA (%)", value=95.0, step=1.0, help="Representa o percentual do CDI que o seu investimento isento de IR renderá.")
    with col2:
        st.subheader("Período de Análise")

        opcao_periodo = st.selectbox(
            "Selecione o tipo de período:",
            ["Anos e Meses", "Somente Anos", "Somente Meses"],
            key="comp_select_periodo"
        )

        anos = 0
        meses_adicionais = 0

        if opcao_periodo == "Anos e Meses":
            anos = st.number_input("Anos", 0, step=1, key="comp_anos", help="O tempo total do seu investimento em anos.")
            meses_adicionais = st.number_input("Meses", 0, step=1, key="comp_meses_ad", help="Meses adicionais ao período em anos.")
        elif opcao_periodo == "Somente Anos":
            anos = st.number_input("Anos", 0, step=1, key="comp_anos_somente", help="O tempo total do seu investimento em anos.")
        elif opcao_periodo == "Somente Meses":
            meses_adicionais = st.number_input("Meses", 0, step=1, key="comp_meses_somente", help="Meses do seu investimento.")

    # Aportes variáveis na Aba 1
    with st.expander("Configurar Aportes Mensais"):
        tipo_aporte_comp = st.radio(
            "Tipo de Aporte:",
            ["Fixo", "Variação Linear", "Variação Percentual", "Aportes Customizados"],
            key="tipo_aporte_comp"
        )
        aporte_comp = 0.0
        variacao_aporte_comp = 0.0
        aportes_customizados_comp = {}

        if tipo_aporte_comp == "Fixo":
            aporte_comp = st.number_input("Aporte mensal (R$)", 0.0, step=100.0, key="comp2", help="O valor fixo que você adicionará ao investimento todo mês.")
        elif tipo_aporte_comp == "Variação Linear":
            aporte_comp = st.number_input("Aporte inicial (R$)", 0.0, step=100.0, key="comp_var_ini", help="O valor do primeiro aporte.")
            variacao_aporte_comp = st.number_input("Variação do aporte mensal (R$)", 0.0, step=10.0, key="comp_var", help="Valor que será adicionado ao aporte a cada mês (ex: 10,00).")
        elif tipo_aporte_comp == "Variação Percentual":
            aporte_comp = st.number_input("Aporte inicial (R$)", 0.0, step=100.0, key="comp_perc_ini", help="O valor do primeiro aporte.")
            variacao_aporte_comp = st.number_input("Variação anual do aporte (%)", 0.0, step=0.1, key="comp_perc_var", help="Percentual de aumento anual do aporte.") / 100
        elif tipo_aporte_comp == "Aportes Customizados":
            aporte_comp = st.number_input("Aporte mensal (R$)", 0.0, step=100.0, key="comp_custom_base", help="O valor do aporte fixo que será somado aos aportes customizados.")
            aportes_customizados_str = st.text_area(
                "Aportes adicionais (mês:valor)",
                help="Preencha com o mês e o valor, separados por vírgula. Ex: `12:1000, 24:2000, 36:500`"
            )
            try:
                if aportes_customizados_str:
                    limpo_str = aportes_customizados_str.replace(';', ',')
                    for item in limpo_str.split(','):
                        item_strip = item.strip()
                        if item_strip:
                            mes, valor = item_strip.split(':')
                            aportes_customizados_comp[int(mes.strip())] = float(valor.strip())
            except:
                st.error("Formato inválido para aportes customizados. Use 'mês:valor' separado por vírgula.")
                aportes_customizados_comp = {}

    meses = (anos * 12) + meses_adicionais

    if meses > 0:
        st.markdown(f"**Período total:** **{anos}** anos e **{meses_adicionais}** meses, totalizando **{meses}** meses ou aproximadamente **{meses*30}** dias.")

        # Taxas aproximadas com base no CDI e Selic (buscadas da internet)
        taxas = {
            "Poupança": poupanca_taxa,
            f"CDB ({perc_cdb:.0f}% CDI)": (cdi * perc_cdb / 100),
            f"LCI/LCA ({perc_lci:.0f}% CDI)": (cdi * perc_lci / 100),
            "Tesouro Selic": selic,
        }

        resultados = {}
        dataframes_para_grafico = {}
        for nome, taxa_anual in taxas.items():
            incide_ir = nome.startswith("CDB") or nome.startswith("Tesouro")
            # Usa a nova função de simulação para a precisão do IR e capital investido
            saldo_bruto, ir_pago, saldo_liquido, df_detalhado, capital_investido = simular_investimento_detalhado(
                valor_inicial,
                tipo_aporte_comp,
                aporte_comp,
                variacao_aporte_comp,
                aportes_customizados_comp,
                taxa_anual,
                0, # Taxa fixa para comparação
                meses,
                incide_ir
            )
            resultados[nome] = {
                "Saldo Final Bruto (R$)": saldo_bruto,
                "IR Pago (R$)": ir_pago,
                "Saldo Final Líquido (R$)": saldo_liquido
            }
            dataframes_para_grafico[nome] = df_detalhado.set_index('Mês')


        st.info(f"**Total Investido (Capital Alocado):** {format_brl(capital_investido)}")

        df_comp = pd.DataFrame(resultados).T
        st.subheader("Resultados Comparativos")

        # Formata os valores da tabela
        st.dataframe(df_comp.style.format(format_brl))

        # Análise textual
        melhor = df_comp["Saldo Final Líquido (R$)"].idxmax()
        melhor_valor = df_comp.loc[melhor, "Saldo Final Líquido (R$)"]

        pior = df_comp["Saldo Final Líquido (R$)"].idxmin()
        pior_valor = df_comp.loc[pior, "Saldo Final Líquido (R$)"]

        rendimento_melhor = melhor_valor - capital_investido
        rendimento_pior = pior_valor - capital_investido

        if rendimento_pior > 0:
            diferenca_percentual = ((rendimento_melhor / rendimento_pior) - 1) * 100
            analise = (
                f"Para o seu objetivo de '{objetivo}', o melhor investimento é o **{melhor}**, "
                f"com um saldo líquido de {format_brl(melhor_valor)}. "
                f"Isso representa uma rentabilidade líquida de {diferenca_percentual:.2f}% acima do **{pior}**, "
                f"o investimento de menor rendimento neste cenário."
            )
        else:
            analise = (
                f"Para o seu objetivo de '{objetivo}', o melhor investimento é o **{melhor}**, "
                f"com um saldo líquido de {format_brl(melhor_valor)}. "
                f"O investimento de menor rendimento foi a **{pior}**."
            )

        st.success(analise)

        st.markdown("---")
        st.subheader("Análise Gráfica")

        # Cria um DataFrame para o gráfico de linhas com os saldos de cada investimento
        df_grafico_linhas = pd.DataFrame({
            nome: df['Saldo Bruto (R$)'] for nome, df in dataframes_para_grafico.items()
        })

        st.line_chart(df_grafico_linhas)
        st.bar_chart(df_comp['Saldo Final Líquido (R$)'])
        st.markdown("---")
    else:
        st.error("O período de simulação deve ser maior que 0. Por favor, insira anos ou meses para continuar.")

# -----------------------------
# Aba 2 - Simulação Manual Detalhada
# -----------------------------
elif aba == "Simulação Manual Detalhada":
    st.header("Simulação manual detalhada")

    # Permite que o usuário defina o projeto
    projeto_pessoal = st.text_input("Qual o objetivo do seu projeto pessoal?", "Comprar um imóvel")
    st.info(f"💡 **Projeto Pessoal:** {projeto_pessoal}")

    with st.expander("Configurar Parâmetros da Simulação"):
        # Colunas para organizar a entrada de dados
        col1, col2 = st.columns(2)
        with col1:
            valor_inicial = st.number_input("Valor inicial (R$)", 0.0, step=100.0, help="O valor que você já possui para iniciar o investimento.")

            tipo_aporte = st.selectbox(
                "Tipo de Aporte Mensal:",
                ["Fixo", "Variação Linear", "Variação Percentual", "Aportes Customizados"],
                key="tipo_aporte_sim",
                help="Escolha se seus aportes serão fixos ou se variarão a cada mês."
            )

            if tipo_aporte == "Variação Linear":
                aporte_mensal = st.number_input("Aporte inicial (R$)", 0.0, step=100.0, key="sim_var_ini", help="Valor do primeiro aporte.")
                variacao_aporte = st.number_input("Variação do aporte mensal (R$)", 0.0, step=10.0, key="sim_var", help="Valor que será adicionado ao aporte a cada mês (ex: 10,00).")
                aportes_customizados = {}
            elif tipo_aporte == "Variação Percentual":
                aporte_mensal = st.number_input("Aporte inicial (R$)", 0.0, step=100.0, key="sim_perc_ini", help="Valor do primeiro aporte.")
                variacao_aporte = st.number_input("Variação anual do aporte (%)", 0.0, step=0.1, key="sim_perc_var", help="Percentual de aumento anual do aporte.") / 100
                aportes_customizados = {}
            elif tipo_aporte == "Aportes Customizados":
                aporte_mensal = st.number_input("Aporte Mensal (R$)", 0.0, step=100.0, key="sim_custom_base", help="O valor do aporte fixo que será somado aos aportes customizados.")
                variacao_aporte = 0.0
                aportes_customizados_str = st.text_area(
                    "Aportes adicionais (mês:valor)",
                    help="Preencha com o mês e o valor, separados por vírgula. Ex: `12:1000, 24:2000, 36:500`"
                )
                aportes_customizados = {}
                try:
                    if aportes_customizados_str:
                        # Substitui ponto e vírgula por vírgula para maior flexibilidade
                        limpo_str = aportes_customizados_str.replace(';', ',')
                        for item in limpo_str.split(','):
                            item_strip = item.strip()
                            if item_strip:
                                mes, valor = item_strip.split(':')
                                aportes_customizados[int(mes.strip())] = float(valor.strip())
                except:
                    st.error("Formato inválido para aportes customizados. Use 'mês:valor' separado por vírgula.")
                    aportes_customizados = {}
            else:
                aporte_mensal = st.number_input("Aporte mensal (R$)", 0.0, step=100.0, key="sim_fixo", help="O valor fixo que você adicionará ao investimento todo mês.")
                variacao_aporte = 0.0
                aportes_customizados = {}

        with col2:
            st.subheader("Período de Simulação")

            opcao_periodo = st.selectbox(
                "Selecione o tipo de período:",
                ["Anos e Meses", "Somente Anos", "Somente Meses"],
                key="sim_select_periodo"
            )

            anos = 0
            meses_adicionais = 0

            if opcao_periodo == "Anos e Meses":
                anos = st.number_input("Anos", 0, step=1, key="sim_anos", help="Duração total da sua simulação, em anos.")
                meses_adicionais = st.number_input("Meses", 0, step=1, key="sim_meses_ad", help="Meses adicionais para a sua simulação.")
            elif opcao_periodo == "Somente Anos":
                anos = st.number_input("Anos", 0, step=1, key="somente_anos_sim", help="Duração total da sua simulação em anos.")
            elif opcao_periodo == "Somente Meses":
                meses_adicionais = st.number_input("Meses", 0, step=1, key="somente_meses_sim", help="Duração total da sua simulação em meses.")

            taxa_juros_tipo = st.radio("Tipo de Taxa de Juros:", ["Fixa", "Variável"], help="Taxa fixa para todo o período ou variável, com alteração mensal.")
            periodo_taxa = st.radio("Periodicidade da Taxa:", ["Anual", "Mensal"], help="Se a taxa informada é anual ou mensal.")

            if taxa_juros_tipo == "Fixa":
                taxa_input = st.number_input(f"Taxa de juros (% {periodo_taxa.lower()})", 0.1, step=0.1, key="sim_taxa_fixa", help="Taxa de juros fixa para o período.") / 100
                variacao_taxa = 0.0
            else:
                taxa_input = st.number_input(f"Taxa inicial (% {periodo_taxa.lower()})", 0.1, step=0.1, key="sim_taxa_var", help="Taxa de juros inicial da simulação.") / 100
                variacao_taxa = st.number_input("Variação da taxa mensal (% do valor anterior)", 0.0, step=0.01, key="sim_var_taxa", help="Percentual de variação da taxa a cada mês.") / 100

        # Conversão da taxa anual para mensal
        taxa_anual = taxa_input if periodo_taxa == "Anual" else (1 + taxa_input)**12 - 1

    # Conversor de tempo
    meses = (anos * 12) + meses_adicionais
    dias = meses * 30  # Aproximação
    st.markdown(f"**Período total:** **{anos}** anos e **{meses_adicionais}** meses, totalizando **{meses}** meses ou aproximadamente **{dias}** dias.")

    incide_ir = st.checkbox("Simular com Imposto de Renda", key="sim_ir", help="Marque se o investimento incidir Imposto de Renda. Será aplicada a tabela regressiva.")

    if st.button("Simular Investimento", key="simular_btn"):
        if meses > 0:
            saldo_bruto, ir_pago, saldo_liquido, df_detalhado, capital_investido = simular_investimento_detalhado(
                valor_inicial,
                tipo_aporte,
                aporte_mensal,
                variacao_aporte,
                aportes_customizados,
                taxa_anual,
                variacao_taxa,
                meses,
                incide_ir
            )

            # Exibição dos resultados
            st.success("✅ **Simulação concluída!**")
            st.subheader("Resumo Financeiro")
            col_res1, col_res2, col_res3, col_res4 = st.columns(4)
            with col_res1:
                st.metric(label="Total Investido", value=format_brl(capital_investido))
            with col_res2:
                st.metric(label="Saldo Bruto", value=format_brl(saldo_bruto))
            with col_res3:
                st.metric(label="Imposto de Renda (IR) Pago", value=format_brl(ir_pago))
            with col_res4:
                st.metric(label="Saldo Líquido", value=format_brl(saldo_liquido))

            st.markdown("---")
            st.subheader("Relatório de Análise Mensal")
            st.markdown("A tabela abaixo mostra o crescimento do seu investimento mês a mês.")
            st.dataframe(df_detalhado)

            st.markdown("---")
            st.subheader("Visualização do Crescimento")

            fig, ax = plt.subplots(figsize=(10, 6))
            ax.plot(df_detalhado['Mês'], df_detalhado['Saldo Bruto (R$)'], label='Saldo Bruto')
            ax.plot(df_detalhado['Mês'], df_detalhado['Capital Acumulado (R$)'], label='Capital Acumulado')
            ax.set_title('Crescimento do Investimento ao Longo do Tempo')
            ax.set_xlabel('Mês')
            ax.set_ylabel('Valor (R$)')
            ax.grid(True)
            ax.legend()
            st.pyplot(fig)

        else:
            st.error("O período de simulação deve ser maior que 0. Por favor, insira anos ou meses para continuar.")

# -----------------------------
# Aba 3 - Conversor de Períodos
# -----------------------------
elif aba == "Conversor de Períodos":
    st.header("Conversor de Períodos")
    st.markdown("Converta anos, meses ou dias e veja o resultado nas outras unidades de tempo.")
    st.info("💡 **Atenção:** A conversão de dias para meses e anos é uma aproximação que considera o mês com 30 dias.")

    col_periodo1, col_periodo2, col_periodo3 = st.columns(3)

    with col_periodo1:
        anos_input = st.number_input("Anos", value=0, min_value=0, help="Insira o número de anos.", key="conv_anos")
    with col_periodo2:
        meses_input = st.number_input("Meses", value=0, min_value=0, help="Insira o número de meses.", key="conv_meses")
    with col_periodo3:
        dias_input = st.number_input("Dias", value=0, min_value=0, help="Insira o número de dias.", key="conv_dias")

    # Lógica de conversão
    anos_result = 0.0
    meses_result = 0.0
    dias_result = 0.0

    if anos_input > 0:
        anos_result = anos_input
        meses_result = anos_input * 12
        dias_result = anos_input * 365.25
    elif meses_input > 0:
        meses_result = meses_input
        anos_result = meses_input / 12
        dias_result = meses_input * 30
    elif dias_input > 0:
        dias_result = dias_input
        meses_result = dias_input / 30
        anos_result = meses_result / 12

    st.subheader("Resultados da Conversão")
    st.metric("Anos", f"{anos_result:.2f}")
    st.metric("Meses", f"{meses_result:.2f}")
    st.metric("Dias", f"{dias_result:.2f}")

# -----------------------------
# Aba 4 - Conversor de Taxas
# -----------------------------
elif aba == "Conversor de Taxas de Juros":
    st.header("Conversor de Taxas de Juros")
    st.markdown("Converta uma taxa de juros anual para mensal e vice-versa.")

    col_taxa1, col_taxa2 = st.columns(2)

    with col_taxa1:
        st.subheader("Anual para Mensal")
        taxa_anual_input = st.number_input("Taxa Anual (%)", min_value=0.0, step=0.1, key="anual_para_mensal", help="Insira a taxa anual que deseja converter para mensal.")
        if taxa_anual_input > 0:
            taxa_anual_decimal = taxa_anual_input / 100
            taxa_mensal_convertida = (1 + taxa_anual_decimal)**(1/12) - 1
            st.metric("Taxa Mensal Equivalente", f"{taxa_mensal_convertida:.4%}")

    with col_taxa2:
        st.subheader("Mensal para Anual")
        taxa_mensal_input = st.number_input("Taxa Mensal (%)", min_value=0.0, step=0.1, key="mensal_para_anual", help="Insira a taxa mensal que deseja converter para anual.")
        if taxa_mensal_input > 0:
            taxa_mensal_decimal = taxa_mensal_input / 100
            taxa_anual_convertida = (1 + taxa_mensal_decimal)**12 - 1
            st.metric("Taxa Anual Equivalente", f"{taxa_anual_convertida:.4%}")

# -----------------------------
# Aba 5 - SAC x Tabela Price
# -----------------------------
elif aba == "SAC x Tabela Price":
    st.header("Análise Comparativa: SAC vs. Tabela Price")
    st.markdown("Compare a diferença entre os sistemas de amortização para o seu financiamento.")

    with st.expander("Configurar o Financiamento"):
        col_price1, col_price2 = st.columns(2)
        with col_price1:
            principal_total = st.number_input("Valor do Imóvel/Bem (R$)", min_value=1000.0, step=1000.0, key="vlr_bem", help="Valor total do bem que você deseja financiar.")
        with col_price2:
            entrada = st.number_input("Valor de Entrada (R$)", min_value=0.0, step=1000.0, key="vlr_entrada", help="Valor pago à vista, que será subtraído do valor total.")

        col_price3, col_price4 = st.columns(2)
        with col_price3:
            taxa_anual = st.number_input("Taxa de Juros Anual (%)", min_value=0.1, step=0.1, key="price_taxa", help="Taxa anual do seu financiamento.") / 100
        with col_price4:
            meses_totais = st.number_input("Período (meses)", min_value=12, step=12, key="price_meses", help="Duração total do seu financiamento em meses.")

    st.markdown("---")

    with st.expander("Configurar Amortizações Extraordinárias (Opcional)"):
        st.info("Use este campo para simular pagamentos extras que abatem o saldo devedor.")
        col_amort1, col_amort2 = st.columns(2)
        with col_amort1:
            amortizacao_extra_valor = st.number_input("Valor da Amortização Extraordinária (R$)", min_value=0.0, step=100.0, key="amort_valor", help="Valor que você deseja pagar extra.")
        with col_amort2:
            amortizacao_extra_meses_str = st.text_input("Meses para as amortizações (ex: 12, 24, 36)", "", key="amort_meses", help="Liste os meses em que o valor acima será pago, separados por vírgula.")

    # Processa os meses de amortização
    meses_extra_amort = []
    if amortizacao_extra_meses_str:
        try:
            meses_extra_amort = [int(m.strip()) for m in amortizacao_extra_meses_str.split(',')]
        except ValueError:
            st.error("Por favor, insira os meses de amortização separados por vírgula (ex: 12, 24, 36).")
            meses_extra_amort = []


    taxa_mensal = (1 + taxa_anual)**(1/12) - 1

    principal_liquido = principal_total - entrada

    if st.button("Simular Amortização", key="simular_amortizacao_btn"):

        df_sac, juros_sac, parcelas_sac = calcular_sac(principal_liquido, taxa_mensal, meses_totais, amortizacao_extra_valor, meses_extra_amort)
        df_price, juros_price, parcelas_price = calcular_price(principal_liquido, taxa_mensal, meses_totais, amortizacao_extra_valor, meses_extra_amort)

        st.subheader("Resumo dos Custos Totais")
        col_metrics_sac, col_metrics_price = st.columns(2)

        with col_metrics_sac:
            st.metric(label="Total Pago (SAC)", value=format_brl(parcelas_sac))
            st.metric(label="Juros Totais Pagos (SAC)", value=format_brl(juros_sac))

        with col_metrics_price:
            st.metric(label="Total Pago (Tabela Price)", value=format_brl(parcelas_price))
            st.metric(label="Juros Totais Pagos (Tabela Price)", value=format_brl(juros_price))

        st.markdown("---")
        st.subheader("Resultados Detalhados")

        col_sac, col_price = st.columns(2)
        with col_sac:
            st.subheader("Tabela SAC")
            st.dataframe(df_sac.style.format({
                'Juros': format_brl,
                'Amortização': format_brl,
                'Parcela': format_brl,
                'Saldo Devedor': format_brl
            }))

        with col_price:
            st.subheader("Tabela Price")
            st.dataframe(df_price.style.format({
                'Juros': format_brl,
                'Amortização': format_brl,
                'Parcela': format_brl,
                'Saldo Devedor': format_brl
            }))

        st.markdown("---")
        st.subheader("Análise Gráfica")

        tab_parcela, tab_saldo = st.tabs(["Comparação de Parcelas", "Comparação do Saldo Devedor"])

        with tab_parcela:
            # DataFrame para o gráfico de linhas das parcelas
            df_grafico_parcelas = pd.DataFrame({
                'Parcela (Tabela Price)': df_price['Parcela'],
                'Parcela (SAC)': df_sac['Parcela']
            })
            st.line_chart(df_grafico_parcelas)

        with tab_saldo:
            # DataFrame para o gráfico de linhas do saldo devedor
            df_grafico_saldo = pd.DataFrame({
                'Saldo Devedor (Tabela Price)': df_price['Saldo Devedor'],
                'Saldo Devedor (SAC)': df_sac['Saldo Devedor']
            })
            st.line_chart(df_grafico_saldo)
