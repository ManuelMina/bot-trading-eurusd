"""
Genera reporte de backtesting con métricas clave.

Métricas incluidas:
    - Win rate total y por tipo (T1/T2/T3)
    - Win rate por ciclo (Normal/Knockout/Sierra/RetailHeaven)
    - P&L acumulado y mensual
    - Drawdown maximo (absoluto y porcentaje)
    - Distribución de confirmaciones
    - Comparativa 2024 vs 2025

Uso:
    python -m reporting.report --year 2024
    python -m reporting.report --year 2025
    python -m reporting.report --compare
"""

import argparse
from pathlib import Path

import pandas as pd

_RESULTS_DIR = Path(__file__).parent / "results"


# ---------------------------------------------------------------------------
# Carga de resultados
# ---------------------------------------------------------------------------

def load_results(year: int) -> pd.DataFrame:
    path = _RESULTS_DIR / f"backtest_{year}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontraron resultados para {year}. "
            f"Ejecuta primero: python -m engine.backtester --year {year}"
        )
    df = pd.read_csv(path, parse_dates=["date", "signal_time"])
    return df


# ---------------------------------------------------------------------------
# Metricas de base
# ---------------------------------------------------------------------------

def _win_rate(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return (df["result"] == "win").mean()


def _max_drawdown(df: pd.DataFrame, initial_capital: float) -> tuple[float, float]:
    """Retorna (drawdown_abs_usd, drawdown_pct) del maximo drawdown."""
    if df.empty:
        return 0.0, 0.0
    capital = pd.Series([initial_capital] + list(df["capital_after"].values))
    rolling_max = capital.cummax()
    drawdown = rolling_max - capital
    max_dd = drawdown.max()
    max_dd_pct = (max_dd / rolling_max[drawdown.idxmax()]) * 100
    return round(max_dd, 2), round(max_dd_pct, 1)


def _profit_factor(df: pd.DataFrame) -> float:
    wins  = df[df["result"] == "win"]["pnl_usd"].sum()
    loss  = abs(df[df["result"] == "loss"]["pnl_usd"].sum())
    return round(wins / loss, 2) if loss > 0 else float("inf")


def _avg_trade(df: pd.DataFrame) -> float:
    return round(df["pnl_usd"].mean(), 2) if not df.empty else 0.0


def _expectancy(df: pd.DataFrame) -> float:
    wr   = _win_rate(df)
    lr   = 1 - wr
    avg_win  = df[df["result"] == "win"]["pnl_usd"].mean()  if (df["result"]=="win").any()  else 0.0
    avg_loss = df[df["result"] == "loss"]["pnl_usd"].mean() if (df["result"]=="loss").any() else 0.0
    return round(wr * avg_win + lr * avg_loss, 2)


# ---------------------------------------------------------------------------
# Reporte de un año
# ---------------------------------------------------------------------------

def print_year_report(df: pd.DataFrame, year: int, initial_capital: float = 1000.0) -> None:
    sep  = "-" * 65
    sep2 = "=" * 65
    print(f"\n{sep2}")
    print(f"  REPORTE DE BACKTESTING {year}")
    print(sep2)

    if df.empty:
        print("  Sin trades.")
        return

    final_cap = df["capital_after"].iloc[-1]
    pnl       = final_cap - initial_capital
    wr        = _win_rate(df) * 100
    max_dd, max_dd_pct = _max_drawdown(df, initial_capital)
    pf        = _profit_factor(df)
    exp       = _expectancy(df)

    total_days = df["date"].nunique()

    print(f"\n  RESUMEN GENERAL")
    print(sep)
    print(f"  Trades totales:     {len(df):<8}  ({total_days} dias con trades)")
    print(f"  Capital inicial:    ${initial_capital:>9,.2f}")
    print(f"  Capital final:      ${final_cap:>9,.2f}  ({pnl:+,.2f} | {100*pnl/initial_capital:+.1f}%)")
    print(f"  Win rate:           {wr:>8.1f}%")
    print(f"  Profit factor:      {pf:>8.2f}  (>1 = profitable)")
    print(f"  Expectancy/trade:   ${exp:>8.2f}")
    print(f"  Max drawdown:       ${max_dd:>8,.2f}  ({max_dd_pct:.1f}%)")

    # Por numero de trade en el dia
    print(f"\n  WIN RATE POR TRADE DEL DIA")
    print(sep)
    for t in [1, 2, 3]:
        sub = df[df["trade_num_day"] == t]
        if sub.empty:
            continue
        wr_t = _win_rate(sub) * 100
        pnl_t = sub["pnl_usd"].sum()
        exp_t = _expectancy(sub)
        be    = 25.0  # break-even a 1:3 RR
        flag  = " [<BREAK-EVEN]" if wr_t < be else ""
        print(f"  T{t}: {len(sub):4d} trades | WR: {wr_t:5.1f}%{flag} | P&L: ${pnl_t:+,.2f} | E/trade: ${exp_t:+.2f}")

    # Por ciclo
    print(f"\n  WIN RATE POR CICLO")
    print(sep)
    for cycle in sorted(df["cycle"].unique()):
        sub = df[df["cycle"] == cycle]
        wr_c = _win_rate(sub) * 100
        pnl_c = sub["pnl_usd"].sum()
        print(f"  {cycle:<15} {len(sub):4d} trades | WR: {wr_c:5.1f}% | P&L: ${pnl_c:+,.2f}")

    # Por confirmaciones
    print(f"\n  CONFIRMACIONES (top combinaciones)")
    print(sep)
    for conf, count in df["confirmations"].value_counts().head(6).items():
        sub = df[df["confirmations"] == conf]
        wr_c = _win_rate(sub) * 100
        print(f"  {conf:<40} {count:4d}  WR: {wr_c:5.1f}%")

    # P&L mensual
    print(f"\n  P&L MENSUAL")
    print(sep)
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
    monthly = df.groupby("month").agg(
        trades   = ("result", "count"),
        wins     = ("result", lambda x: (x == "win").sum()),
        pnl      = ("pnl_usd", "sum"),
    ).reset_index()
    monthly["wr"] = monthly["wins"] / monthly["trades"] * 100

    for _, row in monthly.iterrows():
        bar = "+" * max(0, int(row["pnl"] / 5)) if row["pnl"] >= 0 else "-" * max(0, int(abs(row["pnl"]) / 5))
        print(f"  {row['month']}  {row['trades']:3d}T  WR:{row['wr']:5.1f}%  ${row['pnl']:+8.2f}  {bar}")

    print(f"\n{sep2}\n")


# ---------------------------------------------------------------------------
# Comparativa entre años
# ---------------------------------------------------------------------------

def print_comparison(years: list[int], initial_capital: float = 1000.0) -> None:
    dfs = {}
    for yr in years:
        try:
            dfs[yr] = load_results(yr)
        except FileNotFoundError as e:
            print(f"  [WARN] {e}")

    if len(dfs) < 2:
        print("  Necesitas resultados de al menos 2 anos para comparar.")
        return

    sep  = "-" * 55
    sep2 = "=" * 55
    print(f"\n{sep2}")
    print(f"  COMPARATIVA  {' vs '.join(str(y) for y in sorted(dfs))}")
    print(sep2)

    headers = ["Metrica"] + [str(y) for y in sorted(dfs)]
    rows = []

    for yr, df in sorted(dfs.items()):
        if df.empty:
            continue
        final_cap = df["capital_after"].iloc[-1]
        pnl       = final_cap - initial_capital
        rows.append((yr, {
            "Trades":          len(df),
            "Win rate":        f"{_win_rate(df)*100:.1f}%",
            "P&L USD":         f"${pnl:+,.2f}",
            "Retorno %":       f"{100*pnl/initial_capital:+.1f}%",
            "Profit factor":   f"{_profit_factor(df):.2f}",
            "Expectancy/trade":f"${_expectancy(df):+.2f}",
            "Max drawdown":    f"${_max_drawdown(df, initial_capital)[0]:,.2f} ({_max_drawdown(df, initial_capital)[1]:.1f}%)",
            "T1 WR":           f"{_win_rate(df[df['trade_num_day']==1])*100:.1f}%",
            "T2 WR":           f"{_win_rate(df[df['trade_num_day']==2])*100:.1f}%",
        }))

    metrics = list(rows[0][1].keys())
    col_w   = 22

    print(f"\n  {'Metrica':<25}", end="")
    for yr, _ in rows:
        print(f"{yr:>{col_w}}", end="")
    print()
    print(f"  {sep}")

    for m in metrics:
        print(f"  {m:<25}", end="")
        for _, data in rows:
            print(f"{data.get(m, '-'):>{col_w}}", end="")
        print()

    print(f"\n{sep2}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(description="Reporte de backtesting")
    p.add_argument("--year",    type=int, action="append", dest="years",
                   help="Año a reportar (repetir para multiples)")
    p.add_argument("--compare", action="store_true",
                   help="Mostrar comparativa entre todos los años disponibles")
    p.add_argument("--capital", type=float, default=1000.0,
                   help="Capital inicial USD (default: 1000)")
    return p.parse_args()


if __name__ == "__main__":
    from config import BACKTEST_YEARS
    args  = _parse_args()
    years = args.years or BACKTEST_YEARS

    for yr in years:
        try:
            df = load_results(yr)
            print_year_report(df, yr, initial_capital=args.capital)
        except FileNotFoundError as e:
            print(f"  [WARN] {e}")

    if args.compare or len(years) > 1:
        print_comparison(years, initial_capital=args.capital)
