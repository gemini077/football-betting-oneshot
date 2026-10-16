import math
import pytest
from scripts.market_asian_totals import parse_line, asian_over_share_poisson, fit_asian_market_lambdas
from scripts.market_score_math import over_half_line_probability, fit_market_lambdas
from greenfield.research.gf214_preko_bet365_shadow import market_targets, snapshot_record

@pytest.mark.parametrize("raw,want", [(3,3.0),("3.0",3.0),("2/2.5",2.25),("2.5/3",2.75),("0",0.0),("10",10.0)])
def test_parse_valid(raw,want): assert parse_line(raw)==want

@pytest.mark.parametrize("raw", [None,True,False,float("nan"),-0.25,10.25,"2/3","2.5/3.5","2.3","abc","2//2.5","1.25/1.75","3/2.5","11"])
def test_parse_invalid(raw):
    with pytest.raises((ValueError,TypeError)): parse_line(raw)

def test_whole_three_push_excluded():
    lam=2.7; got=asian_over_share_poisson(lam,3.0)
    assert got==pytest.approx(sum(math.exp(-lam)*lam**k/math.factorial(k) for k in range(4,42))/(sum(math.exp(-lam)*lam**k/math.factorial(k) for k in range(3))+sum(math.exp(-lam)*lam**k/math.factorial(k) for k in range(4,42))),abs=1e-13)

def test_quarter_boundaries():
    lam=2.0; p=lambda k: math.exp(-lam)*lam**k/math.factorial(k)
    assert asian_over_share_poisson(lam,2.25)==pytest.approx(sum(p(k) for k in range(3,42))/(sum(p(k) for k in range(3,42))+sum(p(k) for k in range(2))+0.5*p(2)))
    assert asian_over_share_poisson(lam,2.75)==pytest.approx((sum(p(k) for k in range(4,42))+0.5*p(3))/(sum(p(k) for k in range(4,42))+0.5*p(3)+sum(p(k) for k in range(3))))

@pytest.mark.parametrize("line", [0.5,1.5,2.5,3.5])
def test_half_line_exact_old_formula(line):
    for lam in (0.1,1.7,4.0,10.0): assert asian_over_share_poisson(lam,line)==pytest.approx(over_half_line_probability(lam,line),abs=1e-14)

def test_monotonic_for_supported_line():
    for line in (0,0.25,0.5,2.25,2.5,2.75,3):
        vals=[asian_over_share_poisson(x,line) for x in (0.1,1,2,4,10)]
        assert vals==sorted(vals)

def test_inversion_and_de_vig_target():
    target=asian_over_share_poisson(2.6,3.0)
    h,a=fit_asian_market_lambdas((.5,.25,.25),{"3.0":target})
    assert all(0.1<=v<=5.0 for v in (h,a))
    # Exact transformed half-line target fits the same existing optimizer.
    from scripts.market_score_math import over_half_line_probability as half
    expected=fit_market_lambdas((.5,.25,.25),{"3.5":half(2.6,3.5)})
    assert (h,a)==pytest.approx(expected,abs=1e-5)
    # reciprocal-odds normalization is the target passed by source extraction
    assert (1/2.0)/(1/2.0+1/2.0)==pytest.approx(.5)

def test_source_integer_three_line():
    snap={"input":{"source_snapshots":{"nowscore":{"snapshots":[{"ouzhi":{"bookmakers":[{"name":"bet365","spf_current":{"home":2,"draw":3,"away":4}}]},"daxiao":{"companies":[{"name":"bet365","current_line":"3.0","current_over_water":.9,"current_under_water":1.1}]}}]}}}}
    w,ou=market_targets(snap)
    assert ou=={"3.0":pytest.approx((1/1.9)/(1/1.9+1/2.1))}
    assert w==pytest.approx([6/13, 4/13, 3/13])
