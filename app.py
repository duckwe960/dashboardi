import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO

# =========================
# Dados iniciais
# =========================
caixa_inicial = 1250.00
receitas = {
    "Julho": 0.00,
    "Agosto": 832.00,
    "Setembro": 650.00,
    "Outubro": 650.00,
    "Novembro": 0.00,
    "Dezembro": 0.00
}
custo_mensal = 450.00
custos_trimestrais_meses = ["Setembro", "Dezembro"]
custo_trimestral = 150.00
custos_inesperados = {"Dezembro": 210.00}

# =========================
# Painel de parâmetros
# =========================
st.title(" Dashboard Financeiro - Argos Consultoria")
st.sidebar.header("Configurações da Reserva")

valor_reserva = st.sidebar.number_input(
    "Valor mensal da reserva (R$)", min_value=0.0, value=100.0, step=50.0)
meses_reserva = st.sidebar.multiselect(
    "Meses para recolher reserva",
    list(receitas.keys()),
    default=["Setembro", "Outubro", "Novembro"]
)

# =========================
# Cálculo do fluxo de caixa
# =========================
saldo_inicial = caixa_inicial
dados = []

for mes in receitas.keys():
    receita = receitas[mes]
    despesa_mensal = custo_mensal
    despesa_trimestral = custo_trimestral if mes in custos_trimestrais_meses else 0.00
    despesa_inesperada = custos_inesperados.get(mes, 0.00)

    total_despesas = despesa_mensal + despesa_trimestral + despesa_inesperada
    reserva = valor_reserva if mes in meses_reserva else 0.00

    saldo_final = saldo_inicial + receita - total_despesas - reserva

    dados.append({
        "Mês": mes,
        "Receita (R$)": receita,
        "Despesa mensal (R$)": despesa_mensal,
        "Despesa trimestral (R$)": despesa_trimestral,
        "Despesa inesperada (R$)": despesa_inesperada,
        "Total despesas (R$)": total_despesas,
        "Reserva (R$)": reserva,
        "Saldo inicial (R$)": saldo_inicial,
        "Saldo final (R$)": saldo_final
    })

    saldo_inicial = saldo_final

df = pd.DataFrame(dados)

# =========================
# Exibição no Dashboard
# =========================
st.subheader(" Fluxo de Caixa Projetado (Jul–Dez 2025)")
colunas_numericas = df.select_dtypes(include=['float64', 'int64']).columns
st.dataframe(df.style.format({col: "{:,.2f}" for col in colunas_numericas}))

# =========================
# Botão para exportar Excel
# =========================
output = BytesIO()
df.to_excel(output, index=False)
excel_data = output.getvalue()
st.download_button(
    label=" Baixar planilha em Excel",
    data=excel_data,
    file_name="fluxo_caixa_argos.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# =========================
# Gráfico de evolução do saldo
# =========================
st.subheader(" Evolução do Saldo de Caixa")
plt.figure(figsize=(8, 4))
plt.plot(df["Mês"], df["Saldo final (R$)"], marker='o', label="Saldo Final")
plt.plot(df["Mês"], df["Saldo inicial (R$)"],
         linestyle='--', label="Saldo Inicial")
plt.xticks(rotation=45)
plt.ylabel("R$ Saldo")
plt.legend()
plt.grid(True, linestyle="--", alpha=0.6)
st.pyplot(plt)

# =========================
# Gráfico de composição de despesas
# =========================
st.subheader(" Composição das Despesas por Mês")
df_despesas = df[[
    "Mês", "Despesa mensal (R$)", "Despesa trimestral (R$)", "Despesa inesperada (R$)", "Reserva (R$)"]]
df_despesas.set_index("Mês", inplace=True)
df_despesas.plot(kind="bar", stacked=True, figsize=(8, 4))
plt.ylabel("R$ Valor")
plt.xticks(rotation=45)
plt.title("Despesas e Reservas")
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
st.pyplot(plt)
