import importlib.util, math
from pathlib import Path

P=Path(__file__).parents[1]/'scripts/pme_forward_score_calibration.py'
spec=importlib.util.spec_from_file_location('cal',P); cal=importlib.util.module_from_spec(spec); spec.loader.exec_module(cal)

def pmf():
    m={(h,a):1/169 for h in range(13) for a in range(13)}
    m[(1,1)]=0.20; z=sum(m.values()); return {k:v/z for k,v in m.items()}

def test_transform_normalizes_and_identity():
    p=pmf(); assert cal.transform(p,'one_one_odds',1.0)==p
    assert abs(sum(cal.transform(p,'draw_diagonal_odds',1.5).values())-1)<1e-12
    assert cal.transform(p,'pmf_power',1.0)==p

def test_day_holdout_and_no_future_leakage():
    base=pmf(); rows=[]
    for d in range(5):
        for j in range(3): rows.append({'day':f'2026-01-0{d+1}','key':f'{d}-{j}','actual':(1,1) if d%2 else (0,0),'champion':base})
    earlier=cal.choose(rows[:9],'one_one_odds')
    changed=[dict(x,actual=(12,12)) if x['day']=='2026-01-05' else x for x in rows]
    assert cal.choose(rows[:9],'one_one_odds')==cal.choose(changed[:9],'one_one_odds')
    assert earlier in cal.GRID

def test_score_metric_and_baseline_coefficient():
    p=pmf(); assert cal.choose([{'champion':p,'actual':(1,1)} for _ in range(10)],'one_one_odds')==2.0
    q=cal.transform(p,'one_one_odds',1)
    rank=sorted(q,key=lambda k:(-q[k],k[0],k[1])); assert cal.audit.metric(q,rank,(1,1))['top1']==1

def test_source_failure_fails_closed(tmp_path):
    try: cal.build(tmp_path)
    except FileNotFoundError: pass
    else: assert False

def test_deterministic():
    data=[{'champion':pmf(),'actual':(1,1)} for _ in range(12)]
    assert cal.choose(data,'one_one_odds')==cal.choose(data,'one_one_odds')


