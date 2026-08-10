# P0/P1 source decisions

## UEFA OpenFootball

Adopted as an offline historical/schema source through the existing OpenFootball adapter. The pinned repository exposes UCL/Europa/Conference Football.TXT files and CC0/public-domain terms. The captured 2025/26 files do not prove 2026/27 current-season coverage; therefore current UEFA demand remains source/current-season missing until the next season files are available.

See [openfootball/champions-league](https://github.com/openfootball/champions-league) and its [CC0 license](https://github.com/openfootball/champions-league/blob/master/LICENSE.md).

## World Cup

Registered as `SOURCE_AVAILABLE` for future research only via [openfootball/worldcup](https://github.com/openfootball/worldcup). It is outside the P0/P1 club-strength gate and no national-team model is started.

## K League

`K_LEAGUE_SOURCE_GAP=true`. The official K League terms restrict copying/publishing/providing data without prior permission and prohibit commercial use in the relevant clause; no compliant free source was adopted. See [K League terms](https://portal.kleague.com/user/service/userTermsNice.do).

## API-Football

`DEFER`: future candidate only. No API key, paid plan, runtime network call, or fake response is enabled in Phase 2B.3. Coverage and pricing must be re-reviewed before adoption.

The requested Agent-Reach CLI was not available in this Codex environment; bounded official-source discovery used direct source pages as a fallback.
