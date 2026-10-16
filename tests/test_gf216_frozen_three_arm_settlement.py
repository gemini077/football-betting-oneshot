import gzip
import hashlib
import json
import shutil
import os
from pathlib import Path

import pytest

from greenfield.research import gf216_frozen_three_arm_settlement as ev

GF214 = Path(__file__).resolve().parents[1] / 'greenfield/results/gf214_2026_10_16_preko_bet365_shadow.json.gz'
GF215 = Path(__file__).resolve().parents[1] / 'greenfield/results/gf215_2026_10_16_blend_50_50_preko.json.gz'
SOURCES = Path(os.environ.get('GF216_FROZEN_SOURCE_DIR', str(Path(__file__).resolve().parents[1] / 'data/model_governance/predictions')))


@pytest.fixture
def case(tmp_path):
    recs = tmp_path / 'records'
    recs.mkdir()
    ids = [x['prediction_id'] for x in json.loads(gzip.decompress(GF215.read_bytes()))['matches']]
    assert len(ids) == len(set(ids)) == 6
    for pid in ids:
        f = SOURCES / (pid + '.json')
        assert f.is_file(), 'missing sealed original prediction: ' + pid
        shutil.copyfile(f, recs / f.name)
    results = tmp_path / 'results'
    results.mkdir()
    return {'root': tmp_path, 'records': recs, 'results': results,
            'a': tmp_path / 'a.json.gz', 'b': tmp_path / 'b.json.gz'}


def pin_inputs(case):
    shutil.copyfile(GF214, case['a'])
    shutil.copyfile(GF215, case['b'])


def bundle(case):
    pin_inputs(case)
    return ev.trusted_bundle(case['a'], case['b'], case['records'])[0]


def write_result(path, item, **overrides):
    value = {'match_key': item['match_key'], 'home': item['identity']['home'], 'away': item['identity']['away'],
             'kickoff_local': item['kickoff_at'], 'verified_at': '2026-10-17T03:00:00Z',
             'result_90m': '1-2', 'home_score': 1, 'away_score': 2, 'scope': ev.SCOPE, 'source': 'fixture',
             'verification_quality': 'verified'}
    value.update(overrides)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def test_six_frozen_sources_are_pending_without_result_leakage(case):
    result = ev.evaluate(case['root'], GF214, GF215, case['records'], case['results'])
    assert result['summary']['pending'] == 6 and result['summary']['settled'] == 0
    assert all(x['state'] == 'PENDING' for x in result['matches'])
    assert all(x['mean_nll'] is None for x in result['summary']['methods'].values())


def test_rejects_altered_frozen_record_sha(case):
    pin_inputs(case)
    file = next(case['records'].glob('*.json'))
    file.write_bytes(file.read_bytes() + b' ')
    with pytest.raises(ValueError, match='identity/SHA'):
        ev.trusted_bundle(case['a'], case['b'], case['records'])


def test_rejects_gf215_wrong_prediction_id(case):
    pin_inputs(case)
    obj = json.loads(gzip.decompress(case['b'].read_bytes()))
    obj['matches'][0]['prediction_id'] = 'WRONG'
    case['b'].write_bytes(gzip.compress(json.dumps(obj).encode()))
    with pytest.raises(ValueError, match='identity mismatch'):
        ev.trusted_bundle(case['a'], case['b'], case['records'])


@pytest.mark.parametrize(('override', 'reason'), [
    ({'verified_at': '2026-10-16T16:30:00Z'}, 'VERIFIED_BEFORE_KICKOFF'),
    ({'scope': 'extra_time_included'}, 'WRONG_SCOPE'),
    ({'match_key': 'OTHER'}, 'MISMATCHED_MATCH_KEY'),
    ({'kickoff_local': '2026-10-16T16:31:00Z'}, 'KICKOFF_MISMATCH'),
    ({'result_90m': '13-0'}, 'OUT_OF_SUPPORT'),
    ({'result_90m': {'home': 1, 'away': 2}}, 'INVALID_SCORE_FORMAT'),
    ({'home_score': 3}, 'SCORE_COMPONENT_MISMATCH'),
    ({'verified_at': '2026-10-17T00:00:00Z'}, 'VERIFIED_BEFORE_90M'),
])
def test_rejects_invalid_results(case, override, reason):
    item = bundle(case)[0]
    path = case['results'] / f"{item['match_key']}.json"
    write_result(path, item, **override)
    assert ev.resolve_result(item, case['results']) == {'state': 'EXCLUDED', 'reason': reason}


def test_accepts_manual_metrics_and_paired_nll(case):
    items = bundle(case)
    for item in items:
        write_result(case['results'] / f"{item['match_key']}.json", item)
    out = ev.evaluate(case['root'], case['a'], case['b'], case['records'], case['results'])
    first = out['matches'][0]
    for method, pmf in items[0]['pmfs'].items():
        ordered = sorted(pmf, key=lambda s: (-pmf[s], *map(int, s.split('-'))))
        expected = {'top1': int('1-2' in ordered[:1]), 'top3': int('1-2' in ordered[:3]),
                    'top5': int('1-2' in ordered[:5]), 'nll': -__import__('math').log(pmf['1-2']),
                    'nll_exclusion_reason': None}
        assert first['metrics'][method] == expected
        assert out['summary']['methods'][method]['mean_nll'] is not None


def test_output_is_deterministic_and_contains_raw_provenance(case):
    pin_inputs(case)
    one = ev.evaluate(case['root'], case['a'], case['b'], case['records'], case['results'])
    two = ev.evaluate(case['root'], case['a'], case['b'], case['records'], case['results'])
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
    assert one['provenance']['gf214_raw_sha256'] == hashlib.sha256(case['a'].read_bytes()).hexdigest()


def test_zero_probability_is_excluded_not_clipped(case):
    item = bundle(case)[0]
    for pmf in item['pmfs'].values():
        pmf['1-2'] = 0.0
    path = case['results'] / f"{item['match_key']}.json"
    write_result(path, item)
    result = ev.resolve_result(item, case['results'])
    assert all(m['nll'] is None and m['nll_exclusion_reason'] == 'ZERO_PROBABILITY'
               for m in result['metrics'].values())

def test_pinned_frozen_archive_bytes():
 assert ev.digest(GF214.read_bytes()) == ev.FROZEN_GF214_SHA256
 assert ev.digest(GF215.read_bytes()) == ev.FROZEN_GF215_SHA256
