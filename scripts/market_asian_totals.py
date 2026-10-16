"""Pure research-only settlement-aware Asian total-goals conversion."""
import math
import re

from scripts.market_score_math import _poisson_pmf, fit_market_lambdas, over_half_line_probability


def parse_line(line):
    if isinstance(line, bool) or line is None:
        raise ValueError("invalid_asian_line")
    if isinstance(line, str):
        text = line.strip()
        if "/" in text:
            parts = text.split("/")
            if len(parts) != 2 or any(not re.fullmatch(r"\d+(?:\.\d+)?", x.strip()) for x in parts):
                raise ValueError("invalid_asian_line")
            a, b = map(float, (x.strip() for x in parts))
            if (abs(b-a-0.5)>1e-9 or abs(a*2-round(a*2))>1e-9
                    or abs(b*2-round(b*2))>1e-9):
                raise ValueError("invalid_asian_line")
            value=(a+b)/2
        else:
            if not re.fullmatch(r"\d+(?:\.\d+)?", text):
                raise ValueError("invalid_asian_line")
            value=float(text)
    elif isinstance(line, (int, float)):
        value=float(line)
    else:
        raise ValueError("invalid_asian_line")
    if not math.isfinite(value) or value < 0 or value > 10 or abs(value*4-round(value*4))>1e-9:
        raise ValueError("unsupported_asian_line")
    return round(value*4)/4


def asian_over_share_poisson(lambda_total, line):
    if isinstance(lambda_total, bool) or not isinstance(lambda_total,(int,float)) or not math.isfinite(lambda_total) or lambda_total<0:
        raise ValueError("invalid_total_lambda")
    x=parse_line(line); lam=float(lambda_total)
    whole=math.floor(x); frac=round(x-whole,2)
    probs=[_poisson_pmf(lam,k) for k in range(42)]
    if frac==0:
        wins=sum(probs[whole+1:]); losses=sum(probs[:whole])
    elif frac==0.5:
        wins=sum(probs[whole+1:]); losses=sum(probs[:whole+1])
    elif frac==0.25:
        wins=sum(probs[whole+1:]); losses=sum(probs[:whole])+0.5*probs[whole]
    else: # x.75: N=k+1 is half win for over
        wins=sum(probs[whole+2:])+0.5*probs[whole+1]; losses=sum(probs[:whole+1])
    denom=wins+losses
    if not math.isfinite(denom) or denom<=0: raise ValueError("zero_settlement_mass")
    return wins/denom


def fit_asian_market_lambdas(wdl_target, asian_targets):
    if not isinstance(asian_targets,dict) or len(asian_targets)!=1:
        raise ValueError("one_asian_target_required")
    line_text,target=next(iter(asian_targets.items())); line=parse_line(line_text)
    if isinstance(target,bool) or not isinstance(target,(int,float)) or not math.isfinite(target) or not 0<target<1:
        raise ValueError("asian_target_must_be_between_zero_and_one")
    lo,hi=0.1,10.0; plo=asian_over_share_poisson(lo,line); phi=asian_over_share_poisson(hi,line)
    if not (plo<=target<=phi): raise ValueError("asian_target_out_of_lambda_bracket")
    for _ in range(80):
        mid=(lo+hi)/2
        if asian_over_share_poisson(mid,line)<target: lo=mid
        else: hi=mid
    total=(lo+hi)/2; equivalent=math.floor(line)+0.5
    inferred=over_half_line_probability(total,equivalent)
    return fit_market_lambdas(wdl_target,{str(equivalent):inferred})
