"""GF233: preserve paired research audit and measure repository churn."""
import re
import subprocess
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/deploy-pages.yml"
PAIR = "data/prediction_quality/pure_market_exact_prospective_1"


def _save_step():
    s = WF.read_text(encoding="utf-8")
    return s[s.index("      - name: Save generated public data"):s.index("      - name: Verify formal settled scorecard")]


def test_paired_report_in_daily_save_allowlist():
    step = _save_step()
    m = re.search(r"paths=\(([^)\n]+)\)", step)
    assert m, "save step must stage explicit paths"
    assert PAIR in m.group(1).split(), "historical paired output was silently lost"
    assert 'git add -A -- "${existing[@]}"'.replace('$','$') in step


def test_paired_audit_before_save_and_rebuild():
    s = WF.read_text(encoding="utf-8")
    assert s.index("      - name: Evaluate independent historical paired research") < s.index(
        "      - name: Save generated public data"
    ) < s.index("      - name: Rebuild Pages artifact after data save")
    assert "python -m scripts.pme_champion_paired_audit --repo-root ." in s


def test_commit_churn_is_visible_and_nondestructive():
    s = _save_step()
    assert "git diff --cached --name-only -z" in s
    assert "FBOS staged data files:" in s
    assert "changed_files > 200" in s
    assert "git clean" not in s and "git reset --hard" not in s


def test_git_add_scoped_paired_artifact(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = shutil.which("git") or r"D:\Software\Git\cmd\git.exe"
    subprocess.run([git,"init","-q"],cwd=repo,check=True,capture_output=True)
    target=repo/PAIR/"champion_market_paired_review.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"n":90,"robustness":{"cluster_days":8}}',encoding="utf-8")
    other=repo/"unrelated.txt"
    other.write_text("do not stage",encoding="utf-8")
    subprocess.run([git,"add","-A","--",PAIR],cwd=repo,check=True,capture_output=True)
    files=subprocess.run([git,"diff","--cached","--name-only"],cwd=repo,check=True,
                         capture_output=True,text=True).stdout.splitlines()
    assert files == [PAIR+"/champion_market_paired_review.json"]
    assert other.exists()


def test_generator_has_non_iid_robustness_outputs():
    code=(ROOT/"scripts/pme_champion_paired_audit.py").read_text(encoding="utf-8")
    assert "matchday_cluster_bootstrap_95_ci" in code
    assert "chronological_thirds" in code
    assert "'robustness':" in code
