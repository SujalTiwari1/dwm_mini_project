"""Baseline forecasters (strictly causal, vectorised). Each returns the forecast of units over origin+1 .. origin+h for every origin day and pair.

  naive                  repeat the most recent h days (the last observed period of the same length)
  moving_average_7 / 28  recent daily mean over the last 7 / 28 days, times h
  seasonal_naive_weekly  each future day takes the units of the same weekday in the latest observed week (for h = 7 this equals naive)
  seasonal_naive_yearly  the same calendar span 364 days (52 weeks) earlier; only 24 months exist, so it is available for the validation
                         and test origins from 2025-12-31 onward and rests on a single earlier year (not many independent yearly observations)
"""
import numpy as np


def baseline_forecasts(units, h):
    """Return {name: [T, N] forecast of the units over origin+1..origin+h} (NaN where not computable)."""
    T, N = units.shape
    c0 = np.vstack([np.zeros((1, N)), np.cumsum(units, axis=0).astype(np.float64)])      # c0[t+1] = units through day t
    out = {}

    def window_sum(t_end_offset, length):
        """sum of days (t - length + 1 + offset .. t + offset) for every t, NaN if out of range."""
        res = np.full((T, N), np.nan)
        for t in range(T):
            hi, lo = t + 1 + t_end_offset, t + 1 + t_end_offset - length
            if lo >= 0 and hi <= T:
                res[t] = c0[hi] - c0[lo]
        return res

    out["naive"] = window_sum(0, h)                                    # repeat the most recent h days
    out["moving_average_7"] = h * window_sum(0, 7) / 7                 # recent daily mean x h
    out["moving_average_28"] = h * window_sum(0, 28) / 28
    seasonal = np.zeros((T, N))                                        # same weekday of the latest observed week for each future day
    valid = np.zeros(T, dtype=bool)
    valid[6:] = True
    for j in range(1, h + 1):
        src = np.arange(T) + j - 7 * int(np.ceil(j / 7))
        ok = src >= 0
        seasonal[ok] += units[src[ok]]
    seasonal[~valid] = np.nan
    out["seasonal_naive_weekly"] = seasonal
    out["seasonal_naive_yearly"] = window_sum(h - 364, h)              # the same calendar span 364 days (52 weeks) earlier
    return out
