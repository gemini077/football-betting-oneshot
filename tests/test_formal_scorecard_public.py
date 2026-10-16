import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts import prediction_dashboard as d

def fixture(mid='m1', **kw):
 f={'match_id':mid,'business_date':'2026-10-15','status':'FROZEN','formal_prospective':True,'pilot_excluded':False,'kickoff_timestamp':'2026-10-15T20:00:00Z','selected_freeze_created_at':'2026-10-15T18:00:00Z','selected_source_cutoff_at':'2026-10-15T19:00:00Z','result':{'score_90m':'1-1'},'evaluation':{'kind':'formal','metrics':{'exact_score_authority_status':'FROZEN_PREDICTION_TIME','exact_score_top1':True,'exact_score_top3':True,'exact_score_top5':False}},'prediction':{'primary_score':'1-1'}}
 f.update(kw); return f

def test_legitimate_two():
 p={'fixtures':[fixture(),fixture('m2', result={'score_90m':'2-0'}, prediction={'primary_score':'2-0'})]}
 score=d.summarize_frozen_exact_score_review(p)
 assert {k:score[k] for k in ('count','top1','top3','top5','predicted_11','actual_11','c_count','business_days')}=={'count':2,'top1':2,'top3':2,'top5':0,'predicted_11':1,'actual_11':1,'c_count':0,'business_days':1}
 assert score['expected_11'] is None
def test_duplicate_fails_closed():
 f=fixture(); assert d.summarize_frozen_exact_score_review({'fixtures':[f,dict(f)]}) is None
def test_kickoff_and_stale_cutoff_excluded():
 assert d.summarize_frozen_exact_score_review({'fixtures':[fixture('a',selected_freeze_created_at='2026-10-15T20:00:00Z'),fixture('b',selected_source_cutoff_at='2026-10-15T20:00:00Z')]}) is None
def test_missing_result_and_exclusion():
 assert d.summarize_frozen_exact_score_review({'fixtures':[fixture('a',result={}),fixture('b',pilot_excluded=True)]}) is None
def test_malformed_non_boolean_metric():
 f=fixture(); f['evaluation']['metrics']['exact_score_top1']=1
 assert d.summarize_frozen_exact_score_review({'fixtures':[f]}) is None


def test_grade_and_multi_day_are_not_fabricated():
    x=fixture('a')
    y=fixture('b',business_date='2026-10-16',prediction={'primary_score':'2-0','data_grade':'C'})
    score=d.summarize_frozen_exact_score_review({'fixtures':[x,y]})
    assert score['count']==2
    assert score['c_count']==1
    assert score['business_days']==2
    assert 'Top1 / Top3 / Top5' in d.render_frozen_exact_score_review({'fixtures':[x,y]})


def test_expected_probability_full_coverage():
    rows=[]
    for i in range(12):
        probability=0.1044
        rows.append(fixture(str(i), result={'score_90m':'1-1' if i < 2 else '0-0'}, prediction={'primary_score':'1-1' if i < 8 else '0-0','score_distribution':[{'score':'1-1','probability':probability}]}))
    score=d.summarize_frozen_exact_score_review({'fixtures':rows})
    assert score['count']==12 and score['predicted_11']==8 and score['actual_11']==2
    assert score['expected_11']==pytest.approx(1.2528)
    rendered=d.render_frozen_exact_score_review({'fixtures':rows})
    assert '\u9996\u90091-1 8\u573a \u00b7 \u6309\u6982\u7387\u9884\u671f1.25\u573a \u00b7 \u5b9e\u96452\u573a' in rendered
    assert '\u6309\u6982\u7387\u9884\u671f0.15\u573a' in d.render_frozen_exact_score_review({'fixtures':[fixture('valid', prediction={'primary_score':'1-1','score_distribution':[{'score':'1-1','probability':0.15}]})]})

@pytest.mark.parametrize('distribution', [
    [],
    [{'score':'1-1','probability':0.2},{'score':'1-1','probability':0.3}],
    [{'score':'1-1','probability':float('nan')}],
    [{'score':'1-1','probability':True}],
])
def test_invalid_expected_probability_fails_closed_only(distribution):
    rows=[fixture('a',prediction={'primary_score':'1-1','score_distribution':distribution}),
          fixture('b',prediction={'primary_score':'2-0','score_distribution':[{'score':'1-1','probability':0.2}]})]
    score=d.summarize_frozen_exact_score_review({'fixtures':rows})
    assert score['expected_11'] is None
    assert (score['count'],score['top1'],score['top3'],score['top5'],score['predicted_11'],score['actual_11'])==(2,2,2,0,1,2)
    rendered = d.render_frozen_exact_score_review({'fixtures':rows})
    assert '\u6982\u7387\u9884\u671f\u6682\u4e0d\u53ef\u5f97' in rendered
    assert '\u9884\u671f\u6982\u7387\u9884\u671f' not in rendered
    assert '\u6682\u4e0d\u53ef\u5f97\u573a' not in rendered
    assert '\u9884\u671f\u6982\u7387\u9884\u671f' not in rendered
    assert '\u6682\u4e0d\u53ef\u5f97\u573a' not in rendered

