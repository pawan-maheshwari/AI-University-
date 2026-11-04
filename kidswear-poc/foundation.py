"""
Foundation-model adapter (Chronos-2 / Chronos-Bolt / TimesFM) with zero-shot fallbacks.

In production, set CHRONOS_MODEL_PATH (a local folder or a Hugging Face id such as
"amazon/chronos-bolt-small") and install `chronos-forecasting` + `torch`. The adapter then
produces P10/P50/P90 forecasts from each series' history. TimesFM can be wired the same way
through `timesfm_forecast`.

When the weights cannot be loaded (no network, no GPU, package missing) the pipeline does not
stop: it records why and uses two transparent zero-shot models instead:
  * seasonal_trend  - same week last year x recent year-on-year trend (established styles)
  * analog          - k most similar established styles by attributes (new styles, cold start)
"""
import os
import numpy as np
import pandas as pd


class FoundationModelUnavailable(Exception):
    pass


def load_chronos(model_id=None):
    model_id = model_id or os.environ.get("CHRONOS_MODEL_PATH", "amazon/chronos-bolt-small")
    try:
        import torch  # noqa: F401
        from chronos import BaseChronosPipeline
        return BaseChronosPipeline.from_pretrained(model_id, device_map="cpu")
    except Exception as e:  # missing package, weights or network
        raise FoundationModelUnavailable(f"{e.__class__.__name__}: {str(e)[:160]}")


def chronos_forecast(pipe, histories, horizon, quantiles=(0.1, 0.5, 0.9)):
    """histories: list of 1-D arrays. Returns array [series, horizon, len(quantiles)]."""
    import torch
    q, _ = pipe.predict_quantiles(context=[torch.tensor(np.asarray(h, dtype=np.float32)) for h in histories],
                                  prediction_length=horizon, quantile_levels=list(quantiles))
    return q.numpy()


def load_timesfm(model_id=None):
    try:
        import timesfm  # noqa: F401
    except Exception as e:
        raise FoundationModelUnavailable(f"{e.__class__.__name__}: {str(e)[:160]}")
    raise FoundationModelUnavailable("TimesFM adapter not configured in this environment")


def seasonal_trend(panel, rows, lead=8):
    """panel: demand_est indexed by (style_id, store_id, week_index). rows: frame with style_id, store_id, week_index.
    Forecast = same week last year x (recent 4 weeks / same 4 weeks last year), using data at least `lead` weeks old."""
    get = lambda s, st, w: panel.get((s, st, w), np.nan)
    out = []
    for s, st, w in rows[["style_id", "store_id", "week_index"]].itertuples(index=False):
        ly = get(s, st, w - 52)
        rec = np.nanmean([get(s, st, w - k) for k in range(lead, lead + 4)])
        rec_ly = np.nanmean([get(s, st, w - 52 - k) for k in range(lead, lead + 4)])
        trend = np.clip(rec / rec_ly, 0.4, 2.5) if np.isfinite(rec) and np.isfinite(rec_ly) and rec_ly > 0 else 1.0
        out.append(ly * trend if np.isfinite(ly) else np.nan)
    return np.array(out, dtype=float)


def analog(panel, styles, rows, k=5, lead=8):
    """Cold start: average same-store, same-week-last-year demand of the k most similar established styles,
    adjusted by the category's year-on-year trend. Similarity: category (required), fit, fabric, price."""
    est = styles[styles.launch_wi == 1]
    cat_trend = {}
    out = []
    for s, st, w in rows[["style_id", "store_id", "week_index"]].itertuples(index=False):
        me = styles.loc[s]
        cand = est[est.category == me.category]
        score = (cand.fit == me.fit) * 1.0 + (cand.fabric == me.fabric) * 0.5 - np.abs(np.log(cand.full_price / me.full_price))
        nb = score.sort_values(ascending=False).index[:k]
        vals = [panel.get((a, st, w - 52), np.nan) for a in nb]
        key = (me.category, w)
        if key not in cat_trend:
            now = [panel.get((a, x, w - lead), np.nan) for a in nb for x in [st]]
            then = [panel.get((a, x, w - lead - 52), np.nan) for a in nb for x in [st]]
            cat_trend[key] = np.clip(np.nanmean(now) / np.nanmean(then), 0.4, 2.5) if np.nanmean(then) > 0 else 1.0
        out.append(np.nanmean(vals) * cat_trend[key] if np.isfinite(np.nanmean(vals)) else np.nan)
    return np.array(out, dtype=float)


def nnls_weights(X, y):
    """Non-negative stacking weights (sum not forced to 1, so the blend can also correct bias)."""
    from scipy.optimize import nnls
    w, _ = nnls(np.asarray(X, float), np.asarray(y, float))
    return w
