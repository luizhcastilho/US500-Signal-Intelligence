
import pandas as pd
import numpy as np

REQUIRED = ["timestamp", "open", "high", "low", "close"]

def validate_csv(raw):
    warnings = []
    missing = [c for c in REQUIRED if c not in raw.columns]
    if missing:
        raise ValueError("Colunas ausentes: " + ", ".join(missing))
    df = raw.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    if df["timestamp"].isna().any():
        raise ValueError("Há timestamps inválidos. Use datas reconhecíveis, preferencialmente ISO 8601.")
    for c in ["open","high","low","close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if df[["open","high","low","close"]].isna().any().any():
        raise ValueError("Há preços ausentes ou não numéricos.")
    if (df["high"] < df["low"]).any():
        raise ValueError("Há candles com máxima menor que mínima.")
    if "volume" not in df.columns:
        df["volume"] = np.nan
        warnings.append("Volume não fornecido. O módulo de volume ficará indisponível.")
    else:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")
    if len(df) > 2:
        gaps = df.index.to_series().diff().dropna()
        if (gaps > pd.Timedelta(minutes=2)).any():
            warnings.append("Foram encontrados intervalos maiores que 2 minutos. Confirme se os dados são M1 e se as lacunas são esperadas.")
    return df, warnings

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - (100/(1+rs))

def macd(s):
    line = ema(s,12) - ema(s,26)
    signal = ema(line,9)
    return line, signal, line-signal

def atr(df, n=14):
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"]-df["low"],
        (df["high"]-prev).abs(),
        (df["low"]-prev).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def adx(df, n=14):
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    a = atr(df, n).replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1/n, adjust=False).mean() / a
    minus_di = 100 * minus_dm.ewm(alpha=1/n, adjust=False).mean() / a
    dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0,np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean(), plus_di, minus_di

def resample_ohlc(df, rule):
    agg = {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    return df.resample(rule, label="right", closed="right").agg(agg).dropna(subset=["open","high","low","close"])

def enrich(frame):
    x = frame.copy()
    for n in [9,21,50,200]:
        x[f"ema{n}"] = ema(x["close"], n)
    x["rsi"] = rsi(x["close"])
    x["macd"], x["macd_signal"], x["macd_hist"] = macd(x["close"])
    x["atr"] = atr(x)
    x["atr_pct"] = x["atr"] / x["close"] * 100
    x["adx"], x["plus_di"], x["minus_di"] = adx(x)
    x["range"] = x["high"]-x["low"]
    x["body"] = (x["close"]-x["open"]).abs()
    x["body_ratio"] = x["body"] / x["range"].replace(0,np.nan)
    x["prev_high"] = x["high"].shift(1)
    x["prev_low"] = x["low"].shift(1)
    # Rejeição simples, não é classificação avançada de candle.
    upper = x["high"] - x[["open","close"]].max(axis=1)
    lower = x[["open","close"]].min(axis=1) - x["low"]
    x["bull_rejection"] = (lower > x["body"]*1.5) & (x["close"] > x["open"])
    x["bear_rejection"] = (upper > x["body"]*1.5) & (x["close"] < x["open"])
    return x

def prepare_data(m1):
    # Resample a partir de candles M1; H1/M15/M5 usam apenas barras fechadas.
    m5 = enrich(resample_ohlc(m1, "5min"))
    m15 = enrich(resample_ohlc(m1, "15min"))
    h1 = enrich(resample_ohlc(m1, "1h"))

    h1["h1_trend"] = np.select(
        [(h1["ema50"] > h1["ema200"]) & (h1["close"] > h1["ema50"]),
         (h1["ema50"] < h1["ema200"]) & (h1["close"] < h1["ema50"])],
        ["ALTA","BAIXA"], default="NEUTRA"
    )
    m5["m5_trend"] = np.select(
        [(m5["ema9"] > m5["ema21"]) & (m5["close"] > m5["ema21"]),
         (m5["ema9"] < m5["ema21"]) & (m5["close"] < m5["ema21"])],
        ["ALTA","BAIXA"], default="NEUTRA"
    )
    # Reindex com último candle fechado disponível. Sem olhar candles futuros.
    m15["h1_trend"] = h1["h1_trend"].reindex(m15.index, method="ffill")
    m15["m5_trend"] = m5["m5_trend"].reindex(m15.index, method="ffill")
    m15["market_state"] = np.where(m15["adx"] >= 20, "TENDÊNCIA", "FRACO/LATERAL")
    return m15.dropna(subset=["ema50","rsi","macd_hist","atr","adx"])

def generate_signals(data, min_score=85):
    x = data.copy()
    rows = []
    for i, (ts, r) in enumerate(x.iterrows()):
        call = 0
        put = 0
        call_reasons, put_reasons = [], []

        # H1: contexto de tendência
        if r["h1_trend"] == "ALTA":
            call += 15; call_reasons.append("Tendência H1 de alta")
        elif r["h1_trend"] == "BAIXA":
            put += 15; put_reasons.append("Tendência H1 de baixa")

        # M15: médias alinhadas
        if r["ema9"] > r["ema21"] > r["ema50"] and r["close"] > r["ema200"]:
            call += 15; call_reasons.append("Médias M15 alinhadas para alta")
        elif r["ema9"] < r["ema21"] < r["ema50"] and r["close"] < r["ema200"]:
            put += 15; put_reasons.append("Médias M15 alinhadas para baixa")

        # Momentum
        if r["rsi"] > 52 and r["macd_hist"] > 0:
            call += 15; call_reasons.append("Momentum comprador confirmado")
        elif r["rsi"] < 48 and r["macd_hist"] < 0:
            put += 15; put_reasons.append("Momentum vendedor confirmado")

        # ADX e direção
        if r["adx"] >= 20 and r["plus_di"] > r["minus_di"]:
            call += 10; call_reasons.append("Força direcional compradora")
        elif r["adx"] >= 20 and r["minus_di"] > r["plus_di"]:
            put += 10; put_reasons.append("Força direcional vendedora")

        # Price action: rompimento do candle anterior ou rejeição
        if (r["close"] > r["prev_high"]) or bool(r["bull_rejection"]):
            call += 20; call_reasons.append("Gatilho de price action comprador")
        if (r["close"] < r["prev_low"]) or bool(r["bear_rejection"]):
            put += 20; put_reasons.append("Gatilho de price action vendedor")

        if r["m5_trend"] == "ALTA":
            call += 10; call_reasons.append("Confirmação M5 compradora")
        elif r["m5_trend"] == "BAIXA":
            put += 10; put_reasons.append("Confirmação M5 vendedora")

        # Volatilidade: faixa inicial relativa, será calibrada com dados do ativo.
        if pd.notna(r["atr_pct"]) and 0.015 <= r["atr_pct"] <= 0.35:
            call += 10; put += 10
            call_reasons.append("Volatilidade dentro da faixa inicial")
            put_reasons.append("Volatilidade dentro da faixa inicial")

        # Penalidade por candle de impulso muito grande: evita perseguir movimento.
        oversized = pd.notna(r["atr"]) and r["range"] > 2.2*r["atr"]
        # Bloqueio de sinais contra H1 e divergência severa.
        call_block = (r["h1_trend"] == "BAIXA") or oversized or (r["adx"] < 15)
        put_block = (r["h1_trend"] == "ALTA") or oversized or (r["adx"] < 15)

        direction, score, reasons = "AGUARDAR", max(call,put), []
        if call >= min_score and call > put and not call_block:
            direction, score, reasons = "CALL", call, call_reasons
        elif put >= min_score and put > call and not put_block:
            direction, score, reasons = "PUT", put, put_reasons
        else:
            reasons = ["Filtros de qualidade não foram todos atendidos"]
            if oversized: reasons.append("Bloqueio: candle muito grande em relação ao ATR")
            if r["adx"] < 15: reasons.append("Bloqueio: força de tendência insuficiente")
            if direction == "AGUARDAR" and call_block and put_block:
                reasons.append("Bloqueio por contexto H1 ou volatilidade")

        rows.append({"signal":direction, "score":int(score), "reasons":"; ".join(reasons)})
    return pd.DataFrame(rows, index=x.index)

def backtest_signals(data, signals, payout=0.80):
    # Entrada no próximo candle M15 e liquidação após 1 candle M15.
    out = signals.copy()
    out["entry_price"] = data["open"].shift(-1)
    out["expiry_price"] = data["close"].shift(-1)
    out["entry_time"] = pd.Series(data.index, index=data.index).shift(-1)
    out["outcome"] = "PENDING"
    call_win = (out["signal"] == "CALL") & (out["expiry_price"] > out["entry_price"])
    put_win = (out["signal"] == "PUT") & (out["expiry_price"] < out["entry_price"])
    tie = out["expiry_price"] == out["entry_price"]
    active = out["signal"].isin(["CALL","PUT"])
    out.loc[active & (call_win | put_win), "outcome"] = "WIN"
    out.loc[active & tie, "outcome"] = "TIE"
    out.loc[active & ~(call_win | put_win) & ~tie & out["expiry_price"].notna(), "outcome"] = "LOSS"
    out.loc[out["expiry_price"].isna(), "outcome"] = "PENDING"
    out["payout_assumption"] = payout
    return out
