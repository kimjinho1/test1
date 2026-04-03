"""Example momentum strategy.

Every strategy must expose a `run(context) -> dict` function.
context = {"ticker": str, "ohlcv": list, "portfolio": dict, "timestamp": datetime}
Returns Signal = {"action": "BUY"|"SELL"|"HOLD", "ticker": str, "confidence": float, "reason": str}
"""


def run(context: dict) -> dict:
    ohlcv = context.get("ohlcv", [])
    ticker = context["ticker"]

    if len(ohlcv) < 20:
        return {"action": "HOLD", "ticker": ticker, "confidence": 0.0, "reason": "데이터 부족 (20봉 미만)"}

    # Simple momentum: compare current close to 20-period average
    closes = [candle["close"] for candle in ohlcv[-20:]]
    avg = sum(closes) / len(closes)
    current = closes[-1]

    if current > avg * 1.02:
        return {"action": "BUY", "ticker": ticker, "confidence": 0.7, "reason": f"현재가 {current} > 20일 평균 {avg:.0f}의 102%"}
    elif current < avg * 0.98:
        return {"action": "SELL", "ticker": ticker, "confidence": 0.6, "reason": f"현재가 {current} < 20일 평균 {avg:.0f}의 98%"}
    else:
        return {"action": "HOLD", "ticker": ticker, "confidence": 0.3, "reason": f"현재가 {current} ≈ 20일 평균 {avg:.0f}"}
