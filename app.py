import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, time
from zoneinfo import ZoneInfo

# ============================================================
# BIST PAPER TRADING BOT
# Gerçek piyasa verisi + 100.000 TL sanal para
# GERÇEK EMİR GÖNDERMEZ
# ============================================================

st.set_page_config(
    page_title="BIST AI Trading Bot",
    page_icon="📈",
    layout="wide"
)

# -----------------------------
# AYARLAR
# -----------------------------

STARTING_CASH = 100_000.0

# İşlem başına kullanılabilecek maksimum sermaye
MAX_POSITION_PERCENT = 0.15

# Stop / Take Profit
STOP_LOSS = 0.025
TAKE_PROFIT = 0.05

# Simülasyon işlem maliyeti
SIMULATED_COST = 0.0015

# Otomatik tarama
REFRESH_SECONDS = 30

# BIST hisseleri
SYMBOLS = {
    "THYAO": "THYAO.IS",
    "ASELS": "ASELS.IS",
    "TUPRS": "TUPRS.IS",
    "BIMAS": "BIMAS.IS",
    "AKBNK": "AKBNK.IS",
    "GARAN": "GARAN.IS",
    "ISCTR": "ISCTR.IS",
    "EREGL": "EREGL.IS",
    "KCHOL": "KCHOL.IS",
    "SAHOL": "SAHOL.IS",
    "TCELL": "TCELL.IS",
    "FROTO": "FROTO.IS",
    "TOASO": "TOASO.IS",
    "SISE": "SISE.IS",
    "YKBNK": "YKBNK.IS",
    "PETKM": "PETKM.IS",
    "PGSUS": "PGSUS.IS",
    "TAVHL": "TAVHL.IS",
    "KOZAL": "KOZAL.IS",
    "HEKTS": "HEKTS.IS",
}

# -----------------------------
# SESSION STATE
# -----------------------------

if "cash" not in st.session_state:
    st.session_state.cash = STARTING_CASH

if "positions" not in st.session_state:
    st.session_state.positions = {}

if "trades" not in st.session_state:
    st.session_state.trades = []

if "bot_active" not in st.session_state:
    st.session_state.bot_active = False

if "prices" not in st.session_state:
    st.session_state.prices = {}

if "signals" not in st.session_state:
    st.session_state.signals = {}

if "last_update" not in st.session_state:
    st.session_state.last_update = None


# -----------------------------
# BIST SEANS KONTROLÜ
# -----------------------------

def market_open():
    now = datetime.now(ZoneInfo("Europe/Istanbul"))

    # Pazartesi=0 ... Pazar=6
    if now.weekday() >= 5:
        return False

    current = now.time()

    # BIST için basitleştirilmiş ana seans kontrolü
    return time(10, 0) <= current <= time(18, 10)


# -----------------------------
# VERİ ÇEKME
# -----------------------------

@st.cache_data(ttl=20)
def get_stock_data(symbol):

    try:
        df = yf.download(
            symbol,
            period="5d",
            interval="5m",
            progress=False,
            auto_adjust=False,
            threads=False
        )

        if df is None or df.empty:
            return None

        # Bazı yfinance sürümlerinde MultiIndex geliyor
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Close", "Volume"]

        for col in required:
            if col not in df.columns:
                return None

        df = df[required].dropna()

        if len(df) < 50:
            return None

        return df

    except Exception:
        return None


# -----------------------------
# TEKNİK İNDİKATÖRLER
# -----------------------------

def calculate_indicators(df):

    data = df.copy()

    data["EMA9"] = data["Close"].ewm(span=9, adjust=False).mean()
    data["EMA21"] = data["Close"].ewm(span=21, adjust=False).mean()

    delta = data["Close"].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    data["RSI"] = 100 - (100 / (1 + rs))

    data["VOL_AVG"] = data["Volume"].rolling(20).mean()

    return data.dropna()


# -----------------------------
# SİNYAL MOTORU
# -----------------------------

def calculate_signal(data):

    if data is None or len(data) < 30:
        return "BEKLE"

    last = data.iloc[-1]
    previous = data.iloc[-2]

    price = float(last["Close"])
    ema9 = float(last["EMA9"])
    ema21 = float(last["EMA21"])
    rsi = float(last["RSI"])

    volume = float(last["Volume"])
    avg_volume = float(last["VOL_AVG"])

    # AL koşulları
    bullish_cross = (
        previous["EMA9"] <= previous["EMA21"]
        and ema9 > ema21
    )

    trend_up = ema9 > ema21
    healthy_rsi = 45 <= rsi <= 68
    volume_ok = volume >= avg_volume

    buy_score = 0

    if bullish_cross:
        buy_score += 2

    if trend_up:
        buy_score += 1

    if healthy_rsi:
        buy_score += 1

    if volume_ok:
        buy_score += 1

    # SAT koşulları
    bearish_cross = (
        previous["EMA9"] >= previous["EMA21"]
        and ema9 < ema21
    )

    if bearish_cross or rsi >= 75:
        return "SAT"

    if buy_score >= 4:
        return "AL"

    return "BEKLE"


# -----------------------------
# SANAL ALIŞ
# -----------------------------

def buy_stock(ticker, price):

    if ticker in st.session_state.positions:
        return

    if price <= 0:
        return

    available = st.session_state.cash

    budget = min(
        available,
        STARTING_CASH * MAX_POSITION_PERCENT
    )

    if budget < price:
        return

    quantity = int(budget / price)

    if quantity <= 0:
        return

    gross = quantity * price
    cost = gross * SIMULATED_COST
    total = gross + cost

    if total > st.session_state.cash:
        return

    st.session_state.cash -= total

    st.session_state.positions[ticker] = {
        "quantity": quantity,
        "buy_price": price,
        "buy_time": datetime.now(
            ZoneInfo("Europe/Istanbul")
        ).strftime("%Y-%m-%d %H:%M:%S")
    }

    st.session_state.trades.append({
        "Zaman": datetime.now(
            ZoneInfo("Europe/Istanbul")
        ).strftime("%Y-%m-%d %H:%M:%S"),
        "Hisse": ticker,
        "İşlem": "AL",
        "Fiyat": price,
        "Adet": quantity,
        "K/Z": 0.0
    })


# -----------------------------
# SANAL SATIŞ
# -----------------------------

def sell_stock(ticker, price, reason="SİNYAL"):

    if ticker not in st.session_state.positions:
        return

    position = st.session_state.positions[ticker]

    quantity = position["quantity"]
    buy_price = position["buy_price"]

    gross = quantity * price
    cost = gross * SIMULATED_COST

    received = gross - cost

    st.session_state.cash += received

    profit = (
        (price - buy_price) * quantity
        - cost
        - (buy_price * quantity * SIMULATED_COST)
    )

    st.session_state.trades.append({
        "Zaman": datetime.now(
            ZoneInfo("Europe/Istanbul")
        ).strftime("%Y-%m-%d %H:%M:%S"),
        "Hisse": ticker,
        "İşlem": f"SAT ({reason})",
        "Fiyat": price,
        "Adet": quantity,
        "K/Z": profit
    })

    del st.session_state.positions[ticker]


# -----------------------------
# POZİSYON KONTROLÜ
# -----------------------------

def manage_position(ticker, price, signal):

    if ticker not in st.session_state.positions:
        return

    position = st.session_state.positions[ticker]

    buy_price = position["buy_price"]

    change = (price - buy_price) / buy_price

    # Stop loss
    if change <= -STOP_LOSS:
        sell_stock(ticker, price, "STOP LOSS")
        return

    # Take profit
    if change >= TAKE_PROFIT:
        sell_stock(ticker, price, "TAKE PROFIT")
        return

    # Teknik SAT
    if signal == "SAT":
        sell_stock(ticker, price, "SİNYAL")


# -----------------------------
# PORTFÖY HESABI
# -----------------------------

def portfolio_value():

    total = st.session_state.cash

    for ticker, position in st.session_state.positions.items():

        price = st.session_state.prices.get(ticker)

        if price:
            total += position["quantity"] * price

    return total


def unrealized_profit():

    profit = 0.0

    for ticker, position in st.session_state.positions.items():

        price = st.session_state.prices.get(ticker)

        if price:

            profit += (
                price - position["buy_price"]
            ) * position["quantity"]

    return profit


# -----------------------------
# BOT TARAMASI
# -----------------------------

def run_bot():

    for ticker, yf_symbol in SYMBOLS.items():

        data = get_stock_data(yf_symbol)

        if data is None:
            continue

        data = calculate_indicators(data)

        if data.empty:
            continue

        price = float(data["Close"].iloc[-1])

        signal = calculate_signal(data)

        st.session_state.prices[ticker] = price
        st.session_state.signals[ticker] = signal

        if st.session_state.bot_active and market_open():

            manage_position(
                ticker,
                price,
                signal
            )

            # Yeni AL
            if (
                signal == "AL"
                and ticker not in st.session_state.positions
            ):
                buy_stock(ticker, price)

    st.session_state.last_update = datetime.now(
        ZoneInfo("Europe/Istanbul")
    )


# ============================================================
# ARAYÜZ
# ============================================================

st.title("📈 BIST Otomatik Trading Bot")

st.caption(
    "Gerçek piyasa verisi • 100.000 TL sanal bakiye • "
    "Gerçek emir göndermez"
)

# -----------------------------
# SIDEBAR
# -----------------------------

with st.sidebar:

    st.header("⚙️ Bot Kontrol")

    if st.button(
        "🟢 BOTU BAŞLAT",
        use_container_width=True
    ):
        st.session_state.bot_active = True

    if st.button(
        "🔴 BOTU DURDUR",
        use_container_width=True
    ):
        st.session_state.bot_active = False

    st.divider()

    st.write(
        "Bot durumu:",
        "🟢 AKTİF"
        if st.session_state.bot_active
        else "🔴 DURDU"
    )

    st.write(
        "BIST:",
        "🟢 AÇIK"
        if market_open()
        else "🔴 KAPALI"
    )

    st.divider()

    st.subheader("Risk Ayarları")

    st.write(
        f"İşlem başına maksimum: "
        f"%{MAX_POSITION_PERCENT * 100:.0f}"
    )

    st.write(
        f"Stop Loss: "
        f"%{STOP_LOSS * 100:.1f}"
    )

    st.write(
        f"Take Profit: "
        f"%{TAKE_PROFIT * 100:.1f}"
    )


# -----------------------------
# OTOMATİK GÜNCELLEME
# -----------------------------

@st.fragment(run_every=REFRESH_SECONDS)
def live_bot():

    run_bot()

    # -------------------------
    # ÖZET
    # -------------------------

    total = portfolio_value()
    profit = total - STARTING_CASH

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "💰 Nakit",
        f"{st.session_state.cash:,.2f} TL"
    )

    col2.metric(
        "📊 Portföy",
        f"{total:,.2f} TL",
        f"{profit:+,.2f} TL"
    )

    col3.metric(
        "📈 Açık Pozisyon",
        len(st.session_state.positions)
    )

    col4.metric(
        "🔄 İşlem",
        len(st.session_state.trades)
    )

    st.divider()

    # -------------------------
    # HİSSELER
    # -------------------------

    rows = []

    for ticker in SYMBOLS:

        price = st.session_state.prices.get(ticker)
        signal = st.session_state.signals.get(
            ticker,
            "BEKLE"
        )

        if price is None:
            continue

        position = st.session_state.positions.get(ticker)

        if position:

            quantity = position["quantity"]
            buy_price = position["buy_price"]

            pnl = (
                price - buy_price
            ) * quantity

            status = f"{quantity} adet"

        else:

            pnl = 0
            status = "-"

        rows.append({
            "Hisse": ticker,
            "Fiyat": round(price, 2),
            "Sinyal": signal,
            "Pozisyon": status,
            "K/Z": round(pnl, 2)
        })

    if rows:

        df_display = pd.DataFrame(rows)

        st.subheader("📡 Piyasa Tarayıcı")

        st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True
        )

    # -------------------------
    # POZİSYONLAR
    # -------------------------

    st.subheader("💼 Açık Pozisyonlar")

    if st.session_state.positions:

        positions = []

        for ticker, position in st.session_state.positions.items():

            price = st.session_state.prices.get(
                ticker,
                position["buy_price"]
            )

            qty = position["quantity"]
            buy_price = position["buy_price"]

            pnl = (
                price - buy_price
            ) * qty

            positions.append({
                "Hisse": ticker,
                "Adet": qty,
                "Alış": round(buy_price, 2),
                "Son Fiyat": round(price, 2),
                "K/Z": round(pnl, 2)
            })

        st.dataframe(
            pd.DataFrame(positions),
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info("Şu anda açık pozisyon yok.")

    # -------------------------
    # İŞLEM GEÇMİŞİ
    # -------------------------

    st.subheader("📝 İşlem Geçmişi")

    if st.session_state.trades:

        trades_df = pd.DataFrame(
            st.session_state.trades
        )

        st.dataframe(
            trades_df.iloc[::-1],
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info("Henüz işlem yapılmadı.")

    # -------------------------
    # ALT BİLGİ
    # -------------------------

    if st.session_state.last_update:

        st.caption(
            "Son güncelleme: "
            + st.session_state.last_update.strftime(
                "%H:%M:%S"
            )
        )


live_bot()
