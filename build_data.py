#!/usr/bin/env python3
"""Compute all stats for Craig Cup end-of-season review.
Writes data/computed.json that the HTML deck consumes.
"""
import json
import os
from collections import defaultdict, Counter
from datetime import datetime

DATA = 'data'

def load(p):
    with open(os.path.join(DATA, p)) as f:
        return json.load(f)

league = load('league_details.json')
bootstrap = load('bootstrap_static.json')
draft = load('draft_choices.json')
transactions_raw = load('transactions.json')['transactions']
trades = load('trades.json')['trades']

# Maps
players = {el['id']: el for el in bootstrap['elements']}
teams_map = {t['id']: t for t in bootstrap['teams']}
positions_map = {pt['id']: pt for pt in bootstrap['element_types']}

# Manager mapping
managers = {}
for le in league['league_entries']:
    managers[le['entry_id']] = {
        'entry_id': le['entry_id'],
        'le_id': le['id'],
        'first_name': le['player_first_name'],
        'last_name': le['player_last_name'],
        'team_name': le['entry_name'],
        'short_name': le['short_name'],
    }
# also le_id -> entry_id
le_to_entry = {m['le_id']: m['entry_id'] for m in managers.values()}

# Finished matches only
matches = [m for m in league['matches'] if m.get('finished')]
last_gw = max(m['event'] for m in matches)
print(f"Last finished GW: {last_gw}, matches: {len(matches)}")

# Load picks per (entry, gw)
picks_by_eg = {}
for fn in os.listdir(os.path.join(DATA, 'picks')):
    entry, gw = fn.replace('.json','').split('_gw')
    entry, gw = int(entry), int(gw)
    if gw > last_gw:
        continue
    with open(os.path.join(DATA, 'picks', fn)) as f:
        picks_by_eg[(entry, gw)] = json.load(f)

# Load player history
player_hist = {}
for fn in os.listdir(os.path.join(DATA, 'player_history')):
    pid = int(fn.replace('.json',''))
    with open(os.path.join(DATA, 'player_history', fn)) as f:
        d = json.load(f)
        # Build event -> total_points
        ph = {}
        for h in d.get('history', []):
            if h['event'] <= last_gw:
                ph[h['event']] = {'points': h['total_points'], 'minutes': h.get('minutes', 0)}
        player_hist[pid] = ph

# Helper: player points in GW
def player_points(pid, gw):
    return player_hist.get(pid, {}).get(gw, {}).get('points', 0)

def player_mins(pid, gw):
    return player_hist.get(pid, {}).get(gw, {}).get('minutes', 0)

def player_name(pid):
    p = players.get(pid)
    return p['web_name'] if p else f'Player {pid}'

def player_team(pid):
    p = players.get(pid)
    return teams_map.get(p['team'], {}).get('short_name', '???') if p else '???'

def player_pos(pid):
    p = players.get(pid)
    return positions_map.get(p['element_type'], {}).get('singular_name_short', '???') if p else '???'

# Build ownership timeline: for each player, list of (gw_in, gw_out, owner_entry)
# Initial: draft picks at GW1
ownership = defaultdict(list)  # pid -> list of (start_gw, end_gw or None, entry_id)
draft_owner = {}  # pid -> entry_id (original drafter)
for c in draft['choices']:
    pid = c['element']
    entry = c['entry']
    draft_owner[pid] = entry
    ownership[pid].append({'start': 1, 'end': None, 'entry': entry})

# Process accepted transactions in order
# A transaction: element_in goes TO entry (effective the GW it happens). element_out leaves the entry.
# In draft FPL transactions take effect for the GW listed in 'event'.
accepted_tx = sorted([t for t in transactions_raw if t.get('result') == 'a'], key=lambda x: (x['event'], x.get('id', 0)))

# Process trades (state 'a' or 'p' - 'p' might be processed/accepted)
# From the trades, state is 'p' = processed/accepted. element_in goes from offered TO received? Let me check.
# Each tradeitem: element_in is the player that came IN to offered_entry. element_out is what left offered_entry.
# So element_in from offered_entry's perspective = goes to offered. element_out from offered = leaves offered (to received).
# So: offered gains element_in, loses element_out. received gains element_out, loses element_in.

# Build a unified events list: (gw_effective, kind, ...details)
ownership_events = []  # (gw, entry_to, entry_from, pid)
for tx in accepted_tx:
    gw = tx['event']
    entry = tx['entry']
    pin = tx['element_in']
    pout = tx['element_out']
    # entry gains pin from waivers/free agents (previous owner could be anyone or none)
    # entry loses pout to waivers
    ownership_events.append({'gw': gw, 'pid': pin, 'to': entry, 'from': None, 'kind': tx['kind']})
    ownership_events.append({'gw': gw, 'pid': pout, 'to': None, 'from': entry, 'kind': tx['kind']})

for tr in trades:
    if tr.get('state') != 'a' and tr.get('state') != 'p':
        continue
    gw = tr['event']
    offered = tr['offered_entry']
    received = tr['received_entry']
    for ti in tr['tradeitem_set']:
        ein = ti['element_in']  # to offered
        eout = ti['element_out']  # from offered to received
        ownership_events.append({'gw': gw, 'pid': ein, 'to': offered, 'from': received, 'kind': 't'})
        ownership_events.append({'gw': gw, 'pid': eout, 'to': received, 'from': offered, 'kind': 't'})

ownership_events.sort(key=lambda e: (e['gw'], 0 if e['kind']=='t' else 1))

# Build ownership_by_gw[pid][gw] = entry_id (the manager who owned this player going into this GW)
# Use current_owner dict, update at boundaries
current_owner = dict(draft_owner)  # pid -> entry_id
owner_by_gw = defaultdict(dict)  # pid -> {gw: entry}
for pid, eid in current_owner.items():
    owner_by_gw[pid][1] = eid

# Walk events
events_by_gw = defaultdict(list)
for ev in ownership_events:
    events_by_gw[ev['gw']].append(ev)

# For each GW from 1..last_gw, determine owner: events with event=gw take effect AT that gw (i.e. for that gw's scoring)
# So apply events_by_gw[gw] first, then record owner for that gw
for gw in range(1, last_gw + 1):
    # Apply events for this GW (they take effect this gw)
    for ev in events_by_gw[gw]:
        pid = ev['pid']
        if ev['to'] is not None:
            current_owner[pid] = ev['to']
        elif ev['from'] is not None and current_owner.get(pid) == ev['from']:
            # Only clear if currently owned by from
            if pid in current_owner:
                del current_owner[pid]
    # Snapshot
    for pid, eid in current_owner.items():
        owner_by_gw[pid][gw] = eid

# Tenure-adjusted points: pid -> entry -> total points while owned across all GWs
tenure_points = defaultdict(lambda: defaultdict(int))
for pid, gws in owner_by_gw.items():
    for gw, eid in gws.items():
        pts = player_points(pid, gw)
        tenure_points[pid][eid] += pts

# Now compute per-manager stats
# For each manager, for each GW, what was their lineup (positions 1-11 are starting, 12-15 bench)
# Pass-through subs to figure out auto-subs.
# For our purposes, the actual scoring is in standings/matches. But to detect "goalkeeping howler" we need to know which keeper started.

def get_starting_xi(entry, gw):
    """Return list of player ids in starting XI for this entry+gw, applying auto-subs."""
    data = picks_by_eg.get((entry, gw))
    if not data:
        return []
    starters = [p['element'] for p in data['picks'] if p['position'] <= 11]
    # Apply subs
    subs = data.get('subs', [])
    for s in subs:
        if s['element_out'] in starters:
            idx = starters.index(s['element_out'])
            starters[idx] = s['element_in']
    return starters

def get_full_squad(entry, gw):
    data = picks_by_eg.get((entry, gw))
    if not data:
        return []
    return [p['element'] for p in data['picks']]

def get_two_keepers(entry, gw):
    """Get the 2 GKs owned by entry at this GW (from picks file)"""
    data = picks_by_eg.get((entry, gw))
    if not data:
        return []
    gks = []
    for p in data['picks']:
        pid = p['element']
        if players.get(pid, {}).get('element_type') == 1:
            gks.append((pid, p['position']))
    return gks

# Manager scoring per GW (from matches)
manager_pf_by_gw = defaultdict(dict)  # entry -> gw -> points
for m in matches:
    if m['league_entry_1'] in le_to_entry:
        e1 = le_to_entry[m['league_entry_1']]
        manager_pf_by_gw[e1][m['event']] = m['league_entry_1_points']
    if m['league_entry_2'] in le_to_entry:
        e2 = le_to_entry[m['league_entry_2']]
        manager_pf_by_gw[e2][m['event']] = m['league_entry_2_points']

# H2H results: per manager, per GW, list of opponents and result
# Each GW has 3 matches covering all 6 managers
h2h_by_gw = defaultdict(list)  # entry -> list of dicts {gw, opp, my_score, opp_score, result}
for m in matches:
    gw = m['event']
    le1, le2 = m['league_entry_1'], m['league_entry_2']
    if le1 not in le_to_entry or le2 not in le_to_entry:
        continue
    e1, e2 = le_to_entry[le1], le_to_entry[le2]
    s1, s2 = m['league_entry_1_points'], m['league_entry_2_points']
    if s1 > s2:
        r1, r2 = 'W', 'L'
    elif s2 > s1:
        r1, r2 = 'L', 'W'
    else:
        r1, r2 = 'D', 'D'
    h2h_by_gw[e1].append({'gw': gw, 'opp': e2, 'my_score': s1, 'opp_score': s2, 'result': r1})
    h2h_by_gw[e2].append({'gw': gw, 'opp': e1, 'my_score': s2, 'opp_score': s1, 'result': r2})

# Sort each manager's h2h by gw
for e in h2h_by_gw:
    h2h_by_gw[e].sort(key=lambda x: x['gw'])

# Build league standings per GW (running)
# Win=3, Draw=1, Loss=0. Tiebreak: total points-for.
def compute_standings_at(gw_target):
    s = {e: {'w':0,'d':0,'l':0,'pf':0,'pa':0,'pts':0} for e in managers}
    for m in matches:
        if m['event'] > gw_target:
            continue
        le1, le2 = m['league_entry_1'], m['league_entry_2']
        if le1 not in le_to_entry or le2 not in le_to_entry:
            continue
        e1, e2 = le_to_entry[le1], le_to_entry[le2]
        sc1, sc2 = m['league_entry_1_points'], m['league_entry_2_points']
        s[e1]['pf'] += sc1
        s[e2]['pf'] += sc2
        s[e1]['pa'] += sc2
        s[e2]['pa'] += sc1
        if sc1 > sc2:
            s[e1]['w'] += 1; s[e2]['l'] += 1
            s[e1]['pts'] += 3
        elif sc2 > sc1:
            s[e2]['w'] += 1; s[e1]['l'] += 1
            s[e2]['pts'] += 3
        else:
            s[e1]['d'] += 1; s[e2]['d'] += 1
            s[e1]['pts'] += 1; s[e2]['pts'] += 1
    # Sort
    sorted_eids = sorted(s.keys(), key=lambda e: (-s[e]['pts'], -s[e]['pf']))
    ranks = {}
    for i, e in enumerate(sorted_eids):
        ranks[e] = i + 1
    return s, ranks

# Position-over-time
position_history = {e: [] for e in managers}  # list of (gw, rank)
for gw in range(1, last_gw + 1):
    s, ranks = compute_standings_at(gw)
    for e in managers:
        position_history[e].append({'gw': gw, 'rank': ranks[e], 'pts': s[e]['pts'], 'pf': s[e]['pf']})

# Final standings (just take last)
final_standings = position_history  # has all
# Final table sorted
final_ranks = sorted(managers.keys(), key=lambda e: position_history[e][-1]['rank'])

# Per-manager stats
mgr_stats = {}
for e in managers:
    hist = h2h_by_gw[e]
    pf = sum(h['my_score'] for h in hist)
    pa = sum(h['opp_score'] for h in hist)
    w = sum(1 for h in hist if h['result']=='W')
    d = sum(1 for h in hist if h['result']=='D')
    l = sum(1 for h in hist if h['result']=='L')
    pts = w*3 + d
    # High/low single GW score
    if hist:
        high = max(hist, key=lambda x: x['my_score'])
        low = min(hist, key=lambda x: x['my_score'])
    else:
        high = low = None
    # Streaks
    def longest_streak(seq, predicate):
        best = 0
        best_start = None
        cur = 0
        cur_start = None
        best_end = None
        for i, x in enumerate(seq):
            if predicate(x):
                if cur == 0:
                    cur_start = x['gw']
                cur += 1
                if cur > best:
                    best = cur
                    best_start = cur_start
                    best_end = x['gw']
            else:
                cur = 0
                cur_start = None
        return {'len': best, 'start': best_start, 'end': best_end}
    win_streak = longest_streak(hist, lambda x: x['result']=='W')
    loss_streak = longest_streak(hist, lambda x: x['result']=='L')
    unbeaten = longest_streak(hist, lambda x: x['result'] in ('W','D'))
    winless = longest_streak(hist, lambda x: x['result'] in ('L','D'))
    # Nemesis
    opp_count = Counter()
    for h in hist:
        if h['result'] == 'L':
            opp_count[h['opp']] += 1
    nemesis = opp_count.most_common(1)[0] if opp_count else None
    nemesis_gws = []
    if nemesis:
        nemesis_gws = [h['gw'] for h in hist if h['opp']==nemesis[0] and h['result']=='L']
    # Transactions
    my_tx = [t for t in accepted_tx if t['entry'] == e]
    tx_count = len(my_tx)
    tx_by_gw = Counter()
    for t in my_tx:
        tx_by_gw[t['event']] += 1
    # Longest dormant stretch
    dormant_best = 0
    dormant_start = None
    dormant_end = None
    cur_run = 0
    cur_start = None
    for gw in range(1, last_gw + 1):
        if tx_by_gw[gw] == 0:
            if cur_run == 0:
                cur_start = gw
            cur_run += 1
            if cur_run > dormant_best:
                dormant_best = cur_run
                dormant_start = cur_start
                dormant_end = gw
        else:
            cur_run = 0
    # Best & worst tenure-adjusted moves
    # Look at each (pid) that this manager owned at some point
    pid_pts = []
    for pid, gws in owner_by_gw.items():
        held_gws = [gw for gw, eid in gws.items() if eid == e]
        if not held_gws:
            continue
        total_pts = sum(player_points(pid, gw) for gw in held_gws)
        pid_pts.append({'pid': pid, 'pts': total_pts, 'gws_held': len(held_gws),
                        'name': player_name(pid), 'team': player_team(pid),
                        'first_gw': min(held_gws), 'last_gw': max(held_gws),
                        'drafted': draft_owner.get(pid) == e})
    pid_pts.sort(key=lambda x: -x['pts'])
    best_move = pid_pts[0] if pid_pts else None
    # Worst move: a player they signed (not drafted) but performed badly
    signed = [p for p in pid_pts if not p['drafted'] and p['gws_held'] >= 1]
    signed.sort(key=lambda x: x['pts'])
    worst_move = signed[0] if signed else None
    mgr_stats[e] = {
        'pf': pf, 'pa': pa, 'w': w, 'd': d, 'l': l, 'pts': pts,
        'high': {'pts': high['my_score'], 'gw': high['gw'], 'opp': high['opp']} if high else None,
        'low': {'pts': low['my_score'], 'gw': low['gw'], 'opp': low['opp']} if low else None,
        'win_streak': win_streak, 'loss_streak': loss_streak,
        'unbeaten': unbeaten, 'winless': winless,
        'nemesis': {'opp': nemesis[0], 'count': nemesis[1], 'gws': nemesis_gws} if nemesis else None,
        'tx_count': tx_count,
        'tx_by_gw': dict(tx_by_gw),
        'dormant': {'len': dormant_best, 'start': dormant_start, 'end': dormant_end},
        'best_move': best_move,
        'worst_move': worst_move,
    }

# ===============
# Big H2H beating
# ===============
biggest_margin = max(matches, key=lambda m: abs(m['league_entry_1_points'] - m['league_entry_2_points']))
closest = min([m for m in matches if abs(m['league_entry_1_points']-m['league_entry_2_points'])>0],
              key=lambda m: abs(m['league_entry_1_points']-m['league_entry_2_points']))

# Highest single-GW score (any manager)
all_gw_scores = []
for e in managers:
    for h in h2h_by_gw[e]:
        all_gw_scores.append({'entry': e, 'gw': h['gw'], 'score': h['my_score']})
# Unique by entry+gw (h2h doubles up since each manager plays 3)
# Actually h2h_by_gw doubles because each manager plays 3 opponents per GW, but my_score is same — pick first per (entry, gw)
seen = set()
gw_scores = []
for x in all_gw_scores:
    k = (x['entry'], x['gw'])
    if k in seen: continue
    seen.add(k)
    gw_scores.append(x)
highest_gw = max(gw_scores, key=lambda x: x['score'])
lowest_gw = min(gw_scores, key=lambda x: x['score'])

# ====================
# Goalkeeping howler
# ====================
howler_count = defaultdict(int)  # entry -> count of GWs where wrong keeper started
howler_details = defaultdict(list)
for entry in managers:
    for gw in range(1, last_gw + 1):
        gks = get_two_keepers(entry, gw)
        if len(gks) < 2:
            continue
        # Find which is in starting XI (position <= 11)
        starting_gk = next((pid for pid, pos in gks if pos <= 11), None)
        bench_gk = next((pid for pid, pos in gks if pos > 11), None)
        if not starting_gk or not bench_gk:
            continue
        # Apply auto-subs - but for keepers auto-sub only happens if starter didn't play
        # For howler, judge by raw points
        start_pts = player_points(starting_gk, gw)
        bench_pts = player_points(bench_gk, gw)
        if bench_pts > start_pts:
            howler_count[entry] += 1
            howler_details[entry].append({'gw': gw, 'wrong_pts': start_pts, 'right_pts': bench_pts,
                                          'wrong': player_name(starting_gk), 'right': player_name(bench_gk)})

# ============
# Phantom XI
# ============
phantom_finds = []  # list of (entry, gw, num_zeros)
for entry in managers:
    for gw in range(1, last_gw + 1):
        xi = get_starting_xi(entry, gw)
        zeros = [pid for pid in xi if player_mins(pid, gw) == 0]
        if len(zeros) >= 4:
            phantom_finds.append({'entry': entry, 'gw': gw, 'count': len(zeros),
                                  'players': [{'pid': p, 'name': player_name(p), 'team': player_team(p)} for p in zeros],
                                  'all_xi': [{'pid': p, 'name': player_name(p), 'team': player_team(p)} for p in xi]})
phantom_finds.sort(key=lambda x: -x['count'])

# =====================
# Hot potato / players
# =====================
hot_potato_pid = {}
for pid, gws in owner_by_gw.items():
    owners = set(gws.values())
    if len(owners) >= 4:
        hot_potato_pid[pid] = sorted(owners)

# Per player: list of (owner, run of GWs)
def owner_runs(pid):
    runs = []
    items = sorted(owner_by_gw[pid].items())
    if not items: return runs
    cur_owner = items[0][1]
    cur_start = items[0][0]
    cur_end = items[0][0]
    for gw, e in items[1:]:
        if e == cur_owner and gw == cur_end + 1:
            cur_end = gw
        else:
            runs.append({'owner': cur_owner, 'start': cur_start, 'end': cur_end})
            cur_owner = e
            cur_start = gw
            cur_end = gw
    runs.append({'owner': cur_owner, 'start': cur_start, 'end': cur_end})
    return runs

# ============
# Revolving door / re-signings
# ============
# For each (entry, pid), count how many times the manager signed this player (separate ownership runs initiated by transaction)
resignings = defaultdict(lambda: defaultdict(int))  # entry -> pid -> count
# Use transactions: each accepted tx where element_in IS pid going TO entry is a "signing"
for t in accepted_tx:
    resignings[t['entry']][t['element_in']] += 1
# Also trades
for tr in trades:
    if tr.get('state') not in ('a','p'): continue
    for ti in tr['tradeitem_set']:
        # offered gains element_in
        resignings[tr['offered_entry']][ti['element_in']] += 1
        resignings[tr['received_entry']][ti['element_out']] += 1

# Repeat signings: same entry signed same pid >=2 times
revolving = defaultdict(list)  # entry -> [(pid, count)]
for entry, d in resignings.items():
    for pid, c in d.items():
        if c >= 2:
            revolving[entry].append({'pid': pid, 'name': player_name(pid), 'team': player_team(pid), 'count': c})
for entry in revolving:
    revolving[entry].sort(key=lambda x: -x['count'])

# ============
# Welcome and Goodbye - signed, never started, dropped within 3 GWs
# ============
welcome_goodbye = []
for entry in managers:
    runs = []
    # Build per-player runs for this entry from owner_by_gw
    pid_to_runs = defaultdict(list)
    for pid in owner_by_gw:
        oruns = owner_runs(pid)
        for r in oruns:
            if r['owner'] == entry:
                pid_to_runs[pid].append(r)
    # Only consider acquired (not drafted) - first run starts at GW > 1 OR was preceded by another manager
    for pid, prs in pid_to_runs.items():
        for r in prs:
            if r['start'] == 1 and draft_owner.get(pid) == entry:
                continue  # initial draft
            if r['end'] - r['start'] + 1 > 3:
                continue
            # Did they ever start them?
            started_ever = False
            for gw in range(r['start'], r['end']+1):
                xi = get_starting_xi(entry, gw)
                if pid in xi:
                    started_ever = True
                    break
            if not started_ever:
                welcome_goodbye.append({'entry': entry, 'pid': pid, 'name': player_name(pid),
                                       'start': r['start'], 'end': r['end']})

# ============
# Most Influential Transfer (find biggest tenure-adjusted point swing from waiver/free agent or trade)
# ============
# For each accepted transaction or trade, compute the net swing
# A signing brings player in. Tenure points = sum of player_points(pid, gw) while owned thereafter (until next removal)
# Best draft pick: find player still owned by drafter, with highest tenure points
draft_picks_perf = []
for c in draft['choices']:
    pid = c['element']
    drafter = c['entry']
    # Get tenure points for drafter
    held_gws = [gw for gw, eid in owner_by_gw[pid].items() if eid == drafter]
    pts = sum(player_points(pid, gw) for gw in held_gws)
    draft_picks_perf.append({'pid': pid, 'name': player_name(pid), 'team': player_team(pid),
                             'drafter': drafter, 'round': c['round'], 'pick': c['index'],
                             'pts': pts, 'gws_held': len(held_gws), 'still_owned': owner_by_gw[pid].get(last_gw) == drafter})

# Best draft pick = highest pts (tenure-adjusted)
draft_picks_perf.sort(key=lambda x: -x['pts'])
best_draft_pick = draft_picks_perf[0]

# ============
# Transfers performance
# ============
# For each accepted waiver/FA: track points scored by acquired player while owned by acquirer
transfer_perf = []
for t in accepted_tx:
    pid = t['element_in']
    entry = t['entry']
    gw_in = t['event']
    # Find the ownership run that started at gw_in for this entry
    # Sum points in that run
    runs = owner_runs(pid)
    target_run = None
    for r in runs:
        if r['owner'] == entry and r['start'] == gw_in:
            target_run = r
            break
    if not target_run:
        # Maybe owner started earlier (continued)
        for r in runs:
            if r['owner'] == entry and r['start'] <= gw_in <= r['end']:
                target_run = r
                break
    if not target_run:
        continue
    pts = sum(player_points(pid, gw) for gw in range(target_run['start'], target_run['end']+1))
    transfer_perf.append({'pid': pid, 'name': player_name(pid), 'team': player_team(pid),
                          'entry': entry, 'gw_in': gw_in, 'gw_out': target_run['end'],
                          'pts': pts, 'kind': t['kind']})

transfer_perf.sort(key=lambda x: -x['pts'])

# Most Influential Transfer (override): The spec says Gittens by Christopher
gittens_pid = 239
chris_entry = 76250
# Find Christopher's Gittens transaction
gittens_tx = next((t for t in transfer_perf if t['pid']==gittens_pid and t['entry']==chris_entry), None)

# ============
# The Cliff / Right Place Right Time
# Form before vs after signing
# ============
def avg_pts(pid, gws):
    pts = [player_points(pid, gw) for gw in gws if gw in player_hist.get(pid, {})]
    return sum(pts)/len(pts) if pts else 0

cliff_candidates = []
rprt_candidates = []
for t in accepted_tx:
    pid = t['element_in']
    gw = t['event']
    before = [g for g in range(max(1, gw-4), gw)]
    after = [g for g in range(gw, min(last_gw, gw+3)+1)]
    if len(before) < 2 or len(after) < 2: continue
    b_avg = avg_pts(pid, before)
    a_avg = avg_pts(pid, after)
    swing = a_avg - b_avg
    rec = {'pid': pid, 'name': player_name(pid), 'team': player_team(pid),
           'entry': t['entry'], 'gw': gw, 'before_avg': b_avg, 'after_avg': a_avg, 'swing': swing}
    if swing <= -4 and b_avg >= 5:
        cliff_candidates.append(rec)
    if swing >= 5 and a_avg >= 5:
        rprt_candidates.append(rec)
cliff_candidates.sort(key=lambda x: x['swing'])
rprt_candidates.sort(key=lambda x: -x['swing'])

# ============
# Trade analysis
# ============
trade_results = []
for tr in trades:
    if tr.get('state') not in ('a','p'): continue
    gw = tr['event']
    offered = tr['offered_entry']
    received = tr['received_entry']
    items = tr['tradeitem_set']
    # For offered: gains element_in players, loses element_out players
    # For received: gains element_out players, loses element_in players
    # Compute points tenure-adjusted from gw onward for these players, in the runs initiated by this trade
    def points_for_run(pid, entry, start_gw):
        runs = owner_runs(pid)
        for r in runs:
            if r['owner'] == entry and r['start'] <= start_gw <= r['end']:
                return sum(player_points(pid, g) for g in range(r['start'], r['end']+1)), r['end'] - r['start'] + 1
        return 0, 0
    offered_gain = []
    received_gain = []
    for ti in items:
        ein = ti['element_in']  # to offered
        eout = ti['element_out']  # to received (from offered)
        pts_off, dur_off = points_for_run(ein, offered, gw)
        pts_rec, dur_rec = points_for_run(eout, received, gw)
        offered_gain.append({'pid': ein, 'name': player_name(ein), 'pts': pts_off, 'gws_held': dur_off})
        received_gain.append({'pid': eout, 'name': player_name(eout), 'pts': pts_rec, 'gws_held': dur_rec})
    off_total = sum(x['pts'] for x in offered_gain)
    rec_total = sum(x['pts'] for x in received_gain)
    diff = off_total - rec_total  # positive = offered won
    # Determine verdict
    abs_diff = abs(diff)
    winner_total = max(off_total, rec_total)
    loser_total = min(off_total, rec_total)
    if max(off_total, rec_total) < 30 and abs_diff < 30:
        verdict = 'MUCH ADO ABOUT NOTHING'
    elif abs_diff >= 60 and winner_total >= 50:
        verdict = 'STEAL'
    elif abs_diff >= 25 and min(off_total, rec_total) >= 20:
        verdict = 'WIN'
    elif abs_diff >= 25:
        verdict = 'NEITHER BENEFITED'
    else:
        verdict = 'FAIR'
    trade_results.append({
        'gw': gw,
        'offered_entry': offered,
        'received_entry': received,
        'offered_gain': offered_gain,
        'received_gain': received_gain,
        'offered_total': off_total,
        'received_total': rec_total,
        'verdict': verdict,
        'diff': diff,
    })

# Best trade (most lopsided real value)
best_trade = max(trade_results, key=lambda x: max(x['offered_total'], x['received_total']))

# ===========
# Lacroix Story (pid for Lacroix)
# ===========
lacroix_id = next((p['id'] for p in bootstrap['elements'] if 'lacroix' in p['second_name'].lower()), None)
dewsbury_id = next((p['id'] for p in bootstrap['elements'] if 'dewsbury' in (p.get('second_name','') or '').lower()), None)
senesi_id = next((p['id'] for p in bootstrap['elements'] if 'senesi' in (p.get('second_name','') or '').lower()), None)
mukiele_id = next((p['id'] for p in bootstrap['elements'] if 'mukiele' in (p.get('second_name','') or '').lower()), None)

# Build signing histories for these key players
def signing_history(pid):
    history = []
    # initial draft
    do = draft_owner.get(pid)
    if do:
        history.append({'gw': 1, 'kind': 'draft', 'to': do})
    for t in accepted_tx:
        if t['element_in'] == pid:
            history.append({'gw': t['event'], 'kind': 'sign', 'to': t['entry']})
        if t['element_out'] == pid:
            history.append({'gw': t['event'], 'kind': 'drop', 'from': t['entry']})
    for tr in trades:
        if tr.get('state') not in ('a','p'): continue
        for ti in tr['tradeitem_set']:
            if ti['element_in'] == pid:
                history.append({'gw': tr['event'], 'kind': 'trade-in', 'to': tr['offered_entry']})
            if ti['element_out'] == pid:
                history.append({'gw': tr['event'], 'kind': 'trade-in', 'to': tr['received_entry']})
    return history

lacroix_history = signing_history(lacroix_id) if lacroix_id else []
dewsbury_history = signing_history(dewsbury_id) if dewsbury_id else []
senesi_history = signing_history(senesi_id) if senesi_id else []
mukiele_history = signing_history(mukiele_id) if mukiele_id else []

# ==========
# Club concentration: 5+ players from one club in a manager's XI
# ==========
identity_finds = []
for entry in managers:
    for gw in range(1, last_gw+1):
        xi = get_starting_xi(entry, gw)
        team_counts = Counter()
        for pid in xi:
            team_counts[players.get(pid,{}).get('team')] += 1
        for team_id, cnt in team_counts.items():
            if cnt >= 4:
                identity_finds.append({'entry': entry, 'gw': gw, 'team': team_id,
                                       'team_short': teams_map.get(team_id,{}).get('short_name'),
                                       'team_name': teams_map.get(team_id,{}).get('name'),
                                       'count': cnt})

# ==========
# Squad churn per manager per GW
# ==========
squad_changes = defaultdict(dict)  # entry -> gw -> count of players changed vs prev gw
for entry in managers:
    prev_squad = None
    for gw in range(1, last_gw+1):
        squad = set(get_full_squad(entry, gw))
        if prev_squad is not None:
            changes = len(squad - prev_squad)
            squad_changes[entry][gw] = changes
        prev_squad = squad

# ==========
# Most-signed player (across all managers)
# ==========
total_signings_per_pid = Counter()
for t in accepted_tx:
    total_signings_per_pid[t['element_in']] += 1
most_signed = total_signings_per_pid.most_common(10)

# Hot potato sorted by # of distinct managers
hot_potatoes = []
for pid in owner_by_gw:
    owners = list(set(owner_by_gw[pid].values()))
    if len(owners) >= 3:
        hot_potatoes.append({'pid': pid, 'name': player_name(pid), 'team': player_team(pid),
                             'managers': sorted(owners), 'count': len(owners)})
hot_potatoes.sort(key=lambda x: -x['count'])

# ==========
# Build h2h pairings record
# ==========
pair_record = defaultdict(lambda: {'w': 0, 'l': 0, 'd': 0, 'gws': []})
for h in h2h_by_gw:
    pass

# ==========
# Counterfactual: Everyone Plays Pete
# ==========
pete = 76213
pete_score_by_gw = manager_pf_by_gw[pete]
# League average excluding Pete per GW (for Pete's row)
avg_excl_pete = {}
for gw in range(1, last_gw+1):
    scores = [manager_pf_by_gw[e].get(gw) for e in managers if e != pete and manager_pf_by_gw[e].get(gw) is not None]
    avg_excl_pete[gw] = sum(scores) / len(scores) if scores else 0

# For each manager (incl Pete), play vs Pete (or vs avg if Pete) every GW
counterfactual_pete = {}
for e in managers:
    w = d = l = 0
    pf = pa = 0
    for gw in range(1, last_gw+1):
        my = manager_pf_by_gw[e].get(gw)
        if my is None: continue
        if e == pete:
            opp = avg_excl_pete[gw]
        else:
            opp = pete_score_by_gw.get(gw, 0)
        pf += my
        pa += opp
        if my > opp: w += 1
        elif my < opp: l += 1
        else: d += 1
    counterfactual_pete[e] = {'w': w, 'd': d, 'l': l, 'pts': w*3+d, 'pf': pf, 'pa': pa}

# Sort
cf_pete_sorted = sorted(managers.keys(), key=lambda e: (-counterfactual_pete[e]['pts'], -counterfactual_pete[e]['pf']))

# ==========
# Counterfactual: No transfers ever (GW1 squad scores every week)
# ==========
counterfactual_notrans = {}
for e in managers:
    gw1_picks = picks_by_eg.get((e, 1), {}).get('picks', [])
    gw1_squad_pids = [p['element'] for p in gw1_picks]
    # Starting XI = positions 1-11 from gw1
    # "No transfers ever" — manager's GW1 starting XI plays every week.
    # FPL auto-sub mechanism: a starter who played 0 minutes is replaced by
    # the first bench player of any position who played, then by a positional
    # bench player. We apply a minimal auto-sub: scan bench in order, swap in
    # any player who played for any non-playing starter, respecting formation
    # mins (3 DEF, 2 MID, 1 FWD).
    starting_pids = [p['element'] for p in gw1_picks if p['position'] <= 11]
    bench_pids = [p['element'] for p in gw1_picks if p['position'] > 11]
    total = 0
    by_gw = {}
    for gw in range(1, last_gw+1):
        xi = list(starting_pids)
        bench = list(bench_pids)
        # Auto-sub: for each non-playing starter, find a bench player who played
        for i, pid in enumerate(xi):
            if player_mins(pid, gw) > 0: continue
            # Find a sub from bench that maintains valid formation
            starter_type = players.get(pid,{}).get('element_type')
            # Count current types in XI
            for j, bp in enumerate(bench):
                if player_mins(bp, gw) == 0: continue
                bench_type = players.get(bp,{}).get('element_type')
                # Determine new XI types if we swap
                new_xi = xi[:i] + [bp] + xi[i+1:]
                counts = Counter(players.get(p,{}).get('element_type') for p in new_xi)
                # Must satisfy 1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD
                if (counts.get(1,0) == 1 and 3 <= counts.get(2,0) <= 5
                    and 2 <= counts.get(3,0) <= 5 and 1 <= counts.get(4,0) <= 3):
                    xi[i] = bp
                    bench[j] = pid
                    break
        gw_pts = sum(player_points(pid, gw) for pid in xi)
        total += gw_pts
        by_gw[gw] = gw_pts
    counterfactual_notrans[e] = {'total': total, 'by_gw': by_gw}

# Convert to H2H using same fixture list
def get_match_fixture(e1, e2, gw):
    """Return whether e1 vs e2 played in gw"""
    pass

cf_notrans_h2h = {e: {'w':0,'d':0,'l':0,'pts':0,'pf':0,'pa':0} for e in managers}
for m in matches:
    le1, le2 = m['league_entry_1'], m['league_entry_2']
    if le1 not in le_to_entry or le2 not in le_to_entry: continue
    e1, e2 = le_to_entry[le1], le_to_entry[le2]
    gw = m['event']
    s1 = counterfactual_notrans[e1]['by_gw'].get(gw, 0)
    s2 = counterfactual_notrans[e2]['by_gw'].get(gw, 0)
    cf_notrans_h2h[e1]['pf'] += s1
    cf_notrans_h2h[e2]['pf'] += s2
    cf_notrans_h2h[e1]['pa'] += s2
    cf_notrans_h2h[e2]['pa'] += s1
    if s1 > s2:
        cf_notrans_h2h[e1]['w']+=1; cf_notrans_h2h[e2]['l']+=1; cf_notrans_h2h[e1]['pts']+=3
    elif s2 > s1:
        cf_notrans_h2h[e2]['w']+=1; cf_notrans_h2h[e1]['l']+=1; cf_notrans_h2h[e2]['pts']+=3
    else:
        cf_notrans_h2h[e1]['d']+=1; cf_notrans_h2h[e2]['d']+=1
        cf_notrans_h2h[e1]['pts']+=1; cf_notrans_h2h[e2]['pts']+=1

cf_notrans_sorted = sorted(managers.keys(), key=lambda e: (-cf_notrans_h2h[e]['pts'], -cf_notrans_h2h[e]['pf']))

# ==========
# Counterfactual: Optimal XI every week
# ==========
counterfactual_optimal = {}
optimal_h2h = {e: {'w':0,'d':0,'l':0,'pts':0,'pf':0,'pa':0} for e in managers}
optimal_by_gw = defaultdict(dict)
for e in managers:
    for gw in range(1, last_gw+1):
        squad = get_full_squad(e, gw)
        if not squad: continue
        # Need 1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD, total 11 (FPL settings)
        gks = sorted([p for p in squad if players.get(p,{}).get('element_type')==1], key=lambda p: -player_points(p, gw))
        defs = sorted([p for p in squad if players.get(p,{}).get('element_type')==2], key=lambda p: -player_points(p, gw))
        mids = sorted([p for p in squad if players.get(p,{}).get('element_type')==3], key=lambda p: -player_points(p, gw))
        fwds = sorted([p for p in squad if players.get(p,{}).get('element_type')==4], key=lambda p: -player_points(p, gw))
        if not gks: continue
        best = 0
        # Try all valid formations: 3-5 DEF, 2-5 MID, 1-3 FWD, sum=10
        for nd in range(3, 6):
            for nm in range(2, 6):
                for nf in range(1, 4):
                    if nd + nm + nf != 10: continue
                    if len(defs) < nd or len(mids) < nm or len(fwds) < nf: continue
                    pts = player_points(gks[0], gw) + sum(player_points(p, gw) for p in defs[:nd]) + sum(player_points(p, gw) for p in mids[:nm]) + sum(player_points(p, gw) for p in fwds[:nf])
                    if pts > best: best = pts
        optimal_by_gw[e][gw] = best

for m in matches:
    le1, le2 = m['league_entry_1'], m['league_entry_2']
    if le1 not in le_to_entry or le2 not in le_to_entry: continue
    e1, e2 = le_to_entry[le1], le_to_entry[le2]
    gw = m['event']
    s1 = optimal_by_gw[e1].get(gw, 0)
    s2 = optimal_by_gw[e2].get(gw, 0)
    optimal_h2h[e1]['pf'] += s1; optimal_h2h[e2]['pf'] += s2
    optimal_h2h[e1]['pa'] += s2; optimal_h2h[e2]['pa'] += s1
    if s1>s2:
        optimal_h2h[e1]['w']+=1; optimal_h2h[e2]['l']+=1; optimal_h2h[e1]['pts']+=3
    elif s2>s1:
        optimal_h2h[e2]['w']+=1; optimal_h2h[e1]['l']+=1; optimal_h2h[e2]['pts']+=3
    else:
        optimal_h2h[e1]['d']+=1; optimal_h2h[e2]['d']+=1
        optimal_h2h[e1]['pts']+=1; optimal_h2h[e2]['pts']+=1
cf_optimal_sorted = sorted(managers.keys(), key=lambda e: (-optimal_h2h[e]['pts'], -optimal_h2h[e]['pf']))

# ==========
# Christopher streak GW32-36
# ==========
# Look at Christopher's recent run
chris_recent = [h for h in h2h_by_gw[chris_entry] if h['gw'] >= 30]
# Steven six-in-a-row search GW12-17
steven_e = 76218
steven_h = h2h_by_gw[steven_e]

# Position #1 weeks
weeks_at_one = Counter()
for e in managers:
    for ph in position_history[e]:
        if ph['rank'] == 1:
            weeks_at_one[e] += 1

# Leader changes
leader_changes = []
prev_leader = None
for gw in range(1, last_gw+1):
    leader = None
    best_pts = -1
    best_pf = -1
    for e in managers:
        rec = position_history[e][gw-1]
        if rec['rank'] == 1:
            leader = e
            break
    if leader != prev_leader:
        leader_changes.append({'gw': gw, 'leader': leader, 'previous': prev_leader})
        prev_leader = leader

# Geraint's title margin
geraint = 76226
geraint_final = position_history[geraint][-1]['pts']
runner_up_eid = sorted(managers.keys(), key=lambda e: -position_history[e][-1]['pts'])[1]
runner_up_final = position_history[runner_up_eid][-1]['pts']
title_margin = geraint_final - runner_up_final

# Geraint's late panic stretch: count tx GW31-33
geraint_tx_31_33 = sum(mgr_stats[geraint]['tx_by_gw'].get(gw, 0) for gw in range(31, 34))

# 5-pt or closer H2H matches
close_matches = sum(1 for m in matches if 0 < abs(m['league_entry_1_points'] - m['league_entry_2_points']) <= 5)

# Total distinct players in starting XIs
distinct_xi_pids = set()
for entry in managers:
    for gw in range(1, last_gw+1):
        for pid in get_starting_xi(entry, gw):
            distinct_xi_pids.add(pid)

# Build the output JSON
output = {
    'last_gw': last_gw,
    'managers': {
        str(e): {
            **m,
            **{k: v for k, v in mgr_stats[e].items()},
            'position_history': [p['rank'] for p in position_history[e]],
            'pf_history': [p['pf'] for p in position_history[e]],
            'pts_history': [p['pts'] for p in position_history[e]],
            'h2h': h2h_by_gw[e],
        } for e, m in managers.items()
    },
    'final_order': [str(e) for e in final_ranks],
    'players': {str(pid): {'name': p['web_name'], 'team': teams_map.get(p['team'],{}).get('short_name'),
                            'pos': positions_map.get(p['element_type'],{}).get('singular_name_short'),
                            'first': p['first_name'], 'last': p['second_name']}
                for pid, p in players.items()},
    'biggest_margin': {
        'gw': biggest_margin['event'],
        'le1': le_to_entry.get(biggest_margin['league_entry_1']),
        'le2': le_to_entry.get(biggest_margin['league_entry_2']),
        's1': biggest_margin['league_entry_1_points'],
        's2': biggest_margin['league_entry_2_points'],
    },
    'closest_match': {
        'gw': closest['event'],
        'le1': le_to_entry.get(closest['league_entry_1']),
        'le2': le_to_entry.get(closest['league_entry_2']),
        's1': closest['league_entry_1_points'],
        's2': closest['league_entry_2_points'],
    },
    'highest_gw': highest_gw,
    'lowest_gw': lowest_gw,
    'howler_count': dict(howler_count),
    'howler_details': {str(k): v for k, v in howler_details.items()},
    'phantom_finds': phantom_finds[:5],
    'hot_potatoes': hot_potatoes[:5],
    'revolving': {str(k): v[:8] for k, v in revolving.items()},
    'welcome_goodbye': welcome_goodbye[:10],
    'best_draft_pick': best_draft_pick,
    'draft_picks_top': draft_picks_perf[:10],
    'transfer_perf_top': transfer_perf[:10],
    'gittens_tx': gittens_tx,
    'cliff_candidates': cliff_candidates[:5],
    'rprt_candidates': rprt_candidates[:5],
    'trades': trade_results,
    'best_trade': best_trade,
    'lacroix_history': lacroix_history,
    'dewsbury_history': dewsbury_history,
    'senesi_history': senesi_history,
    'mukiele_history': mukiele_history,
    'identity_finds': identity_finds,
    'squad_changes': {str(k): dict(v) for k, v in squad_changes.items()},
    'most_signed': [{'pid': pid, 'name': player_name(pid), 'team': player_team(pid), 'count': c} for pid, c in most_signed],
    'weeks_at_one': dict(weeks_at_one),
    'leader_changes': leader_changes,
    'title_margin': title_margin,
    'geraint_tx_31_33': geraint_tx_31_33,
    'close_matches': close_matches,
    'distinct_xi_count': len(distinct_xi_pids),
    'counterfactual_pete': {
        'rows': [{'entry': e, **counterfactual_pete[e]} for e in cf_pete_sorted]
    },
    'counterfactual_notrans': {
        'rows': [{'entry': e, **cf_notrans_h2h[e]} for e in cf_notrans_sorted]
    },
    'counterfactual_optimal': {
        'rows': [{'entry': e, **optimal_h2h[e]} for e in cf_optimal_sorted]
    },
    'pete_score_by_gw': pete_score_by_gw,
    'manager_pf_by_gw': {str(k): dict(v) for k, v in manager_pf_by_gw.items()},
    'total_tx': len(accepted_tx),
    'total_trades': len(trade_results),
    'player_pts_by_gw': {
        # Only for players relevant to stories (Gittens, Dewsbury-Hall, Lacroix, Senesi)
        str(pid): {str(gw): h['points'] for gw, h in player_hist.get(pid, {}).items()}
        for pid in [gittens_pid, dewsbury_id, lacroix_id, senesi_id, mukiele_id] if pid
    },
    'gittens_pid': gittens_pid,
    'dewsbury_pid': dewsbury_id,
    'lacroix_pid': lacroix_id,
    'senesi_pid': senesi_id,
    'mukiele_pid': mukiele_id,
    'optimal_by_gw': {str(k): dict(v) for k, v in optimal_by_gw.items()},
}

# Custom JSON-safe encoding (ints from defaultdicts etc.)
def to_jsonable(o):
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [to_jsonable(x) for x in o]
    if isinstance(o, (int, float, str, bool)) or o is None:
        return o
    return str(o)

with open(os.path.join(DATA, 'computed.json'), 'w') as f:
    json.dump(to_jsonable(output), f, separators=(',', ':'))

print('Wrote data/computed.json')
print('Title margin:', title_margin)
print('Howler counts:', dict(howler_count))
print('Phantom finds:', len(phantom_finds))
print('Revolving:')
for e, v in revolving.items():
    print(f"  {managers[e]['first_name']}: {[(p['name'], p['count']) for p in v[:5]]}")
print('Best draft pick:', best_draft_pick['name'], 'by', managers[best_draft_pick['drafter']]['first_name'], 'pts:', best_draft_pick['pts'])
print('Best trade:', best_trade['verdict'], 'GW', best_trade['gw'])
print('Highest GW:', highest_gw)
print('Lowest GW:', lowest_gw)
print('Hot potatoes:', [(h['name'], h['count']) for h in hot_potatoes[:5]])
print('Phantom top:', phantom_finds[0] if phantom_finds else None)
print('Identity finds:', len(identity_finds))
print('Lacroix history:', lacroix_history)
print('Dewsbury history:', dewsbury_history)
print('Counterfactual Pete:', cf_pete_sorted)
print('Counterfactual no transfers:', cf_notrans_sorted)
print('Counterfactual optimal:', cf_optimal_sorted)
print('Weeks at #1:', dict(weeks_at_one))
print('Gittens tx:', gittens_tx)
print('Close matches (<=5):', close_matches)
print('Total accepted tx:', len(accepted_tx))
print('Total distinct XI players:', len(distinct_xi_pids))
