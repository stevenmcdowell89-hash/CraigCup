#!/usr/bin/env python3
"""Compute everything for the Craig Cup deck deterministically."""
import json, os, glob
from collections import defaultdict, Counter

DATA = 'data'
def J(p): return json.load(open(os.path.join(DATA, p)))

ld = J('league_details.json')
bs = J('bootstrap_static.json')
tx_raw = J('transactions.json')['transactions']
tr_raw = J('trades.json')['trades']
dc_raw = J('draft_choices.json')['choices']
game = J('game.json')

# ---------------- Mapping ----------------
entries = ld['league_entries']
LE_TO_ENTRY = {e['id']: e['entry_id'] for e in entries}  # league_entry id -> entry_id (used in picks)
ENTRY_TO_LE = {v: k for k, v in LE_TO_ENTRY.items()}
ENTRY_NAME = {76178: 'Mark', 76213: 'Peter', 76218: 'Steven', 76226: 'Geraint', 76238: 'Michael', 76250: 'Christopher'}
TEAM_NAME = {76178: 'Carrying Timber', 76213: 'MaxPoints', 76218: '✨', 76226: '🏴󠁧󠁢󠁷󠁬󠁳󠁿', 76238: 'Jota win again *20', 76250: 'The Masterplan'}
LE_NAME = {ENTRY_TO_LE[eid]: name for eid, name in ENTRY_NAME.items()}
LE_TEAM = {ENTRY_TO_LE[eid]: tname for eid, tname in TEAM_NAME.items()}
ALL_ENTRIES = list(ENTRY_NAME.keys())
ALL_LE = list(LE_TO_ENTRY.keys())

ELEMENTS = {e['id']: e for e in bs['elements']}
TEAMS = {t['id']: t for t in bs['teams']}
POS_NAME = {1:'GK', 2:'DEF', 3:'MID', 4:'FWD'}

def pname(eid):
    e = ELEMENTS.get(eid, {})
    return e.get('web_name', f'#{eid}')

def pteam(eid):
    e = ELEMENTS.get(eid, {})
    return TEAMS.get(e.get('team'), {}).get('short_name', '?')

def ppos(eid):
    e = ELEMENTS.get(eid, {})
    return POS_NAME.get(e.get('element_type'), '?')

# ---------------- Finished matches ----------------
finished_matches = [m for m in ld['matches'] if m['finished']]
LAST_GW = max(m['event'] for m in finished_matches) if finished_matches else 0
print(f'Last finished GW: {LAST_GW}')
GWS = list(range(1, LAST_GW + 1))

# ---------------- Player history (per-GW points) ----------------
# player_history files keyed by element id
PLAYER_PTS = {}  # element_id -> {gw: points}
PLAYER_MINS = {}  # element_id -> {gw: minutes}
for path in glob.glob('data/player_history/*.json'):
    eid = int(os.path.basename(path).split('.')[0])
    h = json.load(open(path))
    pts = {}
    mins = {}
    for entry in h.get('history', []):
        gw = entry['event']
        pts[gw] = pts.get(gw, 0) + entry.get('total_points', 0)
        mins[gw] = mins.get(gw, 0) + entry.get('minutes', 0)
    PLAYER_PTS[eid] = pts
    PLAYER_MINS[eid] = mins

def pts_for(eid, gw):
    return PLAYER_PTS.get(eid, {}).get(gw, 0)

def mins_for(eid, gw):
    return PLAYER_MINS.get(eid, {}).get(gw, 0)

# ---------------- Picks per manager per GW ----------------
PICKS = {}  # entry_id -> gw -> picks dict
for path in glob.glob('data/picks/*.json'):
    base = os.path.basename(path).split('.')[0]
    eid, gw = base.split('_gw')
    eid = int(eid); gw = int(gw)
    PICKS.setdefault(eid, {})[gw] = json.load(open(path))

# starting XI = positions 1..11 (multiplier=1)
def starting_xi(entry, gw):
    p = PICKS.get(entry, {}).get(gw)
    if not p: return []
    return [pk for pk in p['picks'] if pk['position'] <= 11]

def all_squad(entry, gw):
    p = PICKS.get(entry, {}).get(gw)
    if not p: return []
    return p['picks']

def starting_score(entry, gw):
    """Score from starting XI, applying auto-subs.
    The 'picks' as recorded reflect pre-subs ordering. The 'subs' field shows auto-subs that occurred.
    We compute score = sum of points for the 11 starters, BUT with auto-subs applied:
    if a starter got 0 minutes and a bench player came on for them per the subs list, that bench player's points count.
    """
    p = PICKS.get(entry, {}).get(gw)
    if not p: return 0
    starters = [pk for pk in p['picks'] if pk['position'] <= 11]
    bench = [pk for pk in p['picks'] if pk['position'] > 11]
    starter_ids = [pk['element'] for pk in starters]
    bench_ids = [pk['element'] for pk in bench]
    subs = p.get('subs', []) or []
    # apply subs: replace element_out with element_in in starter_ids
    final_ids = list(starter_ids)
    for s in subs:
        if s['element_out'] in final_ids:
            idx = final_ids.index(s['element_out'])
            final_ids[idx] = s['element_in']
    return sum(pts_for(pid, gw) for pid in final_ids)

# starting_score using ORIGINAL XI without subs (for "started X but he got 0 mins" type analysis)
def started_ids(entry, gw):
    return [pk['element'] for pk in starting_xi(entry, gw)]

# ---------------- H2H per GW ----------------
# Build per-GW scores from actual lineups (sanity check vs match data)
MATCH_BY_GW = defaultdict(list)
for m in finished_matches:
    MATCH_BY_GW[m['event']].append(m)

# Per-GW score per league_entry
GW_SCORE = defaultdict(dict)  # gw -> le_id -> score
for m in finished_matches:
    GW_SCORE[m['event']][m['league_entry_1']] = m['league_entry_1_points']
    GW_SCORE[m['event']][m['league_entry_2']] = m['league_entry_2_points']

# Sanity check vs computed starting_score
mismatches = 0
for gw in GWS:
    for le in ALL_LE:
        if le not in GW_SCORE[gw]: continue
        computed = starting_score(LE_TO_ENTRY[le], gw)
        actual = GW_SCORE[gw][le]
        if computed != actual:
            mismatches += 1
            if mismatches <= 3:
                print(f'  Mismatch gw{gw} {LE_NAME[le]}: computed {computed} vs actual {actual}')
print(f'GW score mismatches: {mismatches}')

# ---------------- Standings recomputed from finished only ----------------
STAND = {le: {'w':0,'d':0,'l':0,'pf':0,'pa':0} for le in ALL_LE}
for m in finished_matches:
    le1, le2 = m['league_entry_1'], m['league_entry_2']
    p1, p2 = m['league_entry_1_points'], m['league_entry_2_points']
    STAND[le1]['pf'] += p1; STAND[le1]['pa'] += p2
    STAND[le2]['pf'] += p2; STAND[le2]['pa'] += p1
    if p1 > p2: STAND[le1]['w']+=1; STAND[le2]['l']+=1
    elif p1 < p2: STAND[le2]['w']+=1; STAND[le1]['l']+=1
    else: STAND[le1]['d']+=1; STAND[le2]['d']+=1

for le in STAND:
    STAND[le]['total'] = STAND[le]['w']*3 + STAND[le]['d']

# Sort
table = sorted(ALL_LE, key=lambda le: (-STAND[le]['total'], -STAND[le]['pf']))
print('\nRecomputed standings (finished only):')
for i, le in enumerate(table, 1):
    s = STAND[le]
    print(f'  {i}. {LE_NAME[le]:11s} W{s["w"]} D{s["d"]} L{s["l"]}  PF={s["pf"]} PA={s["pa"]} Total={s["total"]}')

# ---------------- League position per GW ----------------
RUNNING = {le: {'w':0,'d':0,'l':0,'pf':0,'pa':0} for le in ALL_LE}
POS_BY_GW = defaultdict(dict)  # gw -> le -> position
for gw in GWS:
    for m in MATCH_BY_GW[gw]:
        le1, le2 = m['league_entry_1'], m['league_entry_2']
        p1, p2 = m['league_entry_1_points'], m['league_entry_2_points']
        RUNNING[le1]['pf'] += p1; RUNNING[le1]['pa'] += p2
        RUNNING[le2]['pf'] += p2; RUNNING[le2]['pa'] += p1
        if p1 > p2: RUNNING[le1]['w']+=1; RUNNING[le2]['l']+=1
        elif p1 < p2: RUNNING[le2]['w']+=1; RUNNING[le1]['l']+=1
        else: RUNNING[le1]['d']+=1; RUNNING[le2]['d']+=1
    snap = sorted(ALL_LE, key=lambda le: (-(RUNNING[le]['w']*3+RUNNING[le]['d']), -RUNNING[le]['pf']))
    for pos, le in enumerate(snap, 1):
        POS_BY_GW[gw][le] = pos

# Weeks at #1
weeks_at_1 = Counter()
for gw in GWS:
    for le, pos in POS_BY_GW[gw].items():
        if pos == 1: weeks_at_1[le] += 1

print('\nWeeks at #1:')
for le, n in weeks_at_1.most_common():
    print(f'  {LE_NAME[le]}: {n}')

# ---------------- H2H streaks per manager ----------------
def streaks_for(le):
    results = []  # list of 'W'/'D'/'L' per GW in order, BUT each GW has 1 H2H match per manager
    for gw in GWS:
        for m in MATCH_BY_GW[gw]:
            if m['league_entry_1'] == le:
                p1, p2 = m['league_entry_1_points'], m['league_entry_2_points']
                if p1>p2: results.append('W')
                elif p1<p2: results.append('L')
                else: results.append('D')
                break
            elif m['league_entry_2'] == le:
                p1, p2 = m['league_entry_1_points'], m['league_entry_2_points']
                if p2>p1: results.append('W')
                elif p2<p1: results.append('L')
                else: results.append('D')
                break
    return results

def longest_run(results, condition):
    best = 0; cur = 0; best_start = 0; cur_start = 0
    best_end = 0
    for i, r in enumerate(results):
        if condition(r):
            if cur == 0: cur_start = i
            cur += 1
            if cur > best:
                best = cur; best_start = cur_start; best_end = i
        else:
            cur = 0
    return best, best_start+1, best_end+1  # 1-indexed gw

STREAKS = {}
for le in ALL_LE:
    res = streaks_for(le)
    win_streak = longest_run(res, lambda r: r=='W')
    loss_streak = longest_run(res, lambda r: r=='L')
    unbeaten = longest_run(res, lambda r: r in ('W','D'))
    winless = longest_run(res, lambda r: r in ('L','D'))
    STREAKS[le] = {'results': res, 'win':win_streak, 'loss':loss_streak, 'unbeaten':unbeaten, 'winless':winless}
    print(f'  {LE_NAME[le]}: WStreak={win_streak} LStreak={loss_streak}')

# ---------------- Transactions ----------------
# Accepted transactions only
accepted_tx = [t for t in tx_raw if t['result'] == 'a' and t['event'] <= LAST_GW]
print(f'\nAccepted transactions (finished GWs): {len(accepted_tx)}')

tx_per_entry = Counter()
tx_per_entry_per_gw = defaultdict(lambda: defaultdict(int))
for t in accepted_tx:
    tx_per_entry[t['entry']] += 1
    tx_per_entry_per_gw[t['entry']][t['event']] += 1

print('Total accepted txn per manager:')
for entry, n in tx_per_entry.most_common():
    print(f'  {ENTRY_NAME[entry]}: {n}')

# Dormant stretches
def dormant_run(entry):
    best = 0; cur = 0; best_start = 0; cur_start = 0; best_end = 0
    for gw in GWS:
        if tx_per_entry_per_gw[entry].get(gw, 0) == 0:
            if cur == 0: cur_start = gw
            cur += 1
            if cur > best:
                best = cur; best_start = cur_start; best_end = gw
        else:
            cur = 0
    return best, best_start, best_end

print('Longest dormant stretch:')
DORMANT = {}
for entry in ALL_ENTRIES:
    d = dormant_run(entry)
    DORMANT[entry] = d
    print(f'  {ENTRY_NAME[entry]}: {d[0]} GWs (GW{d[1]}-{d[2]})')

# 3-week rolling window (busiest)
print('Busiest 3-week rolling:')
BUSIEST3 = {}
for entry in ALL_ENTRIES:
    best = 0; best_gw = 1
    for gw in GWS:
        s = sum(tx_per_entry_per_gw[entry].get(g, 0) for g in range(gw, gw+3))
        if s > best: best = s; best_gw = gw
    BUSIEST3[entry] = (best, best_gw, best_gw+2)
    print(f'  {ENTRY_NAME[entry]}: {best} in GW{best_gw}-{best_gw+2}')

# ---------------- Ownership timeline ----------------
# Reconstruct: each player has a list of (gw, entry, IN/OUT) events sourced from draft + trades + transactions
# Draft = IN at gw 0 (pre-season)
events = defaultdict(list)  # element_id -> list of (gw, entry, action, source)
for pick in dc_raw:
    events[pick['element']].append((0, pick['entry'], 'IN', 'draft'))
for tr in tr_raw:
    if tr.get('state') != 'a':
        # The 'p' state appears to mean processed/accepted in this API. Treat 'a' or 'p' as accepted; skip 'r' (rejected).
        if tr.get('state') == 'r': continue
    gw = tr['event']
    for item in tr['tradeitem_set']:
        # element_in = comes IN to offered_entry; element_out = goes OUT from offered_entry
        # Trade structure: offered_entry offers element_out and gets element_in from received_entry
        offered = tr['offered_entry']; received = tr['received_entry']
        events[item['element_in']].append((gw, received, 'OUT', 'trade'))
        events[item['element_in']].append((gw, offered, 'IN', 'trade'))
        events[item['element_out']].append((gw, offered, 'OUT', 'trade'))
        events[item['element_out']].append((gw, received, 'IN', 'trade'))
for t in accepted_tx:
    gw = t['event']
    entry = t['entry']
    # element_in joins entry; element_out leaves entry (becomes free agent or null)
    if t.get('element_in'):
        events[t['element_in']].append((gw, entry, 'IN', 'tx'))
    if t.get('element_out'):
        events[t['element_out']].append((gw, entry, 'OUT', 'tx'))

# Sort events per player
for pid in events:
    events[pid].sort(key=lambda x: (x[0], 0 if x[2]=='OUT' else 1))

# Build ownership intervals: for each player, list of (entry, start_gw, end_gw) where start_gw=1 means owned at GW1 etc.
# Draft picks own from GW1 onwards until first OUT event.
OWN_INTERVALS = defaultdict(list)  # element_id -> list of (entry, start_gw, end_gw_inclusive)
for pid, evs in events.items():
    cur_owner = None
    cur_start = None
    for (gw, entry, action, src) in evs:
        if action == 'IN':
            # If from draft, gw=0 -> ownership starts GW1
            actual_start = 1 if gw == 0 else gw
            if cur_owner == entry:
                continue  # already owned (shouldn't happen)
            if cur_owner is not None:
                # close previous interval at gw-1
                OWN_INTERVALS[pid].append((cur_owner, cur_start, gw - 1 if gw > 0 else 0))
            cur_owner = entry
            cur_start = actual_start
        elif action == 'OUT':
            if cur_owner == entry:
                OWN_INTERVALS[pid].append((cur_owner, cur_start, gw - 1 if gw > 0 else 0))
                # but wait - if dropped GW=5, they're not owned in GW5? Actually transactions resolve before GW deadline.
                # Convention: action at GW X means ownership changes for GW X onwards.
                # So if dropped at GW 5, they were owned through GW 4. If signed at GW 5, owned from GW 5.
                # Let's set end = gw - 1 for OUT.
                cur_owner = None
                cur_start = None
            # else: spurious OUT, ignore
    if cur_owner is not None:
        OWN_INTERVALS[pid].append((cur_owner, cur_start, LAST_GW))

# Quick fix: the above can produce overlapping or wrong intervals when trade has both IN/OUT at same gw for same entry.
# Recompute more carefully with state machine:
OWN_INTERVALS = defaultdict(list)
for pid, evs in events.items():
    cur_owner = None
    cur_start = None
    # group events by gw
    by_gw = defaultdict(list)
    for ev in evs:
        by_gw[ev[0]].append(ev)
    sorted_gws = sorted(by_gw.keys())
    for gw in sorted_gws:
        # apply OUTs first, then INs
        outs = [e for e in by_gw[gw] if e[2]=='OUT']
        ins = [e for e in by_gw[gw] if e[2]=='IN']
        for (_, entry, _, _) in outs:
            if cur_owner == entry:
                end = (gw - 1) if gw > 0 else 0
                if cur_start is not None and end >= cur_start:
                    OWN_INTERVALS[pid].append((cur_owner, cur_start, end))
                cur_owner = None
                cur_start = None
        for (_, entry, _, _) in ins:
            start = 1 if gw == 0 else gw
            if cur_owner is not None and cur_owner != entry:
                end = (gw - 1) if gw > 0 else 0
                if cur_start is not None and end >= cur_start:
                    OWN_INTERVALS[pid].append((cur_owner, cur_start, end))
            cur_owner = entry
            cur_start = start
    if cur_owner is not None and cur_start is not None and cur_start <= LAST_GW:
        OWN_INTERVALS[pid].append((cur_owner, cur_start, LAST_GW))

# Tenure-adjusted points for any owner of any player
def tenure_pts(pid, entry, start_gw=None, end_gw=None):
    """Sum points scored by player while owned by entry. Optionally within window."""
    total = 0
    for (owner, s, e) in OWN_INTERVALS.get(pid, []):
        if owner != entry: continue
        rs = max(s, start_gw) if start_gw else s
        re_ = min(e, end_gw) if end_gw else e
        for gw in range(rs, re_+1):
            total += pts_for(pid, gw)
    return total

# ---------------- Best draft pick ----------------
print('\nBest draft picks (tenure-adjusted):')
draft_evals = []
for pick in dc_raw:
    pid = pick['element']
    entry = pick['entry']
    pts = tenure_pts(pid, entry)
    draft_evals.append((pts, pick['pick'] if False else pick['round'], pick['index'], pid, entry, pick))
draft_evals.sort(reverse=True)
for d in draft_evals[:12]:
    print(f'  Round {d[5]["round"]} pick #{d[2]} ({ENTRY_NAME[d[4]]}): {pname(d[3])} = {d[0]} pts')

# Calculate value relative to draft position: actual_pts - expected_pts_for_pick_index
# Use full-season totals of all drafted players as a baseline
draft_index_sorted = sorted(dc_raw, key=lambda x: x['index'])
# expected_pts at index i = average of all drafted players' season totals sorted by index? Actually too noisy.
# Just rank by raw tenure pts as primary metric, with caveat for late picks.
# Compute "value over pick" = tenure_pts - median tenure_pts of picks at similar index
# Simpler: best pick = highest tenure_pts. But also flag "best late pick" (round 8+).
best_pick = draft_evals[0]
print(f'  BEST OVERALL: {pname(best_pick[3])} drafted by {ENTRY_NAME[best_pick[4]]} at pick #{best_pick[2]} (round {best_pick[5]["round"]}) = {best_pick[0]} pts')

# Best late round pick (round 8+)
late_picks = [d for d in draft_evals if d[5]['round'] >= 8]
print(f'  BEST LATE PICK (R8+): {pname(late_picks[0][3])} pick #{late_picks[0][2]} ({ENTRY_NAME[late_picks[0][4]]}) = {late_picks[0][0]} pts')

# ---------------- Best trade ----------------
print('\nTrades analysis:')
trade_analyses = []
for tr in tr_raw:
    if tr.get('state') == 'r': continue
    gw = tr['event']
    offered = tr['offered_entry']  # gives element_out, receives element_in
    received = tr['received_entry']  # gives element_in, receives element_out
    given_by_offered = []
    given_by_received = []
    for item in tr['tradeitem_set']:
        # element_out leaves offered, element_in leaves received
        given_by_offered.append(item['element_out'])
        given_by_received.append(item['element_in'])

    # Points scored by acquired players for the offered side, from gw to LAST_GW
    offered_gain = sum(tenure_pts(pid, offered, gw, LAST_GW) for pid in given_by_received)
    offered_loss = sum(pts_for(pid, g) for pid in given_by_offered for g in range(gw, LAST_GW+1))
    # Actually "loss" should be: points those players would have scored for offered if they'd kept them.
    # Counter-factually, points scored by given_by_offered while they were NOT owned by offered after trade.
    # Approximation: in this window, simply sum total points scored across the rest of the season for the players given away (whether or not they remained with the recipient).

    received_gain = sum(tenure_pts(pid, received, gw, LAST_GW) for pid in given_by_offered)
    received_loss = sum(pts_for(pid, g) for pid in given_by_received for g in range(gw, LAST_GW+1))

    offered_net = offered_gain - offered_loss
    received_net = received_gain - received_loss

    info = {
        'gw': gw, 'offered': offered, 'received': received,
        'offered_gives': given_by_offered, 'offered_gets': given_by_received,
        'offered_gain': offered_gain, 'offered_loss': offered_loss, 'offered_net': offered_net,
        'received_gain': received_gain, 'received_loss': received_loss, 'received_net': received_net,
    }
    trade_analyses.append(info)
    print(f'  GW{gw}: {ENTRY_NAME[offered]} gives {[pname(p) for p in given_by_offered]} -> gets {[pname(p) for p in given_by_received]}')
    print(f'    {ENTRY_NAME[offered]}: gain {offered_gain} from acquired, lost potential {offered_loss}. Net {offered_net}')
    print(f'    {ENTRY_NAME[received]}: gain {received_gain} from acquired, lost potential {received_loss}. Net {received_net}')

# Best trade = max absolute differential
best_trade = max(trade_analyses, key=lambda t: max(t['offered_gain'], t['received_gain']))
print(f'  BEST TRADE (highest gain by one side): GW{best_trade["gw"]}')

# ---------------- Hot Potato (player owned by multiple managers) ----------------
print('\nHot potatoes (signed by 3+ different managers):')
hot_potatoes = []
for pid, intervals in OWN_INTERVALS.items():
    owners = set(iv[0] for iv in intervals)
    if len(owners) >= 3:
        # Count distinct signings (transactions IN + draft + trade IN)
        signings = 0
        for ev in events.get(pid, []):
            if ev[2] == 'IN' and ev[3] in ('tx', 'trade'):
                signings += 1
        hot_potatoes.append((len(owners), signings, pid, intervals))
hot_potatoes.sort(reverse=True)
for hp in hot_potatoes[:10]:
    print(f'  {pname(hp[2])}: owned by {hp[0]} managers, {hp[1]} signings')
    for iv in hp[3]:
        print(f'    {ENTRY_NAME[iv[0]]}: GW{iv[1]}-{iv[2]}')

# Lacroix
lacroix_id = None
for e in bs['elements']:
    if e.get('second_name', '').lower() == 'lacroix' or 'lacroix' in e.get('web_name','').lower():
        lacroix_id = e['id']
        print(f'\nLacroix id={lacroix_id} ({e["web_name"]})')
        break
if lacroix_id:
    print(f'  Events for Lacroix:')
    for ev in events.get(lacroix_id, []):
        print(f'    GW{ev[0]} {ENTRY_NAME.get(ev[1], "?")} {ev[2]} ({ev[3]})')
    print(f'  Intervals:')
    for iv in OWN_INTERVALS.get(lacroix_id, []):
        print(f'    {ENTRY_NAME[iv[0]]} GW{iv[1]}-{iv[2]}')

# Senesi
senesi_id = None
for e in bs['elements']:
    if 'senesi' in e.get('second_name', '').lower() or 'senesi' in e.get('web_name','').lower():
        senesi_id = e['id']
        print(f'\nSenesi id={senesi_id} ({e["web_name"]})')
        break
if senesi_id:
    for ev in events.get(senesi_id, []):
        print(f'    GW{ev[0]} {ENTRY_NAME.get(ev[1], "?")} {ev[2]} ({ev[3]})')

# Mukiele
mukiele_id = None
for e in bs['elements']:
    if 'mukiele' in e.get('second_name', '').lower() or 'mukiele' in e.get('web_name','').lower():
        mukiele_id = e['id']
        print(f'\nMukiele id={mukiele_id} ({e["web_name"]})')
        break
if mukiele_id:
    for ev in events.get(mukiele_id, []):
        print(f'    GW{ev[0]} {ENTRY_NAME.get(ev[1], "?")} {ev[2]} ({ev[3]})')

# ---------------- Repeat signings (per manager) ----------------
print('\nRepeat signings by manager:')
repeat_by_entry = defaultdict(Counter)
for t in accepted_tx:
    if t.get('element_in'):
        repeat_by_entry[t['entry']][t['element_in']] += 1
for entry, cnt in repeat_by_entry.items():
    repeats = [(c, pid) for pid, c in cnt.items() if c >= 2]
    repeats.sort(reverse=True)
    if repeats:
        print(f'  {ENTRY_NAME[entry]}:')
        for c, pid in repeats[:8]:
            print(f'    {pname(pid)} signed {c} times')

# ---------------- The Cliff (player form vs signing) ----------------
print('\nForm vs signing analysis (waiver/FA signings):')
form_analyses = []
for t in accepted_tx:
    if t['kind'] not in ('w', 'f'): continue
    if not t.get('element_in'): continue
    pid = t['element_in']
    gw = t['event']
    # Avg in 4 GWs before vs 4 GWs after
    before_gws = [g for g in range(max(1, gw-4), gw)]
    after_gws = [g for g in range(gw, min(LAST_GW, gw+3)+1)]
    if not before_gws or not after_gws: continue
    bef_pts = [pts_for(pid, g) for g in before_gws]
    aft_pts = [pts_for(pid, g) for g in after_gws]
    if not bef_pts or not aft_pts: continue
    bef_avg = sum(bef_pts)/len(bef_pts)
    aft_avg = sum(aft_pts)/len(aft_pts)
    swing = aft_avg - bef_avg
    form_analyses.append((swing, gw, t['entry'], pid, bef_avg, aft_avg))

cliffs = sorted(form_analyses)[:10]
spikes = sorted(form_analyses, reverse=True)[:10]
print('Biggest cliffs (worst form drop after signing):')
for s in cliffs:
    print(f'  GW{s[1]} {ENTRY_NAME[s[2]]} signed {pname(s[3])}: bef avg {s[4]:.1f} -> aft {s[5]:.1f} (swing {s[0]:+.1f})')
print('Biggest spikes (best form pickup):')
for s in spikes:
    print(f'  GW{s[1]} {ENTRY_NAME[s[2]]} signed {pname(s[3])}: bef avg {s[4]:.1f} -> aft {s[5]:.1f} (swing {s[0]:+.1f})')

# Specifically: Dewsbury-Hall
kdh_id = None
for e in bs['elements']:
    if 'dewsbury' in e.get('second_name','').lower():
        kdh_id = e['id']
        print(f'\nDewsbury-Hall id={kdh_id} ({e["web_name"]})')
        break
if kdh_id:
    print(f'  Per-GW pts: {[(g, pts_for(kdh_id, g)) for g in GWS if pts_for(kdh_id, g) != 0]}')
    print(f'  Events:')
    for ev in events.get(kdh_id, []):
        print(f'    GW{ev[0]} {ENTRY_NAME.get(ev[1], "?")} {ev[2]} ({ev[3]})')

# ---------------- Goalkeeping howler ----------------
print('\nGoalkeeping howler counts (wrong keeper started, when manager owned 2 keepers):')
howler = Counter()
for entry in ALL_ENTRIES:
    for gw in GWS:
        p = PICKS.get(entry, {}).get(gw)
        if not p: continue
        # find owned GKs
        gks = [pk for pk in p['picks'] if ELEMENTS.get(pk['element'], {}).get('element_type') == 1]
        if len(gks) != 2: continue
        started_gk = next((pk for pk in gks if pk['position'] <= 11), None)
        bench_gk = next((pk for pk in gks if pk['position'] > 11), None)
        if not started_gk or not bench_gk: continue
        sp = pts_for(started_gk['element'], gw)
        bp = pts_for(bench_gk['element'], gw)
        if bp > sp:
            howler[entry] += 1
print('Howler counts:')
for entry, n in howler.most_common():
    print(f'  {ENTRY_NAME[entry]}: {n}')

# ---------------- Phantom XI (players with 0 mins in starting XI) ----------------
print('\nPhantom XI analysis (post-auto-subs starting XI players with 0 mins):')
phantom = []
for entry in ALL_ENTRIES:
    for gw in GWS:
        p = PICKS.get(entry, {}).get(gw)
        if not p: continue
        starters = [pk for pk in p['picks'] if pk['position'] <= 11]
        bench = [pk for pk in p['picks'] if pk['position'] > 11]
        starter_ids = [pk['element'] for pk in starters]
        subs = p.get('subs', []) or []
        final_ids = list(starter_ids)
        for s in subs:
            if s['element_out'] in final_ids:
                idx = final_ids.index(s['element_out'])
                final_ids[idx] = s['element_in']
        zero_mins = [pid for pid in final_ids if mins_for(pid, gw) == 0]
        if len(zero_mins) >= 4:
            phantom.append((len(zero_mins), entry, gw, zero_mins))
phantom.sort(reverse=True)
for ph in phantom[:10]:
    print(f'  {ENTRY_NAME[ph[1]]} GW{ph[2]}: {ph[0]} starters with 0 mins ({[pname(p) for p in ph[3]]})')

# Also check pre-subs starting XI
print('\nPhantom XI analysis (pre-auto-subs starting XI):')
phantom_pre = []
for entry in ALL_ENTRIES:
    for gw in GWS:
        p = PICKS.get(entry, {}).get(gw)
        if not p: continue
        starters = [pk for pk in p['picks'] if pk['position'] <= 11]
        zero_mins = [pk['element'] for pk in starters if mins_for(pk['element'], gw) == 0]
        if len(zero_mins) >= 4:
            phantom_pre.append((len(zero_mins), entry, gw, zero_mins))
phantom_pre.sort(reverse=True)
for ph in phantom_pre[:10]:
    print(f'  {ENTRY_NAME[ph[1]]} GW{ph[2]}: {ph[0]} starters with 0 mins ({[pname(p) for p in ph[3]]})')

# ---------------- Biggest H2H beating / closest ----------------
print('\nBiggest H2H beating:')
margins = []
for m in finished_matches:
    diff = m['league_entry_1_points'] - m['league_entry_2_points']
    margins.append((abs(diff), m['event'], m, diff))
margins.sort(key=lambda x: (-x[0], x[1]))
for x in margins[:5]:
    m = x[2]
    p1 = m['league_entry_1_points']; p2 = m['league_entry_2_points']
    win_le, lose_le = (m['league_entry_1'], m['league_entry_2']) if p1>p2 else (m['league_entry_2'], m['league_entry_1'])
    print(f'  GW{m["event"]}: {LE_NAME[win_le]} {max(p1,p2)}-{min(p1,p2)} {LE_NAME[lose_le]} (margin {x[0]})')

print('Closest H2H (non-draw):')
non_draw = [x for x in margins if x[0] > 0]
non_draw.sort(key=lambda x: (x[0], x[1]))
for x in non_draw[:5]:
    m = x[2]
    p1 = m['league_entry_1_points']; p2 = m['league_entry_2_points']
    win_le, lose_le = (m['league_entry_1'], m['league_entry_2']) if p1>p2 else (m['league_entry_2'], m['league_entry_1'])
    print(f'  GW{m["event"]}: {LE_NAME[win_le]} {max(p1,p2)}-{min(p1,p2)} {LE_NAME[lose_le]} (margin {x[0]})')

# ---------------- Nemesis per manager ----------------
print('\nNemesis per manager (most-beat-by):')
beat_by = defaultdict(Counter)
beat_gws = defaultdict(lambda: defaultdict(list))
for m in finished_matches:
    le1, le2 = m['league_entry_1'], m['league_entry_2']
    p1, p2 = m['league_entry_1_points'], m['league_entry_2_points']
    if p1 > p2:
        beat_by[le2][le1] += 1
        beat_gws[le2][le1].append(m['event'])
    elif p2 > p1:
        beat_by[le1][le2] += 1
        beat_gws[le1][le2].append(m['event'])
for le in ALL_LE:
    if not beat_by[le]:
        print(f'  {LE_NAME[le]}: no nemesis')
        continue
    nemesis_le, n = beat_by[le].most_common(1)[0]
    print(f'  {LE_NAME[le]}: {LE_NAME[nemesis_le]} ({n} times, GWs {beat_gws[le][nemesis_le]})')

# ---------------- Highest/lowest GW score ----------------
print('\nHighest/lowest single-GW scores:')
gw_scores = []
for gw in GWS:
    for le, s in GW_SCORE[gw].items():
        gw_scores.append((s, gw, le))
gw_scores.sort(reverse=True)
print('Top:')
for s in gw_scores[:5]:
    print(f'  {LE_NAME[s[2]]} GW{s[1]}: {s[0]}')
print('Bottom:')
for s in sorted(gw_scores)[:5]:
    print(f'  {LE_NAME[s[2]]} GW{s[1]}: {s[0]}')

# Per-manager high/low
print('Per-manager high/low:')
HIGHLOW = {}
for le in ALL_LE:
    scores = [(GW_SCORE[gw][le], gw) for gw in GWS]
    hi = max(scores); lo = min(scores)
    HIGHLOW[le] = {'hi': hi, 'lo': lo}
    print(f'  {LE_NAME[le]}: high {hi[0]} (GW{hi[1]}) / low {lo[0]} (GW{lo[1]})')

# ---------------- Club concentration ----------------
print('\nClub concentration (4+ players from one club in starting XI):')
for entry in ALL_ENTRIES:
    for gw in GWS:
        starters = starting_xi(entry, gw)
        teams = Counter(ELEMENTS.get(pk['element'], {}).get('team') for pk in starters)
        most = teams.most_common(1)
        if most and most[0][1] >= 4:
            club_id = most[0][0]
            club_name = TEAMS.get(club_id, {}).get('short_name', '?')
            print(f'  {ENTRY_NAME[entry]} GW{gw}: {most[0][1]} {club_name} players')

# ---------------- Best move / Worst move per manager ----------------
# Best move = highest tenure-adjusted pts from a transaction signing
# Worst move = lowest tenure-adjusted pts from a signing (player picked up that scored minimal)
print('\nBest/worst signings by manager (tenure pts during ownership AFTER signing):')

BEST_WORST = {}
for entry in ALL_ENTRIES:
    signings = []
    for t in accepted_tx:
        if t['entry'] != entry: continue
        if not t.get('element_in'): continue
        pid = t['element_in']
        gw = t['event']
        # find the ownership interval starting at this GW
        pts_held = 0
        for iv in OWN_INTERVALS.get(pid, []):
            if iv[0] == entry and iv[1] == gw:
                for g in range(iv[1], iv[2]+1):
                    pts_held += pts_for(pid, g)
                break
        signings.append((pts_held, pid, gw))
    if not signings: continue
    best = max(signings); worst = min(signings)
    BEST_WORST[entry] = {'best': best, 'worst': worst}
    print(f'  {ENTRY_NAME[entry]}:')
    print(f'    Best signing: {pname(best[1])} GW{best[2]} = {best[0]} pts held')
    print(f'    Worst signing: {pname(worst[1])} GW{worst[2]} = {worst[0]} pts held')

# ---------------- Squad changes per GW per manager (for stories) ----------------
print('\nSquad changes per GW per manager:')
SQUAD_CHANGES = defaultdict(dict)
for entry in ALL_ENTRIES:
    for gw in range(2, LAST_GW+1):
        prev_squad = set(pk['element'] for pk in PICKS.get(entry, {}).get(gw-1, {}).get('picks', []))
        cur_squad = set(pk['element'] for pk in PICKS.get(entry, {}).get(gw, {}).get('picks', []))
        changes = len(cur_squad ^ prev_squad) // 2
        SQUAD_CHANGES[entry][gw] = changes

# Michael GW9-14 churn
print('  Michael GW9-14 squad changes:')
for gw in range(9, 15):
    print(f'    GW{gw}: {SQUAD_CHANGES[76238].get(gw, 0)} changes')

# ---------------- Most-owned player (by total weeks across all managers) ----------------
weeks_owned = Counter()
unique_managers = defaultdict(set)
for pid, intervals in OWN_INTERVALS.items():
    for iv in intervals:
        weeks_owned[pid] += (iv[2] - iv[1] + 1)
        unique_managers[pid].add(iv[0])
# Most-owned: highest weeks_owned
print('\nMost-owned player (total weeks across all managers):')
for pid, w in weeks_owned.most_common(10):
    print(f'  {pname(pid)}: {w} weeks, {len(unique_managers[pid])} managers')

# Player owned by all 6 managers
print('\nPlayers owned by all 6 managers:')
for pid, mgrs in unique_managers.items():
    if len(mgrs) == 6:
        print(f'  {pname(pid)}: {weeks_owned[pid]} weeks')

# ---------------- Gittens (Christopher's transfer) ----------------
print('\nGittens analysis:')
gittens_id = None
for e in bs['elements']:
    if 'gittens' in e.get('second_name','').lower() or 'gittens' in e.get('web_name','').lower():
        gittens_id = e['id']
        print(f'  Gittens id={gittens_id} ({e["web_name"]} {e.get("first_name","")})')
        break
if gittens_id:
    print(f'  Events:')
    for ev in events.get(gittens_id, []):
        print(f'    GW{ev[0]} {ENTRY_NAME.get(ev[1], "?")} {ev[2]} ({ev[3]})')
    print(f'  Intervals:')
    for iv in OWN_INTERVALS.get(gittens_id, []):
        print(f'    {ENTRY_NAME[iv[0]]} GW{iv[1]}-{iv[2]}')
    # Christopher's tenure points
    chris_pts = tenure_pts(gittens_id, 76250)
    print(f'  Total tenure pts for Christopher: {chris_pts}')
    print(f'  Christopher held Gittens GWs:')
    for iv in OWN_INTERVALS.get(gittens_id, []):
        if iv[0] == 76250:
            print(f'    GW{iv[1]}-{iv[2]}: pts each gw {[(g, pts_for(gittens_id, g)) for g in range(iv[1], iv[2]+1)]}')

# ---------------- Liverpool block (Michael GW7) ----------------
print('\nMichael GW7 starting XI:')
mich_gw7 = starting_xi(76238, 7)
for pk in mich_gw7:
    eid = pk['element']
    print(f'  {pname(eid)} ({pteam(eid)})')

# ---------------- Aggregate stats ----------------
print('\nAggregate stats:')
total_tx = len([t for t in accepted_tx])
print(f'  Total accepted transactions: {total_tx}')
print(f'  Total trades: {len(tr_raw)}')
total_pts = sum(sum(GW_SCORE[gw].get(le, 0) for gw in GWS) for le in ALL_LE)
print(f'  Total starting XI points across season: {total_pts}')
# Different players fielded
all_fielded = set()
for entry in ALL_ENTRIES:
    for gw in GWS:
        for pk in PICKS.get(entry, {}).get(gw, {}).get('picks', []):
            all_fielded.add(pk['element'])
print(f'  Distinct players fielded: {len(all_fielded)}')

# ---------------- Welcome and Goodbye: signed, never started, dropped within 3 GWs ----------------
print('\nWelcome and goodbye candidates (signed, never started, dropped within 3 GWs):')
for entry in ALL_ENTRIES:
    cands = []
    for iv in [iv for evs in OWN_INTERVALS.values() for iv in evs]:
        pass  # skip - already iterating
    # Easier: iterate intervals
    pass
welcome_goodbye = []
for pid, intervals in OWN_INTERVALS.items():
    for iv in intervals:
        owner, start, end = iv
        # only consider intervals that came from a signing (not draft / start at 1)
        # check if there was an OUT to end (not LAST_GW)
        duration = end - start + 1
        if duration > 3: continue
        if start == 1: continue  # draft pick
        # Check never started
        ever_started = False
        for gw in range(start, end+1):
            p = PICKS.get(owner, {}).get(gw)
            if p:
                if any(pk['element'] == pid and pk['position'] <= 11 for pk in p['picks']):
                    ever_started = True
                    break
        if not ever_started and end < LAST_GW:
            welcome_goodbye.append((owner, pid, start, end))
# Print top 10
for wg in welcome_goodbye[:20]:
    print(f'  {ENTRY_NAME[wg[0]]}: {pname(wg[1])} (GW{wg[2]}-{wg[3]}, never started)')

# ---------------- One-week wonder (held #1 for exactly 1 GW) ----------------
print('\nWeeks-at-each-position breakdown:')
for le in ALL_LE:
    poscount = Counter(POS_BY_GW[gw][le] for gw in GWS)
    print(f'  {LE_NAME[le]}: {dict(poscount)}')

# Mark held #1?
print('\nWhich GWs each manager was at #1:')
for le in ALL_LE:
    gws_at_1 = [gw for gw in GWS if POS_BY_GW[gw][le] == 1]
    if gws_at_1:
        print(f'  {LE_NAME[le]}: {gws_at_1}')

# ---------------- Three strikes (signed-dropped-signed) ----------------
print('\nThree strikes (player signed-dropped-signed by same manager):')
for entry in ALL_ENTRIES:
    chain = defaultdict(list)
    for t in accepted_tx:
        if t['entry'] != entry: continue
        if t.get('element_in'):
            chain[t['element_in']].append((t['event'], 'IN'))
        if t.get('element_out'):
            chain[t['element_out']].append((t['event'], 'OUT'))
    for pid, ev in chain.items():
        ev.sort()
        pattern = ''.join('I' if e[1]=='IN' else 'O' for e in ev)
        if 'IOI' in pattern:
            count = ev.count((ev[0][0], 'IN')) if False else sum(1 for e in ev if e[1]=='IN')
            if count >= 2:
                pass  # already covered in repeats

# Done
print('\n=== DONE ===')
