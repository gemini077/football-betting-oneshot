import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts import prediction_dashboard as d

def fixture(mid='m1', **kw):
 f={'match_id':mid,'business_date':'2026-10-15','status':'FROZEN','formal_prospective':True,'pilot_excluded':False,'kickoff_timestamp':'2026-10-15T20:00:00Z','selected_freeze_created_at':'2026-10-15T18:00:00Z','selected_source_cutoff_at':'2026-10-15T19:00:00Z','result':{'score_90m':'1-1'},'evaluation':{'kind':'formal','metrics':{'exact_score_authority_status':'FROZEN_PREDICTION_TIME','exact_score_top1':True,'exact_score_top3':True,'exact_score_top5':False}},'prediction':{'primary_score':'1-1'}}
 f.update(kw); return f

def test_legitimate_two():
 p={'fixtures':[fixture(),fixture('m2', result={'score_90m':'2-0'}, prediction={'primary_score':'2-0'})]}
 assert d.summarize_frozen_exact_score_review(p)=={'count':2,'top1':2,'top3':2,'top5':0,'predicted_11':1,'actual_11':1,'c_count':0,'business_days':1}
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
    assert '小样本' in d.render_frozen_exact_score_review({'fixtures':[x,y]})
