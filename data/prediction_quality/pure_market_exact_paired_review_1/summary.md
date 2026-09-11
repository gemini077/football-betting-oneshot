# Pure Market Exact vs Champion paired prospective review

- Verdict: `INSUFFICIENT_SAMPLE_CONTINUE_ACCUMULATING`; paired unique matches: `22`.
- Counts: raw Market settlements `94`, unique Market matches `22`, exact Champion pairs resolved `22`, rejected `0`.
- Reject counts: `{}`.
- Selection exclusions: `{}`.
- No winner or promotion conclusion is emitted; Champion and all serving/model authority remain unchanged.

## Paired metrics

| Metric | Market | Champion | Market-Champion delta | 95% CI for delta | W/T/L |
|---|---:|---:|---:|---:|---:|
| `exact_nll` | 2.782163 (n=22) | 3.021906 (n=22) | -0.239743 | [-0.428001, -0.051486] | 16/0/6 |
| `exact_top1` | 0.272727 (n=22) | 0.181818 (n=22) | 0.090909 | [-0.032048, 0.213866] | 2/20/0 |
| `exact_top3` | 0.409091 (n=22) | 0.363636 (n=22) | 0.045455 | [-0.111286, 0.202195] | 2/19/1 |
| `exact_top5` | 0.681818 (n=22) | 0.590909 (n=22) | 0.090909 | [-0.032048, 0.213866] | 2/20/0 |
| `actual_score_rank` | 6.363636 (n=22) | 8.272727 (n=22) | -1.909091 | [-3.898186, 0.080004] | 11/8/3 |
| `ft_1x2_log_loss` | 0.630661 (n=22) | 0.792638 (n=22) | -0.161977 | [-0.242773, -0.081181] | 16/0/6 |
| `ft_1x2_brier` | 0.336246 (n=22) | 0.445993 (n=22) | -0.109747 | [-0.163903, -0.055590] | 16/0/6 |
| `ft_1x2_rps` | 0.114220 (n=22) | 0.162997 (n=22) | -0.048778 | [-0.073667, -0.023889] | 16/0/6 |
| `ou_2_5_brier` | 0.191371 (n=22) | 0.193626 (n=22) | -0.002255 | [-0.020307, 0.015797] | 13/0/9 |
| `btts_brier` | 0.209561 (n=22) | 0.207550 (n=22) | 0.002011 | [-0.030499, 0.034521] | 11/0/11 |
| `lambda_home_residual` | 0.301703 (n=22) | 0.527630 (n=22) | -0.225926 | [-0.441622, -0.010230] | - |
| `lambda_away_residual` | 0.053499 (n=22) | -0.041720 (n=22) | 0.095220 | [-0.045522, 0.235962] | - |
| `lambda_total_residual` | 0.355203 (n=22) | 0.485909 (n=22) | -0.130706 | [-0.242818, -0.018594] | - |
| `lambda_home_absolute_error` | 0.954084 (n=22) | 1.118849 (n=22) | -0.164765 | [-0.389691, 0.060161] | 14/0/8 |
| `lambda_away_absolute_error` | 0.614290 (n=22) | 0.729361 (n=22) | -0.115071 | [-0.202971, -0.027170] | 15/0/7 |
| `lambda_total_absolute_error` | 1.385623 (n=22) | 1.437727 (n=22) | -0.052104 | [-0.175383, 0.071175] | 14/0/8 |
| `score_1_1_top1` | 0.363636 (n=22) | 0.545455 (n=22) | -0.181818 | [-0.346782, -0.016854] | - |

## Exact paired IDs

| match_key | Market prediction | Champion prediction | result |
|---|---|---|---|
| `FBOS-202609090200-5dbc7ae41e` | `PME-f9b1adf0b522d119a94c9d94` | `FBOS-PRED-b88d4b76d7dbce708aff6fe6` | `3-2` |
| `FBOS-202609090245-6a774af33b` | `PME-ddc05cc137f41f1a941096df` | `FBOS-PRED-f53ae5290980206bc7b89536` | `1-0` |
| `FBOS-202609090245-ed796926bf` | `PME-caf617dac03b8ae060e0b443` | `FBOS-PRED-2401a87826156cf40a9e54ca` | `3-1` |
| `FBOS-202609090300-0b8c814860` | `PME-882341c052754e1e9860ae57` | `FBOS-PRED-f346c65e734e35a6a38c1fab` | `3-2` |
| `FBOS-202609090300-29dbd22105` | `PME-8b7aa9aed0eb79ce86156f13` | `FBOS-PRED-49ae55986576209cdf44d56d` | `2-1` |
| `FBOS-202609090300-688d6ee1d6` | `PME-8eec5a054b4d9c76cb8dd8e3` | `FBOS-PRED-c0224f32b7a412046833bbba` | `2-3` |
| `FBOS-202609090300-cd8fbf4839` | `PME-74884be476e70528848133d5` | `FBOS-PRED-4a8326b4895698308a76a4bd` | `0-2` |
| `FBOS-202609090600-f31c604b59` | `PME-1456b7bebc9a7af82b696e49` | `FBOS-PRED-15911cb0d46c4a9ab526b2f3` | `2-0` |
| `FBOS-202609091830-7d61d7a0da` | `PME-8083dd289d4e6b83c444b447` | `FBOS-PRED-afd2867bc620ab0922795011` | `1-1` |
| `FBOS-202609092355-d411c3c28c` | `PME-1173957b9108b51c89a41e0f` | `FBOS-PRED-6f94cec1a824d14f6c24cd67` | `2-1` |
| `FBOS-202609100045-2c0516a4d6` | `PME-bad9cf4c871762ed6f55cd33` | `FBOS-PRED-a2f1cc3750bc26d4e86c580d` | `5-1` |
| `FBOS-202609100045-5a43b83eda` | `PME-69b5f6dfbde7acf37b7a629d` | `FBOS-PRED-8eddc814712b34c68fb87509` | `3-1` |
| `FBOS-202609100045-ddfb069568` | `PME-f1f0943a9ceb63af65eb6b85` | `FBOS-PRED-a20c86ceb648bf5690570c76` | `1-0` |
| `FBOS-202609100300-3e26d83fee` | `PME-75a4c84a2160f6ffdb832dd1` | `FBOS-PRED-4823475390f4cb8a19e2de4d` | `0-1` |
| `FBOS-202609100300-5ea6528f3d` | `PME-2179960bfa468995901999a1` | `FBOS-PRED-11e6375dab1bcecd42b0c365` | `6-1` |
| `FBOS-202609100300-716826571b` | `PME-0881ffc8688027670b771cad` | `FBOS-PRED-5bfda22cdc58e4f9644be6ad` | `2-1` |
| `FBOS-202609100300-7d99f57de6` | `PME-007f93645416e82f0ab7f8a1` | `FBOS-PRED-199c3a8c713c79b3cf813190` | `3-1` |
| `FBOS-202609100300-ea4affffaf` | `PME-f111ed7de6c66665f8e262b3` | `FBOS-PRED-cec0ff4da307d4f81e3661cf` | `6-3` |
| `FBOS-202609100345-813b3011ef` | `PME-e96d68b266b0880d459d6943` | `FBOS-PRED-62391ba6b767efe5364d8fc6` | `0-4` |
| `FBOS-202609100600-d3feec8956` | `PME-74d9167095648ffd8d895472` | `FBOS-PRED-a51c572c99b2ad3ce9cef569` | `1-0` |
| `FBOS-202609100830-06eba581f7` | `PME-225255df758c227c38d012b9` | `FBOS-PRED-5ac4e9b0a5f2b34325ad6e24` | `1-1` |
| `FBOS-202609100830-ff78f84126` | `PME-6e31fac7239cbaaaeee13eda` | `FBOS-PRED-da2a2e2e2e6f5269fa02aca0` | `1-1` |
