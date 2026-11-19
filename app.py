
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from strategy import prepare_data, generate_signals, backtest_signals, validate_csv

st.set_page_config(page_title="US 500 Signal Intelligence", page_icon="📈", layout="wide")

st.title("📈 US 500 Signal Intelligence")
st.caption("MVP 1.0 • Análise M15 • Confirmação H1/M5 • Expiração de referência: 15 minutos")

with st.sidebar:
    st.header("Configurações")
    min_score = st.slider("Pontuação mínima do sinal", 70, 100, 85, 1)
    payout = st.slider("Payout hipotético (%)", 50, 95, 80, 1) / 100
    st.caption("O payout é usado apenas para estimar o ponto de equilíbrio. Confira o payout real da operação.")
    st.divider()
    st.subheader("Dados")
    uploaded = st.file_uploader("Importar candles CSV", type=["csv"])
    st.caption("Colunas obrigatórias: timestamp, open, high, low, close. Volume é opcional. Prefira dados M1 para formar H1/M15/M5.")

st.info("Este MVP não se conecta à IQ Option, não executa operações e não gera cotações ao vivo. Os sinais só são calculados sobre os dados importados.")

if uploaded is None:
    st.subheader("Como começar")
    st.markdown("""
    1. Exporte ou obtenha candles históricos do instrumento US 500 que corresponda exatamente ao produto exibido na sua IQ Option.
    2. Salve em CSV com as colunas `timestamp, open, high, low, close` e, se disponível, `volume`.
    3. Importe o arquivo na barra lateral.
    4. Confira o fuso horário, a origem dos preços e se os candles estão completos.

    **Importante:** candles de um índice à vista, futuro, CFD ou outro provedor podem divergir do preço de liquidação da opção na IQ Option.
    """)
    st.stop()

try:
    raw = pd.read_csv(uploaded)
    df, warnings = validate_csv(raw)
    if warnings:
        for w in warnings:
            st.warning(w)
    if len(df) < 250:
        st.warning("A amostra é pequena. Para calcular médias longas e testar a estratégia, prefira pelo menos 250 candles M1 e idealmente várias semanas de histórico.")
    data = prepare_data(df)
    signals = generate_signals(data, min_score=min_score)
    results = backtest_signals(data, signals, payout=payout)
except Exception as e:
    st.error(f"Não foi possível processar o arquivo: {e}")
    st.stop()

if data.empty:
    st.error("Não há dados suficientes para análise.")
    st.stop()

last = data.iloc[-1]
last_sig = signals.iloc[-1] if len(signals) else None

c1, c2, c3, c4 = st.columns(4)
c1.metric("Candles M1", f"{len(df):,}")
c2.metric("Último fechamento", f"{last['close']:.2f}")
c3.metric("Tendência H1", str(last.get("h1_trend", "—")))
c4.metric("Condição M15", str(last.get("market_state", "—")))

st.divider()
left, right = st.columns([1.6, 1])

with left:
    st.subheader("US 500 — gráfico M15")
    chart = data.tail(160)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=chart.index, open=chart["open"], high=chart["high"],
        low=chart["low"], close=chart["close"], name="M15"
    ))
    for col, name in [("ema9","EMA 9"),("ema21","EMA 21"),("ema50","EMA 50"),("ema200","EMA 200")]:
        if col in chart:
            fig.add_trace(go.Scatter(x=chart.index, y=chart[col], name=name, mode="lines"))
    fig.update_layout(height=520, xaxis_rangeslider_visible=False, margin=dict(l=10,r=10,t=25,b=10))
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Última leitura")
    if last_sig is not None and last_sig["signal"] in ("CALL", "PUT"):
        st.metric("Sinal no último candle fechado", last_sig["signal"], f"Pontuação {int(last_sig['score'])}/100")
        st.write(f"**Horário do candle:** {signals.index[-1]}")
        st.write("**Expiração de referência:** 15 minutos")
        st.write("**Motivos:**")
        for reason in last_sig["reasons"]:
            st.write(f"- {reason}")
    else:
        st.metric("Sinal no último candle", "AGUARDAR")
        st.write("Nenhuma oportunidade passou por todos os filtros na última barra.")
        if last_sig is not None:
            st.write(f"Pontuação observada: {int(last_sig['score'])}/100")
            for reason in last_sig["reasons"]:
                st.write(f"- {reason}")

st.divider()
st.subheader("Histórico de sinais e simulação")
valid = results[results["signal"].isin(["CALL","PUT"])].copy()
if valid.empty:
    st.warning("Nenhum sinal qualificado foi encontrado nesta amostra. Isso pode ser correto: a estratégia foi desenhada para ser seletiva.")
else:
    settled = valid[valid["outcome"].isin(["WIN","LOSS","TIE"])]
    wins = int((settled["outcome"] == "WIN").sum())
    losses = int((settled["outcome"] == "LOSS").sum())
    ties = int((settled["outcome"] == "TIE").sum())
    decided = wins + losses
    hit = wins / decided * 100 if decided else 0
    breakeven = 1/(1+payout)*100
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Sinais qualificados", len(valid))
    m2.metric("Taxa de acerto (sem empates)", f"{hit:.1f}%" if decided else "—")
    m3.metric("Ponto de equilíbrio", f"{breakeven:.1f}%")
    m4.metric("WIN / LOSS / EMPATE", f"{wins} / {losses} / {ties}")
    st.caption("Backtest simplificado: sinal após fechamento M15, entrada no próximo candle M15 e avaliação após um candle. Não inclui payout variável, latência, spread, regras de liquidação ou diferenças entre provedores.")
    show = valid.reset_index().rename(columns={"index":"signal_time"})
    cols = [c for c in ["signal_time","signal","score","entry_price","expiry_price","outcome","reasons"] if c in show.columns]
    st.dataframe(show[cols].tail(100), use_container_width=True, hide_index=True)
    csv = show[cols].to_csv(index=False).encode("utf-8")
    st.download_button("Baixar histórico de sinais (CSV)", csv, "us500_sinais.csv", "text/csv")

st.divider()
st.subheader("Integridade e limites")
st.markdown("""
- A pontuação é um filtro técnico experimental, **não uma probabilidade de acerto**.
- O robô só deve ser avaliado com dados do mesmo instrumento e fonte de preço usados para liquidar a opção.
- Não há Martingale nem execução automática.
- Antes de qualquer uso financeiro, faça teste histórico fora da amostra e acompanhamento em demonstração.
""")
