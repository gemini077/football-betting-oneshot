import argparse
import gzip
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

GF214_DEFAULT = 'greenfield/results/gf214_2026_10_16_preko_bet365_shadow.json.gz'
GF215_DEFAULT = 'greenfield/results/gf215_2026_10_16_blend_50_50_preko.json.gz'
METHODS = ('champion', 'bet365', 'blend_50_50')
SCOPE = 'regulation_90m_plus_stoppage'
FROZEN_GF214_SHA256 = 'b289f555a1485f7bd63a8a24fba9e70df4445cbaf47cb30a160a4868044e2484'
FROZEN_GF215_SHA256 = 'b789f295fdcb60477760d027342236224c1d4930426719fdf127fb6b7a3334e5'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def instant(value):
    if not isinstance(value, str) or not value:
        raise ValueError('invalid timestamp')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('timestamp lacks timezone')
    return dt.timestamp()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_gzip(path):
    raw = Path(path).read_bytes()
    return json.loads(gzip.decompress(raw).decode('utf-8')), raw


def pmf_map(rows):
    values = {}
    for row in rows:
        score = row.get('score')
        if score is None and type(row.get('home_goals')) is int and type(row.get('away_goals')) is int:
            score = f"{row['home_goals']}-{row['away_goals']}"
        p = row.get('probability')
        if (not isinstance(score, str) or not isinstance(p, (int, float)) or isinstance(p, bool)
                or not math.isfinite(p) or p < 0 or score in values):
            raise ValueError('invalid pmf cell')
        values[score] = float(p)
    if len(values) != 169:
        raise ValueError('pmf must contain 169 cells')
    return values


def champion_pmf(record):
    dist = record.get('exact_score_distribution')
    if not isinstance(dist, dict) or dist.get('status') != 'FORMAL_EXACT_DISTRIBUTION_FROZEN':
        raise ValueError('Champion distribution not frozen')
    return pmf_map(dist.get('cells', []))


def trusted_bundle(gf214_path, gf215_path, records_dir):
    a, raw_a = read_gzip(gf214_path)
    b, raw_b = read_gzip(gf215_path)
    if b.get('source_gf214_compressed_sha256') != digest(raw_a):
        raise ValueError('GF215 does not pin GF214 bytes')
    if len(a.get('records', [])) != 6 or len(b.get('matches', [])) != 6:
        raise ValueError('expected six frozen pairs')
    ar = {str(x.get('match_id')): x for x in a['records']}
    br = {str(x.get('match_id')): x for x in b['matches']}
    if len(ar) != 6 or len(br) != 6 or set(ar) != set(br):
        raise ValueError('conflicting or unpaired match IDs')
    trusted = []
    for mid in sorted(ar):
        x, y = ar[mid], br[mid]
        pid = x.get('selected_prediction_id')
        if not pid or y.get('prediction_id') != pid or str(y.get('match_id')) != mid:
            raise ValueError('prediction/match identity mismatch')
        if not y.get('source_record_sha256') or len(y['source_record_sha256']) != 64:
            raise ValueError('missing Champion source SHA')
        if (x.get('original_cutoff') != y.get('source_cutoff_at')
                or x.get('original_freeze_created_at') != y.get('freeze_created_at')
                or x.get('kickoff_timestamp') != y.get('kickoff_at')):
            raise ValueError('frozen timestamp mismatch')
        record_path = Path(records_dir) / (pid + '.json')
        if not record_path.is_file():
            raise ValueError('missing frozen prediction record: ' + pid)
        raw = record_path.read_bytes()
        r = json.loads(raw.decode('utf-8'))
        if (r.get('prediction_id') != pid or str(r.get('match_id')) != mid
                or digest(raw) != y.get('source_record_sha256')):
            raise ValueError('frozen record identity/SHA mismatch')
        if (r.get('source_cutoff_at') != y.get('source_cutoff_at')
                or r.get('freeze_created_at') != y.get('freeze_created_at')
                or instant(r.get('kickoff_at')) != instant(y.get('kickoff_at'))):
            raise ValueError('frozen record timestamps mismatch')
        cp = champion_pmf(r)
        bp = pmf_map(x['market']['pmf_169'])
        blend = pmf_map(y['blend_pmf_169'])
        if any(abs(sum(p.values()) - 1) > 1e-8 for p in (cp, bp, blend)):
            raise ValueError('pmf normalization mismatch')
        rank = lambda pmf: sorted(pmf, key=lambda s: (-pmf[s], *map(int, s.split('-'))))
        champion_rank, market_rank, blend_rank = rank(cp), rank(bp), rank(blend)
        if (x.get('original_model', {}).get('top1') != y.get('champion_top1')
                or champion_rank[:3] != x.get('original_model', {}).get('top3')
                or champion_rank[:5] != x.get('original_model', {}).get('top5')
                or market_rank[:5] != x.get('market', {}).get('top5')
                or blend_rank[:5] != y.get('blend_top5')
                or champion_rank[0] != y.get('champion_top1')
                or market_rank[0] != y.get('market_top1')
                or blend_rank[0] != y.get('blend_top1')):
            raise ValueError('frozen probability invariant mismatch')
        trusted.append({'prediction_id': pid, 'match_id': mid, 'match_key': r.get('match_key'),
                        'kickoff_at': r['kickoff_at'], 'identity': r.get('match_identity') or {},
                        'pmfs': {'champion': cp, 'bet365': bp, 'blend_50_50': blend}})
    return trusted, digest(raw_a), digest(raw_b)


def resolve_result(item, result_dir):
    path = Path(result_dir) / (str(item['match_key']) + '.json')
    if not path.is_file():
        return {'state': 'PENDING', 'reason': 'NO_VERIFIED_RESULT'}
    try:
        r = read_json(path)
    except Exception:
        return {'state': 'EXCLUDED', 'reason': 'INVALID_RESULT_JSON'}

    def excluded(reason):
        return {'state': 'EXCLUDED', 'reason': reason}

    if r.get('match_key') != item['match_key']:
        return excluded('MISMATCHED_MATCH_KEY')
    ident = item['identity']
    if r.get('home') != ident.get('home') or r.get('away') != ident.get('away'):
        return excluded('TEAM_MISMATCH')
    try:
        if instant(r.get('kickoff_local')) != instant(item['kickoff_at']):
            return excluded('KICKOFF_MISMATCH')
        elapsed = instant(r.get('verified_at')) - instant(item['kickoff_at'])
        if elapsed <= 0:
            return excluded('VERIFIED_BEFORE_KICKOFF')
        if elapsed < 90 * 60:
            return excluded('VERIFIED_BEFORE_90M')
    except Exception:
        return excluded('INVALID_RESULT_TIMESTAMP')
    if r.get('scope') != SCOPE:
        return excluded('WRONG_SCOPE')
    score = r.get('result_90m')
    if not isinstance(score, str) or re.fullmatch(r'\d{1,2}-\d{1,2}', score) is None:
        return excluded('INVALID_SCORE_FORMAT')
    home, away = (int(v) for v in score.split('-'))
    if not (0 <= home <= 12 and 0 <= away <= 12):
        return excluded('OUT_OF_SUPPORT')
    if (type(r.get('home_score')) is int and r['home_score'] != home) or (type(r.get('away_score')) is int and r['away_score'] != away):
        return excluded('SCORE_COMPONENT_MISMATCH')
    if not r.get('source') or not r.get('verification_quality'):
        return excluded('MISSING_VERIFICATION_PROVENANCE')
    key = f'{home}-{away}'
    metrics = {}
    for method, pmf in item['pmfs'].items():
        ranking = sorted(pmf, key=lambda s: (-pmf[s], *map(int, s.split('-'))))
        p = pmf[key]
        metrics[method] = {'top1': int(key in ranking[:1]), 'top3': int(key in ranking[:3]),
                           'top5': int(key in ranking[:5]), 'nll': -math.log(p) if p > 0 else None,
                           'nll_exclusion_reason': 'ZERO_PROBABILITY' if p == 0 else None}
    return {'state': 'SETTLED', 'score': key, 'metrics': metrics}


def evaluate(repo_root, gf214_path, gf215_path, records_dir, result_dir=None):
    repo = Path(repo_root)
    results_path = Path(result_dir or repo / 'data/postmatch_automation/results')
    items, h214, h215 = trusted_bundle(gf214_path, gf215_path, records_dir)
    matches = []
    for item in items:
        result = resolve_result(item, results_path)
        row = {k: item[k] for k in ('prediction_id', 'match_id', 'match_key')}
        row.update(result)
        matches.append(row)
    settled = [x for x in matches if x['state'] == 'SETTLED']
    paired_nll = [x for x in settled if all(x['metrics'][m]['nll'] is not None for m in METHODS)]
    summary = {'settled': len(settled), 'pending': sum(x['state'] == 'PENDING' for x in matches),
               'excluded': sum(x['state'] == 'EXCLUDED' for x in matches), 'methods': {}}
    for method in METHODS:
        vals = [x['metrics'][method] for x in settled]
        nlls = [x['metrics'][method]['nll'] for x in paired_nll]
        summary['methods'][method] = {
            'top1': sum(v['top1'] for v in vals) / len(vals) if vals else None,
            'top3': sum(v['top3'] for v in vals) / len(vals) if vals else None,
            'top5': sum(v['top5'] for v in vals) / len(vals) if vals else None,
            'mean_nll': sum(nlls) / len(nlls) if nlls else None, 'nll_matches': len(nlls),
            'nll_excluded_zero_probability': len(settled) - len(paired_nll)}
    return {'schema': 'gf216.strict_paired_score_eval.v1',
            'provenance': {'gf214_raw_sha256': h214, 'gf215_raw_sha256': h215},
            'summary': summary, 'matches': matches}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo-root', required=True)
    parser.add_argument('--gf214')
    parser.add_argument('--gf215')
    parser.add_argument('--records-dir')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    repo = Path(args.repo_root)
    gf214 = Path(args.gf214 or repo / GF214_DEFAULT)
    gf215 = Path(args.gf215 or repo / GF215_DEFAULT)
    if digest(gf214.read_bytes()) != FROZEN_GF214_SHA256 or digest(gf215.read_bytes()) != FROZEN_GF215_SHA256:
        raise ValueError('source archives changed from sealed pre-kickoff bytes')
    result = evaluate(repo, gf214, gf215, args.records_dir or repo / 'data/model_governance/predictions')
    Path(args.output).write_text(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
