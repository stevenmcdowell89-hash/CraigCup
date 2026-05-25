"""Full season analysis for Craig Cup. Writes season_analysis.md."""
import json, os
from collections import defaultdict, Counter

# ---------- Manager mapping ----------
ENTRY = [
    # (league_entry_id, entry_id, first_name, full_name, team_name)
    (73788, 76178, "Mark",        "Mark Craig",        "Carrying Timber"),
    (73822, 76213, "Peter",       "Peter Craig",       "MaxPoints"),
    (73827, 76218, "Steven",      "Steven McDowell",   "✨"),
    (73835, 76226, "Geraint",     "Geraint Hopkins",   "\U0001F3F4\U000E0067\U000E0062\U000E0077\U000E006C\U000E0073\U000E007F"),
    (73847, 76238, "Michael",     "Michael Craig",     "Jota win again *20"),
    (73858, 76250, "Christopher", "christopher craig", "The Masterplan"),
]
LE2ID  = {e[0]: e[1] for e in ENTRY}
ID2LE  = {e[1]: e[0] for e in ENTRY}
LE2FN  = {e[0]: e[2] for e in ENTRY}
LE2TN  = {e[0]: e[4] for e in ENTRY}
ALL_LE = [e[0] for e in ENTRY]

def FN(le_or_eid):
    """Map either league_entry or entry_id to first name."""
    if le_or_eid in LE2FN: return LE2FN[le_or_eid]
    if le_or_eid in ID2LE: return LE2FN[ID2LE[le_or_eid]]
    return f"?({le_or_eid})"

def to_le(eid_or_le):
    return ID2LE.get(eid_or_le, eid_or_le)

# ---------- Load ----------
print("Loading data...")
with open('data/league_details.json') as f: LD = json.load(f)
with open('data/bootstrap_static.json') as f: BS = json.load(f)
with open('data/transactions.json') as f: TX_RAW = json.load(f)
TX = TX_RAW['transactions']
with open('data/trades.json') as f: TR_RAW = json.load(f)
TRADES = TR_RAW['trades']
with open('data/draft_choices.json') as f: DC_RAW = json.load(f)
DC = DC_RAW['choices']
with open('data/element_status.json') as f: ES = json.load(f)

ELEMENTS = {e['id']: e for e in BS['elements']}
TEAMS    = {t['id']: t for t in BS['teams']}
ETYPE    = {1:'GK',2:'DEF',3:'MID',4:'FWD'}

def pname(pid):
    e = ELEMENTS.get(pid)
    if not e: return f"#{pid}"
    return e.get('web_name') or f"{e.get('first_name','')} {e.get('second_name','')}".strip()

# Player history -> {pid: {gw: total_points}} summed across all fixtures (handles DGWs)
print("Loading player history...")
HIST = {}
HIST_BY_FIXTURE = defaultdict(list)
for fn in os.listdir('data/player_history'):
    pid = int(fn.split('.')[0])
    with open(f'data/player_history/{fn}') as f:
        d = json.load(f)
    HIST[pid] = {}
    for ev in d['history']:
        e = ev['event']
        HIST[pid][e] = HIST[pid].get(e, 0) + ev['total_points']
        HIST_BY_FIXTURE[(pid, e)].append(ev)

def pts(pid, gw): return HIST.get(pid, {}).get(gw, 0)
def mins(pid, gw):
    return sum(r['minutes'] for r in HIST_BY_FIXTURE.get((pid, gw), []))

# Picks
print("Loading picks...")
PICKS = {}
for le, eid, *_ in ENTRY:
    for gw in range(1, 39):
        with open(f'data/picks/{eid}_gw{gw}.json') as f:
            PICKS[(le, gw)] = json.load(f)

def starters_raw(le, gw):
    return [p['element'] for p in PICKS[(le, gw)]['picks'] if p['position'] <= 11]
def bench_raw(le, gw):
    return [p['element'] for p in PICKS[(le, gw)]['picks'] if p['position'] > 11]
def squad(le, gw):
    return [p['element'] for p in PICKS[(le, gw)]['picks']]

def final_xi(le, gw):
    starters = starters_raw(le, gw)
    lineup = list(starters)
    for sub in PICKS[(le, gw)].get('subs', []):
        if sub['element_out'] in lineup:
            lineup[lineup.index(sub['element_out'])] = sub['element_in']
    return lineup

def gw_score(le, gw):
    return sum(pts(pid, gw) for pid in final_xi(le, gw))

# Verify alignment with official H2H scores
OFFICIAL = {}
for m in LD['matches']:
    OFFICIAL[(m['league_entry_1'], m['event'])] = m['league_entry_1_points']
    OFFICIAL[(m['league_entry_2'], m['event'])] = m['league_entry_2_points']
bad = 0
for le in ALL_LE:
    for gw in range(1, 39):
        if gw_score(le, gw) != OFFICIAL[(le, gw)]:
            bad += 1
print(f"Verification: {bad} mismatches across 228 (manager,GW) pairs (must be 0).")
assert bad == 0

# ---------- Cumulative season race ----------
def cumulative_through(gw_max):
    tot = {le: {'W':0,'D':0,'L':0,'PF':0,'PA':0,'pts':0} for le in ALL_LE}
    for m in LD['matches']:
        if m['event'] > gw_max: continue
        a, b = m['league_entry_1'], m['league_entry_2']
        sa, sb = m['league_entry_1_points'], m['league_entry_2_points']
        tot[a]['PF'] += sa; tot[a]['PA'] += sb
        tot[b]['PF'] += sb; tot[b]['PA'] += sa
        if sa > sb:
            tot[a]['W'] += 1; tot[a]['pts'] += 3
            tot[b]['L'] += 1
        elif sa < sb:
            tot[b]['W'] += 1; tot[b]['pts'] += 3
            tot[a]['L'] += 1
        else:
            tot[a]['D'] += 1; tot[a]['pts'] += 1
            tot[b]['D'] += 1; tot[b]['pts'] += 1
    return tot

RANK_BY_GW = {}
POINTS_BY_GW = {}
PF_BY_GW = {}
for gw in range(1, 39):
    t = cumulative_through(gw)
    POINTS_BY_GW[gw] = {le: t[le]['pts'] for le in ALL_LE}
    PF_BY_GW[gw] = {le: t[le]['PF'] for le in ALL_LE}
    ranked = sorted(ALL_LE, key=lambda le: (-t[le]['pts'], -t[le]['PF']))
    RANK_BY_GW[gw] = {le: i+1 for i, le in enumerate(ranked)}

weeks_at_top = Counter()
for gw in range(1, 39):
    for le, r in RANK_BY_GW[gw].items():
        if r == 1:
            weeks_at_top[le] += 1

# Lead changes
lead_history = []
for gw in range(1, 39):
    leader = [le for le, r in RANK_BY_GW[gw].items() if r == 1][0]
    lead_history.append((gw, leader, LE2FN[leader]))

# ---------- H2H specifics ----------
H2H_MARGIN = []
H2H_PAIR = defaultdict(lambda: defaultdict(int))
NEMESIS_LOSSES = defaultdict(lambda: defaultdict(list))
for m in LD['matches']:
    a, b = m['league_entry_1'], m['league_entry_2']
    sa, sb = m['league_entry_1_points'], m['league_entry_2_points']
    if sa > sb:
        H2H_MARGIN.append((sa-sb, m['event'], a, b, sa, sb))
        H2H_PAIR[a][b] += 1
        NEMESIS_LOSSES[b][a].append(m['event'])
    elif sb > sa:
        H2H_MARGIN.append((sb-sa, m['event'], b, a, sb, sa))
        H2H_PAIR[b][a] += 1
        NEMESIS_LOSSES[a][b].append(m['event'])
    else:
        H2H_MARGIN.append((0, m['event'], a, b, sa, sb))
H2H_MARGIN_SORTED = sorted(H2H_MARGIN, key=lambda x: -x[0])
CLOSEST = sorted([m for m in H2H_MARGIN if m[0] > 0], key=lambda x: x[0])

NEMESIS = {}
for le in ALL_LE:
    losses_by_opp = {opp: len(gws) for opp, gws in NEMESIS_LOSSES[le].items()}
    if losses_by_opp:
        opp = max(losses_by_opp, key=losses_by_opp.get)
        NEMESIS[le] = (opp, losses_by_opp[opp], sorted(NEMESIS_LOSSES[le][opp]))

# ---------- Streaks ----------
def streaks(le):
    seq = []
    for gw in range(1, 39):
        m_gw = [m for m in LD['matches'] if m['event']==gw and (m['league_entry_1']==le or m['league_entry_2']==le)][0]
        if m_gw['league_entry_1'] == le:
            mine, theirs = m_gw['league_entry_1_points'], m_gw['league_entry_2_points']
        else:
            mine, theirs = m_gw['league_entry_2_points'], m_gw['league_entry_1_points']
        if mine > theirs: seq.append('W')
        elif mine < theirs: seq.append('L')
        else: seq.append('D')
    return seq

SEQS = {le: streaks(le) for le in ALL_LE}

def longest_run(seq, allowed):
    best = 0; best_end = -1; cur = 0
    for i, x in enumerate(seq):
        if x in allowed:
            cur += 1
            if cur > best: best, best_end = cur, i
        else:
            cur = 0
    if best == 0: return 0, 0, 0
    return best, best_end - best + 2, best_end + 1

# ---------- Transactions (entry field = entry_id 76xxx) ----------
ACCEPTED = [t for t in TX if t.get('result') == 'a']
print(f"Total transactions in file: {len(TX)}, accepted: {len(ACCEPTED)}")

TX_PER_LE = defaultdict(list)
for t in ACCEPTED:
    le = ID2LE.get(t.get('entry'))
    if le is None: continue
    TX_PER_LE[le].append(t)

TX_COUNTS = {le: len(TX_PER_LE[le]) for le in ALL_LE}

TX_PER_LE_GW = defaultdict(lambda: defaultdict(int))
for t in ACCEPTED:
    le = ID2LE.get(t.get('entry'))
    if le is None: continue
    TX_PER_LE_GW[le][t.get('event')] += 1

def longest_dormant(le):
    longest = 0; longest_start=0; longest_end=0
    cur = 0; cur_start = 1
    for gw in range(1, 39):
        if TX_PER_LE_GW[le].get(gw, 0) == 0:
            cur += 1
            if cur > longest:
                longest = cur; longest_start = cur_start; longest_end = gw
        else:
            cur = 0; cur_start = gw + 1
    return longest, longest_start, longest_end

DORMANT = {le: longest_dormant(le) for le in ALL_LE}

# ---------- Player ownership timelines ----------
OWNERSHIP_EVENTS = defaultdict(list)  # pid -> list of (event, le, dir, kind)
# 1) Draft
for pick in DC:
    pid = pick['element']
    if pid is None: continue
    le = ID2LE.get(pick['entry'])
    if le is None: continue
    OWNERSHIP_EVENTS[pid].append((0, le, 'IN', 'draft'))
# 2) Transactions
for t in sorted(ACCEPTED, key=lambda x: (x.get('event', 0), x.get('id', 0))):
    ev = t['event']
    le = ID2LE.get(t.get('entry'))
    if le is None: continue
    if t.get('element_in') is not None:
        OWNERSHIP_EVENTS[t['element_in']].append((ev, le, 'IN', t.get('kind','w')))
    if t.get('element_out') is not None:
        OWNERSHIP_EVENTS[t['element_out']].append((ev, le, 'OUT', t.get('kind','w')))
# 3) Trades
for trade in TRADES:
    if trade.get('state') != 'p': continue
    ev = trade['event']
    le_offered = ID2LE.get(trade['offered_entry'])
    le_received = ID2LE.get(trade['received_entry'])
    if le_offered is None or le_received is None: continue
    # In trade item: element_in goes INTO offered_entry (from received_entry);
    # element_out goes OUT of offered_entry (to received_entry).
    for it in trade.get('tradeitem_set', []):
        pid_in = it['element_in']     # received → offered
        pid_out = it['element_out']   # offered → received
        # pid_in leaves received_entry, arrives at offered_entry
        OWNERSHIP_EVENTS[pid_in].append((ev, le_received, 'OUT', 'trade'))
        OWNERSHIP_EVENTS[pid_in].append((ev, le_offered, 'IN', 'trade'))
        # pid_out leaves offered_entry, arrives at received_entry
        OWNERSHIP_EVENTS[pid_out].append((ev, le_offered, 'OUT', 'trade'))
        OWNERSHIP_EVENTS[pid_out].append((ev, le_received, 'IN', 'trade'))

# Sort events: same GW: OUT before IN (so swap is clean)
for pid in OWNERSHIP_EVENTS:
    OWNERSHIP_EVENTS[pid].sort(key=lambda x: (x[0], 0 if x[2] == 'OUT' else 1))

# Build per-player ownership intervals.
# Convention: a trade/waiver/free-agent IN at GW ev means the NEW owner has
# the player from GW ev onwards (the move took effect before GW ev started).
# An OUT at GW ev means the previous owner held the player through GW ev-1.
# Draft picks (ev=0) become the owner's player from GW 1.
PLAYER_TENURE = defaultdict(list)  # pid -> list of (le, start_gw, end_gw_inclusive)
for pid, events in OWNERSHIP_EVENTS.items():
    cur_owner = None
    cur_start = None
    for (ev, le, dir, kind) in events:
        if dir == 'IN':
            if cur_owner is not None and cur_owner != le:
                # Close prior owner one GW before this IN
                end_gw = max(cur_start, ev - 1)
                PLAYER_TENURE[pid].append((cur_owner, cur_start, end_gw))
            cur_owner = le
            cur_start = max(1, ev)  # draft (ev=0) starts at GW1
        elif dir == 'OUT':
            if cur_owner == le:
                # Previous owner held through ev-1 (the move was processed before GW ev).
                end_gw = max(cur_start, ev - 1)
                PLAYER_TENURE[pid].append((cur_owner, cur_start, end_gw))
                cur_owner = None
                cur_start = None
    if cur_owner is not None:
        PLAYER_TENURE[pid].append((cur_owner, cur_start, 38))

def tenure_points(pid, le):
    total = 0
    for owner, s, e in PLAYER_TENURE.get(pid, []):
        if owner != le: continue
        for gw in range(max(1, s), min(38, e) + 1):
            total += pts(pid, gw)
    return total

# Signings per player
SIGN_COUNT = defaultdict(int)
for pid, events in OWNERSHIP_EVENTS.items():
    for (ev, le, dir, kind) in events:
        if dir == 'IN' and ev > 0 and kind != 'trade':
            SIGN_COUNT[pid] += 1

DISTINCT_SIGNERS = defaultdict(set)
for pid, events in OWNERSHIP_EVENTS.items():
    for (ev, le, dir, kind) in events:
        if dir == 'IN':
            DISTINCT_SIGNERS[pid].add(le)

# Per-manager player signings (count of IN events, draft excluded)
SIGNS_BY_MGR_PLAYER = defaultdict(lambda: defaultdict(int))
for pid, events in OWNERSHIP_EVENTS.items():
    for (ev, le, dir, kind) in events:
        if dir == 'IN' and ev > 0 and kind != 'trade':
            SIGNS_BY_MGR_PLAYER[le][pid] += 1

# ---------- Cliff / Spike ----------
def form_swing(pid, sign_gw):
    before_gws = [g for g in range(max(1, sign_gw - 4), sign_gw)]
    after_gws  = [g for g in range(sign_gw, min(38, sign_gw + 3) + 1)]
    if not before_gws or not after_gws: return None
    b = sum(pts(pid, g) for g in before_gws) / len(before_gws)
    a = sum(pts(pid, g) for g in after_gws) / len(after_gws)
    return a - b, a, b

CLIFFS = []
SPIKES = []
for t in ACCEPTED:
    pid = t.get('element_in')
    if pid is None: continue
    ev = t['event']
    sw = form_swing(pid, ev)
    if not sw: continue
    delta, a, b = sw
    le = ID2LE.get(t.get('entry'))
    if le is None: continue
    if delta <= -4 and b >= 3:
        CLIFFS.append((delta, pid, le, ev, a, b))
    if delta >= 5:
        SPIKES.append((delta, pid, le, ev, a, b))
CLIFFS.sort()
SPIKES.sort(reverse=True)

# ---------- Goalkeeping howler ----------
GK_HOWLER = Counter()
GK_HOWLER_DETAILS = defaultdict(list)
for le in ALL_LE:
    for gw in range(1, 39):
        squad_pids = squad(le, gw)
        gks = [pid for pid in squad_pids if ELEMENTS.get(pid, {}).get('element_type') == 1]
        if len(gks) < 2: continue
        started_gks = [pid for pid in final_xi(le, gw) if pid in gks]
        if not started_gks: continue
        bench_gks = [pid for pid in gks if pid not in started_gks]
        if not bench_gks: continue
        started = started_gks[0]
        for b_gk in bench_gks:
            if pts(b_gk, gw) > pts(started, gw):
                GK_HOWLER[le] += 1
                GK_HOWLER_DETAILS[le].append((gw, started, pts(started, gw), b_gk, pts(b_gk, gw)))
                break

# ---------- Phantom XI ----------
PHANTOMS = []
for le in ALL_LE:
    for gw in range(1, 39):
        xi = final_xi(le, gw)
        zero_mins = [pid for pid in xi if mins(pid, gw) == 0]
        if len(zero_mins) >= 4:
            PHANTOMS.append((len(zero_mins), le, gw, zero_mins))
PHANTOMS.sort(reverse=True)

# ---------- Club concentration ----------
CLUB_CONC = []
for le in ALL_LE:
    for gw in range(1, 39):
        starters = final_xi(le, gw)
        team_count = Counter(ELEMENTS.get(pid, {}).get('team') for pid in starters)
        for team, c in team_count.items():
            if c >= 4:
                CLUB_CONC.append((c, team, le, gw, [pid for pid in starters if ELEMENTS.get(pid,{}).get('team') == team]))
CLUB_CONC.sort(reverse=True)

# ---------- Welcome, and Goodbye ----------
WELCOME_GOODBYE = []
for pid, events in OWNERSHIP_EVENTS.items():
    last_in_gw = None; last_in_le = None
    for (ev, le, dir, kind) in events:
        if dir == 'IN' and ev > 0:
            last_in_gw = ev; last_in_le = le
        elif dir == 'OUT' and last_in_le == le and last_in_gw is not None:
            tenure = ev - last_in_gw
            if 0 <= tenure <= 3:
                started = any(pid in final_xi(le, g) for g in range(last_in_gw, ev + 1))
                if not started:
                    WELCOME_GOODBYE.append((pid, le, last_in_gw, ev))
            last_in_gw = None; last_in_le = None

# ---------- Squad changes per week ----------
SQUAD_CHANGES = defaultdict(dict)
for le in ALL_LE:
    for gw in range(2, 39):
        prev = set(squad(le, gw-1))
        now = set(squad(le, gw))
        SQUAD_CHANGES[le][gw] = len(now - prev)

# ---------- Most-owned & all-six-owned ----------
ALL_SIX_OWNED = []
for pid in PLAYER_TENURE:
    owners = set([t[0] for t in PLAYER_TENURE[pid]])
    if len(owners) >= 6:
        ALL_SIX_OWNED.append(pid)

# ---------- Hot potatoes ----------
HOT_POTATOES = sorted([(len(s), pid) for pid, s in DISTINCT_SIGNERS.items() if len(s) >= 3], reverse=True)

# Repeat signings per manager
REPEATS_BY_MGR = {}
for le in ALL_LE:
    items = sorted([(pid, c) for pid, c in SIGNS_BY_MGR_PLAYER[le].items() if c >= 2], key=lambda x: -x[1])
    REPEATS_BY_MGR[le] = items

# ---------- Trades (tenure-adjusted, points AFTER trade only) ----------
def tenure_pts_from(pid, owner_le, start_gw):
    for o, s, e in PLAYER_TENURE.get(pid, []):
        if o == owner_le and s == start_gw:
            return sum(pts(pid, g) for g in range(max(1, s), min(38, e) + 1))
    # fallback: first interval for this owner at or after start_gw
    for o, s, e in PLAYER_TENURE.get(pid, []):
        if o == owner_le and s >= start_gw:
            return sum(pts(pid, g) for g in range(max(1, s), min(38, e) + 1))
    return 0

TRADE_DETAILS = []
for trade in TRADES:
    if trade.get('state') != 'p': continue
    ev = trade['event']
    le_offered = ID2LE.get(trade['offered_entry'])
    le_received = ID2LE.get(trade['received_entry'])
    # offered_entry GIVES element_out (to received_entry).
    # received_entry GIVES element_in (which goes to offered_entry).
    offered_gave = [it['element_out'] for it in trade['tradeitem_set']]
    received_gave = [it['element_in'] for it in trade['tradeitem_set']]
    # Tenure points the recipient earned with the players they got
    offered_received_pts = sum(tenure_pts_from(pid, le_offered, ev) for pid in received_gave)
    received_received_pts = sum(tenure_pts_from(pid, le_received, ev) for pid in offered_gave)
    TRADE_DETAILS.append({
        'event': ev,
        'le_offered': le_offered, 'le_received': le_received,
        'offered_gave': offered_gave,  # offered_entry's players sent to received
        'received_gave': received_gave,  # received_entry's players sent to offered
        'offered_received_pts': offered_received_pts,
        'received_received_pts': received_received_pts,
    })

# ---------- Best draft pick ----------
DRAFT_RESULTS = []
for pick in DC:
    pid = pick['element']; le = ID2LE.get(pick['entry'])
    if pid is None or le is None: continue
    tp = tenure_points(pid, le)
    DRAFT_RESULTS.append((tp, pick['pick'], le, pid))
DRAFT_RESULTS.sort(reverse=True)

# ---------- Waiver tenure-adjusted ----------
WAIVER_MOVES = []
for t in ACCEPTED:
    pid = t.get('element_in')
    if pid is None: continue
    le = ID2LE.get(t.get('entry')); ev = t['event']
    if le is None: continue
    tp = 0
    for o, s, e in PLAYER_TENURE.get(pid, []):
        if o == le and s == ev:
            tp = sum(pts(pid, g) for g in range(s, min(38, e) + 1))
            break
    WAIVER_MOVES.append((tp, le, pid, ev))
WAIVER_MOVES.sort(reverse=True)

# ---------- High / low per manager ----------
HIGH_LOW = {}
for le in ALL_LE:
    scores = [(gw_score(le, gw), gw) for gw in range(1, 39)]
    HIGH_LOW[le] = (max(scores), min(scores))

# ---------- Best/worst move per manager (tenure-adjusted, any acquisition) ----------
def best_worst_move(le):
    moves = []  # ('source', pid, tenure_pts, label)
    for pick in DC:
        if ID2LE.get(pick['entry']) != le or pick['element'] is None: continue
        pid = pick['element']
        moves.append(('draft', pid, tenure_points(pid, le), f"pick #{pick['index']}"))
    for t in ACCEPTED:
        if ID2LE.get(t.get('entry')) != le: continue
        pid = t.get('element_in')
        if pid is None: continue
        ev = t['event']
        tp = 0
        for o, s, e in PLAYER_TENURE.get(pid, []):
            if o == le and s == ev:
                tp = sum(pts(pid, g) for g in range(s, min(38, e) + 1))
                break
        moves.append(('waiver', pid, tp, f"GW{ev}"))
    for trade in TRADES:
        if trade.get('state') != 'p': continue
        ev = trade['event']
        if ID2LE.get(trade['received_entry']) == le:
            # received_entry GAINS element_out
            for it in trade['tradeitem_set']:
                pid = it['element_out']
                tp = tenure_pts_from(pid, le, ev)
                moves.append(('trade', pid, tp, f"trade GW{ev}"))
        if ID2LE.get(trade['offered_entry']) == le:
            # offered_entry GAINS element_in
            for it in trade['tradeitem_set']:
                pid = it['element_in']
                tp = tenure_pts_from(pid, le, ev)
                moves.append(('trade', pid, tp, f"trade GW{ev}"))
    moves.sort(key=lambda m: -m[2])
    best = moves[0] if moves else None
    # worst: a meaningful acquisition (not just one held for 1 GW). Filter to those held >0
    bad = [m for m in moves if m[2] is not None]
    bad.sort(key=lambda m: m[2])
    return best, bad[0] if bad else None, moves

# ---------- Output ----------
print("Writing season_analysis.md...")
out = []
out.append("# Craig Cup — Season Analysis (computed)\n\n")

out.append("## 1. Final table (raw)\n\n")
out.append("| Pos | Manager | Team | W | D | L | PF | PA | League Pts |\n|-|-|-|-|-|-|-|-|-|\n")
for s in LD['standings']:
    le = s['league_entry']
    out.append(f"| {s['rank']} | {LE2FN[le]} | {LE2TN[le]} | {s['matches_won']} | {s['matches_drawn']} | {s['matches_lost']} | {s['points_for']} | {s['points_against']} | {s['total']} |\n")
out.append("\n")

out.append("## 2. Weeks at #1\n\n")
for le, c in weeks_at_top.most_common():
    out.append(f"- {LE2FN[le]}: {c} weeks\n")
out.append("\n")

out.append("## 3. Leader at end of each GW\n\n")
prev = None
for gw, le, name in lead_history:
    if name != prev:
        out.append(f"- GW{gw}: {name} takes the lead\n")
        prev = name
out.append("\nFull lead sequence: " + " ".join(name[0] for _, _, name in lead_history) + "\n\n")

out.append("## 4. Per-GW scores (verified vs H2H)\n\n")
out.append("| GW | " + " | ".join(LE2FN[le] for le in ALL_LE) + " |\n|-" + ("|-" * len(ALL_LE)) + "|\n")
for gw in range(1, 39):
    out.append(f"| {gw} | " + " | ".join(str(gw_score(le, gw)) for le in ALL_LE) + " |\n")
out.append("\n")

out.append("## 5. Streaks per manager\n\n")
for le in ALL_LE:
    seq = SEQS[le]
    lw, lws, lwe = longest_run(seq, {'W'})
    ll, lls, lle = longest_run(seq, {'L'})
    lu, lus, lue = longest_run(seq, {'W','D'})
    lwl, lwls, lwle = longest_run(seq, {'L','D'})
    out.append(f"### {LE2FN[le]}\n")
    out.append(f"- Sequence: `{''.join(seq)}`\n")
    out.append(f"- Longest W: {lw} (GW{lws}-{lwe})\n")
    out.append(f"- Longest L: {ll} (GW{lls}-{lle})\n")
    out.append(f"- Longest unbeaten: {lu} (GW{lus}-{lue})\n")
    out.append(f"- Longest winless: {lwl} (GW{lwls}-{lwle})\n\n")

out.append("## 6. Biggest H2H margins (top 12)\n\n")
for margin, ev, w, l, ws, ls in H2H_MARGIN_SORTED[:12]:
    out.append(f"- GW{ev}: {LE2FN[w]} {ws}-{ls} {LE2FN[l]} (margin {margin})\n")
out.append("\n## 6b. Closest decisive results (top 10)\n\n")
for margin, ev, w, l, ws, ls in CLOSEST[:10]:
    out.append(f"- GW{ev}: {LE2FN[w]} {ws}-{ls} {LE2FN[l]} (margin {margin})\n")
out.append("\n## 6c. Draws\n\n")
draws = [m for m in H2H_MARGIN if m[0]==0]
for margin, ev, a, b, sa, sb in draws:
    out.append(f"- GW{ev}: {LE2FN[a]} {sa}-{sb} {LE2FN[b]}\n")
out.append(f"\nTotal draws: {len(draws)}\n\n")

out.append("## 7. Nemesis per manager\n\n")
for le in ALL_LE:
    if le in NEMESIS:
        opp, n, gws = NEMESIS[le]
        out.append(f"- {LE2FN[le]}: beaten by {LE2FN[opp]} {n}× — GWs {gws}\n")
out.append("\n")

out.append("## 8. Transactions per manager\n\n")
for le in sorted(ALL_LE, key=lambda x: -TX_COUNTS[x]):
    out.append(f"- {LE2FN[le]}: {TX_COUNTS[le]} accepted\n")
out.append(f"- Total accepted: {sum(TX_COUNTS.values())}\n\n")

out.append("## 9. Longest dormant stretches\n\n")
for le in ALL_LE:
    d, s, e = DORMANT[le]
    out.append(f"- {LE2FN[le]}: {d} GWs (GW{s}-{e})\n")
peter_le = 73822
peter_tx_gws = sorted(set(t['event'] for t in TX_PER_LE[peter_le]))
out.append(f"\nPeter's transaction GWs: {peter_tx_gws}\n")
out.append(f"Peter's last accepted transaction: GW{peter_tx_gws[-1] if peter_tx_gws else 'never'}\n\n")

out.append("## 10. Transactions per GW per manager\n\n")
out.append("| GW | " + " | ".join(LE2FN[le] for le in ALL_LE) + " |\n|-" + "|-" * len(ALL_LE) + "|\n")
for gw in range(1, 39):
    out.append(f"| {gw} | " + " | ".join(str(TX_PER_LE_GW[le].get(gw,0)) for le in ALL_LE) + " |\n")
out.append("\n")

out.append("## 11. Geraint transactions full list\n\n")
ger_tx = sorted([(t['event'], pname(t.get('element_in')), pname(t.get('element_out'))) for t in TX_PER_LE[73835]])
for ev, i, o in ger_tx:
    out.append(f"- GW{ev}: IN {i} / OUT {o}\n")
out.append("\n")

out.append("## 12. Goalkeeping howler counts\n\n")
for le, c in sorted(GK_HOWLER.items(), key=lambda x: -x[1]):
    out.append(f"- {LE2FN[le]}: {c} wrong calls\n")
out.append("\n")
# Detail for top howler manager
top_howler = max(GK_HOWLER, key=GK_HOWLER.get) if GK_HOWLER else None
if top_howler:
    out.append(f"### Detail for {LE2FN[top_howler]}\n")
    for gw, s, sp, b, bp in GK_HOWLER_DETAILS[top_howler]:
        out.append(f"- GW{gw}: started {pname(s)} ({sp}) over {pname(b)} ({bp})\n")
    out.append("\n")

out.append("## 13. Phantom XI candidates (≥4 starters with zero mins)\n\n")
for c, le, gw, pids in PHANTOMS[:20]:
    out.append(f"- {LE2FN[le]} GW{gw}: {c} phantoms — " + ", ".join(pname(p) for p in pids) + "\n")
out.append("\n")

out.append("## 14. Club concentration (≥4 starters from same club)\n\n")
for c, team, le, gw, pids in CLUB_CONC[:30]:
    team_name = TEAMS.get(team, {}).get('name', f'team#{team}')
    out.append(f"- {LE2FN[le]} GW{gw}: {c}× {team_name} — " + ", ".join(pname(p) for p in pids) + "\n")
out.append("\n")

out.append("## 15. Welcome, and Goodbye (signed, never started, dropped within 3 GWs)\n\n")
for pid, le, in_gw, out_gw in WELCOME_GOODBYE:
    out.append(f"- {LE2FN[le]} signed {pname(pid)} GW{in_gw}, dropped GW{out_gw} (held {out_gw-in_gw} GWs)\n")
out.append("\n")

out.append("## 16. Hot potatoes (3+ distinct signers)\n\n")
for n, pid in HOT_POTATOES[:25]:
    timeline = [(ev, LE2FN[le], dir) for (ev, le, dir, k) in OWNERSHIP_EVENTS[pid] if ev > 0]
    out.append(f"- **{pname(pid)}** ({n} distinct managers, {SIGN_COUNT[pid]} signings): " +
               " → ".join(f"GW{tl[0]}{tl[2][0]}({tl[1]})" for tl in timeline) + "\n")
out.append("\n")

out.append("## 17. Most-signed players per manager (≥2)\n\n")
for le in ALL_LE:
    items = REPEATS_BY_MGR[le][:15]
    out.append(f"### {LE2FN[le]}\n")
    for pid, c in items:
        out.append(f"- {pname(pid)} × {c}\n")
    out.append("\n")

out.append("## 18. The Cliff candidates (≥3ppg before, drops ≥4)\n\n")
for delta, pid, le, ev, a, b in CLIFFS[:15]:
    out.append(f"- {LE2FN[le]} signed {pname(pid)} GW{ev}: before {b:.1f} → after {a:.1f} (Δ {delta:+.1f})\n")
out.append("\n## 19. Right place right time (≥+5 swing)\n\n")
for delta, pid, le, ev, a, b in SPIKES[:15]:
    out.append(f"- {LE2FN[le]} signed {pname(pid)} GW{ev}: before {b:.1f} → after {a:.1f} (Δ {delta:+.1f})\n")
out.append("\n")

out.append("## 20. Trades (tenure-adjusted, post-trade points only)\n\n")
for td in TRADE_DETAILS:
    a_le = td['le_offered']; b_le = td['le_received']
    out.append(f"### GW{td['event']}: {LE2FN[a_le]} (offered) ↔ {LE2FN[b_le]} (received)\n")
    out.append(f"- {LE2FN[a_le]} gave: " + ", ".join(pname(p) for p in td['offered_gave']) + "\n")
    out.append(f"- {LE2FN[b_le]} gave: " + ", ".join(pname(p) for p in td['received_gave']) + "\n")
    out.append(f"- {LE2FN[a_le]} received pts (after trade): {td['offered_received_pts']}\n")
    out.append(f"- {LE2FN[b_le]} received pts (after trade): {td['received_received_pts']}\n\n")

out.append("## 21. Top 25 draft picks (tenure-adjusted)\n\n")
for tp, pick_no, le, pid in DRAFT_RESULTS[:25]:
    out.append(f"- Pick #{pick_no}: {pname(pid)} → {LE2FN[le]} ({tp} pts while held)\n")
out.append("\n")

out.append("## 22. Top 20 waiver/FA pickups (tenure-adjusted)\n\n")
for tp, le, pid, ev in WAIVER_MOVES[:20]:
    out.append(f"- {LE2FN[le]} GW{ev} signed {pname(pid)} → {tp} pts while held\n")
out.append("\n")

out.append("## 23. High and low GW per manager\n\n")
for le in ALL_LE:
    (hi, hi_gw), (lo, lo_gw) = HIGH_LOW[le]
    out.append(f"- {LE2FN[le]}: high {hi} (GW{hi_gw}), low {lo} (GW{lo_gw})\n")
out.append("\n")

out.append("## 24. Best & worst move per manager\n\n")
for le in ALL_LE:
    best, worst, _ = best_worst_move(le)
    out.append(f"### {LE2FN[le]}\n")
    if best: out.append(f"- Best: {pname(best[1])} ({best[3]}, via {best[0]}) — {best[2]} pts\n")
    if worst: out.append(f"- Worst: {pname(worst[1])} ({worst[3]}, via {worst[0]}) — {worst[2]} pts\n")
    out.append("\n")

out.append("## 25. Squad changes per GW per manager\n\n")
out.append("| GW | " + " | ".join(LE2FN[le] for le in ALL_LE) + " |\n|-" + "|-" * len(ALL_LE) + "|\n")
for gw in range(2, 39):
    out.append(f"| {gw} | " + " | ".join(str(SQUAD_CHANGES[le].get(gw,0)) for le in ALL_LE) + " |\n")
out.append("\n")

# Aggregate stats
total_tx = sum(TX_COUNTS.values())
total_trades = sum(1 for t in TRADES if t.get('state') == 'a')
all_starters = set()
for le in ALL_LE:
    for gw in range(1, 39):
        for pid in final_xi(le, gw):
            all_starters.add(pid)
all_owned = set(PLAYER_TENURE.keys())
total_pts_for = sum(s['points_for'] for s in LD['standings'])
highest_gw_score = max((gw_score(le, gw), le, gw) for le in ALL_LE for gw in range(1, 39))
lowest_gw_score = min((gw_score(le, gw), le, gw) for le in ALL_LE for gw in range(1, 39))
avg_score = {le: sum(gw_score(le, gw) for gw in range(1,39))/38 for le in ALL_LE}

out.append("## 26. Aggregate stats\n\n")
out.append(f"- Total accepted transactions: {total_tx}\n")
out.append(f"- Total accepted trades: {total_trades}\n")
out.append(f"- Distinct players started across all six managers: {len(all_starters)}\n")
out.append(f"- Distinct players owned at any point: {len(all_owned)}\n")
out.append(f"- Total PL players in dataset: {len(BS['elements'])}\n")
out.append(f"- Total H2H points scored: {total_pts_for}\n")
out.append(f"- Highest single GW: {highest_gw_score[0]} by {LE2FN[highest_gw_score[1]]} in GW{highest_gw_score[2]}\n")
out.append(f"- Lowest single GW: {lowest_gw_score[0]} by {LE2FN[lowest_gw_score[1]]} in GW{lowest_gw_score[2]}\n")
out.append(f"- Avg score per GW per mgr: " + ", ".join(f"{LE2FN[le]} {v:.1f}" for le, v in sorted(avg_score.items(), key=lambda x:-x[1])) + "\n")
n_5 = sum(1 for m in H2H_MARGIN if 0 < m[0] <= 5)
n_10 = sum(1 for m in H2H_MARGIN if 0 < m[0] <= 10)
out.append(f"- H2H decided by ≤5: {n_5}\n")
out.append(f"- H2H decided by ≤10: {n_10}\n")
out.append(f"- H2H drawn: {sum(1 for m in H2H_MARGIN if m[0]==0)}\n")
out.append(f"- Players owned by ALL six managers: {len(ALL_SIX_OWNED)}: {[pname(p) for p in ALL_SIX_OWNED]}\n\n")

# Most-owned by weeks
owned_weeks = Counter()
for pid in PLAYER_TENURE:
    for o, s, e in PLAYER_TENURE[pid]:
        owned_weeks[pid] += min(38, e) - max(1, s) + 1
top_owned = owned_weeks.most_common(20)
out.append("## 27. Most-owned players (owner-weeks)\n\n")
for pid, w in top_owned:
    out.append(f"- {pname(pid)}: {w} owner-weeks\n")
out.append("\n")

# Distinct signers ranking
out.append("## 28. Players signed by most distinct managers\n\n")
ds = sorted([(len(s), pid) for pid, s in DISTINCT_SIGNERS.items()], reverse=True)
for n, pid in ds[:15]:
    out.append(f"- {pname(pid)}: {n} distinct signers, {SIGN_COUNT[pid]} signings\n")
out.append("\n")

# ---------- Counterfactuals ----------
out.append("## 29. Counterfactual — Everyone Plays Pete\n\n")
def cf_everyone_plays_pete():
    pete = 73822
    others = [le for le in ALL_LE if le != pete]
    results = {}
    for m in others:
        w=d=l=0; pf=0; pa=0
        for gw in range(1, 39):
            ms, ps = gw_score(m, gw), gw_score(pete, gw)
            pf += ms; pa += ps
            if ms > ps: w += 1
            elif ms < ps: l += 1
            else: d += 1
        results[m] = {'W':w,'D':d,'L':l,'PF':pf,'PA':pa,'pts': w*3 + d}
    w=d=l=0; pf=0; pa=0
    for gw in range(1, 39):
        ps = gw_score(pete, gw)
        avg = sum(gw_score(o, gw) for o in others) / 5
        pf += ps; pa += avg
        if ps > avg: w += 1
        elif ps < avg: l += 1
        else: d += 1
    results[pete] = {'W':w,'D':d,'L':l,'PF':pf,'PA':round(pa,1),'pts': w*3 + d}
    return results
cf1 = cf_everyone_plays_pete()
ranked = sorted(ALL_LE, key=lambda le: (-cf1[le]['pts'], -cf1[le]['PF']))
out.append("| Pos | Mgr | W | D | L | League Pts | PF |\n|-|-|-|-|-|-|-|\n")
for i, le in enumerate(ranked, 1):
    r = cf1[le]
    out.append(f"| {i} | {LE2FN[le]} | {r['W']} | {r['D']} | {r['L']} | {r['pts']} | {r['PF']:.0f} |\n")
out.append("\n")

out.append("## 30. Counterfactual — Optimal XI every week\n\n")
def best_lineup(le, gw):
    pids = squad(le, gw)
    by_pos = {1: [], 2: [], 3: [], 4: []}
    for p in pids:
        t = ELEMENTS.get(p, {}).get('element_type')
        if t in by_pos: by_pos[t].append(pts(p, gw))
    for k in by_pos: by_pos[k].sort(reverse=True)
    best_total = -1
    formations = [(1,d,m,f) for d in range(3,6) for m in range(2,6) for f in range(1,4) if 1+d+m+f==11]
    for (g, d, mi, fw) in formations:
        if len(by_pos[1]) < g or len(by_pos[2]) < d or len(by_pos[3]) < mi or len(by_pos[4]) < fw:
            continue
        total = sum(by_pos[1][:g]) + sum(by_pos[2][:d]) + sum(by_pos[3][:mi]) + sum(by_pos[4][:fw])
        if total > best_total: best_total = total
    return best_total

opt_scores = {le: {gw: best_lineup(le, gw) for gw in range(1, 39)} for le in ALL_LE}
def cf_with_scores(score_table):
    res = {le: {'W':0,'D':0,'L':0,'PF':0,'PA':0,'pts':0} for le in ALL_LE}
    for m in LD['matches']:
        a, b = m['league_entry_1'], m['league_entry_2']
        sa, sb = score_table[a][m['event']], score_table[b][m['event']]
        res[a]['PF'] += sa; res[a]['PA'] += sb
        res[b]['PF'] += sb; res[b]['PA'] += sa
        if sa > sb: res[a]['W'] += 1; res[a]['pts'] += 3; res[b]['L'] += 1
        elif sa < sb: res[b]['W'] += 1; res[b]['pts'] += 3; res[a]['L'] += 1
        else: res[a]['D']+=1; res[b]['D']+=1; res[a]['pts']+=1; res[b]['pts']+=1
    return res
cf2 = cf_with_scores(opt_scores)
ranked = sorted(ALL_LE, key=lambda le: (-cf2[le]['pts'], -cf2[le]['PF']))
out.append("| Pos | Mgr | W | D | L | League Pts | PF |\n|-|-|-|-|-|-|-|\n")
for i, le in enumerate(ranked, 1):
    r = cf2[le]
    out.append(f"| {i} | {LE2FN[le]} | {r['W']} | {r['D']} | {r['L']} | {r['pts']} | {r['PF']} |\n")
out.append("\n")

out.append("## 31. Counterfactual — Drop your top scorer each week\n\n")
new_scores = {}
for le in ALL_LE:
    new_scores[le] = {}
    for gw in range(1, 39):
        xi = final_xi(le, gw)
        if not xi:
            new_scores[le][gw] = gw_score(le, gw); continue
        xi_scores = sorted([(pts(p, gw), p) for p in xi], reverse=True)
        top_pts = xi_scores[0][0]
        bench_pids = [p for p in squad(le, gw) if p not in xi]
        bench_scores = sorted([(pts(p, gw), p) for p in bench_pids], reverse=True)
        repl = bench_scores[0][0] if bench_scores else 0
        new_scores[le][gw] = gw_score(le, gw) - top_pts + repl
cf3 = cf_with_scores(new_scores)
ranked = sorted(ALL_LE, key=lambda le: (-cf3[le]['pts'], -cf3[le]['PF']))
out.append("| Pos | Mgr | W | D | L | League Pts | PF |\n|-|-|-|-|-|-|-|\n")
for i, le in enumerate(ranked, 1):
    r = cf3[le]
    out.append(f"| {i} | {LE2FN[le]} | {r['W']} | {r['D']} | {r['L']} | {r['pts']} | {r['PF']} |\n")
out.append("\n")

# Story validation
out.append("## 32. Story validation\n\n")
def player_id_by_name(needle):
    needle_l = needle.lower()
    return [(pid, e) for pid, e in ELEMENTS.items() if needle_l in (e.get('web_name','') + ' ' + e.get('first_name','') + ' ' + e.get('second_name','')).lower()]
for needle in ['Lacroix', 'Senesi', 'Dewsbury', 'Mukiele', 'Martinez', 'Gittens', 'Marmoush', 'Grealish', 'Bruno F', 'Fernandes']:
    matches = player_id_by_name(needle)
    for pid, e in matches:
        events_for = OWNERSHIP_EVENTS.get(pid, [])
        if not events_for: continue
        post_draft = [(ev, le, dir, kind) for (ev, le, dir, kind) in events_for if ev > 0]
        if not post_draft: continue
        out.append(f"- **{e.get('web_name')}** ({TEAMS.get(e.get('team'),{}).get('name','?')}, id {pid}): " +
                   " · ".join(f"GW{ev} {dir}({LE2FN.get(le,'?')})" for (ev, le, dir, _) in post_draft) + "\n")
out.append("\n")

# Pete + Geraint detailed tx
out.append("## 33. Pete full transaction history\n\n")
pete_tx = sorted([(t['event'], pname(t.get('element_in')), pname(t.get('element_out'))) for t in TX_PER_LE[73822]])
for ev, i, o in pete_tx:
    out.append(f"- GW{ev}: IN {i} / OUT {o}\n")
out.append("\n")

# Gittens detailed
gittens_id = None
for pid, e in ELEMENTS.items():
    if 'gittens' in e.get('web_name','').lower():
        gittens_id = pid; break
if gittens_id:
    out.append(f"## 34. Gittens (id {gittens_id}) full timeline\n\n")
    out.append(f"- Tenures: {PLAYER_TENURE.get(gittens_id, [])}\n")
    out.append(f"- Per-GW pts: " + ", ".join(f"GW{g}:{pts(gittens_id, g)}" for g in range(1, 39)) + "\n")
    out.append(f"- All events: {OWNERSHIP_EVENTS.get(gittens_id, [])}\n\n")
    for owner_le, s, e in PLAYER_TENURE.get(gittens_id, []):
        total = sum(pts(gittens_id, g) for g in range(max(1, s), min(38, e) + 1))
        out.append(f"  - {LE2FN.get(owner_le,'?')}: GW{s}-{e}, scored {total} pts while held\n")
    out.append("\n")

# The Chase (Mark/Steven/Christopher)
out.append("## 35. The Chase — cumulative league pts (Mark/Steven/Christopher)\n\n")
out.append("| GW | Mark | Steven | Christopher |\n|-|-|-|-|\n")
for gw in range(1, 39):
    out.append(f"| {gw} | {POINTS_BY_GW[gw][73788]} | {POINTS_BY_GW[gw][73827]} | {POINTS_BY_GW[gw][73858]} |\n")
out.append("\n")

# Rank-per-gw matrix
out.append("## 36. Rank per GW per manager\n\n")
out.append("| GW | " + " | ".join(LE2FN[le] for le in ALL_LE) + " |\n|-" + "|-" * len(ALL_LE) + "|\n")
for gw in range(1, 39):
    out.append(f"| {gw} | " + " | ".join(str(RANK_BY_GW[gw][le]) for le in ALL_LE) + " |\n")
out.append("\n")

# Key moments
out.append("## 37. Key Moments candidates\n\n")
out.append(f"- Highest GW: {highest_gw_score[0]} by {LE2FN[highest_gw_score[1]]} in GW{highest_gw_score[2]}\n")
out.append(f"- Lowest GW: {lowest_gw_score[0]} by {LE2FN[lowest_gw_score[1]]} in GW{lowest_gw_score[2]}\n")
m = H2H_MARGIN_SORTED[0]
out.append(f"- Biggest beating: GW{m[1]} {LE2FN[m[2]]} {m[4]}-{m[5]} {LE2FN[m[3]]}\n")
out.append(f"- Peter's last accepted transaction: GW{peter_tx_gws[-1] if peter_tx_gws else '-'}\n")
for t in TRADES:
    if t.get('state') != 'a': continue
    ev = t['event']
    out.append(f"- Trade GW{ev}: {LE2FN.get(ID2LE.get(t['offered_entry']),'?')} ↔ {LE2FN.get(ID2LE.get(t['received_entry']),'?')}\n")
out.append("\n")

# Write season_analysis.md
with open('season_analysis.md', 'w') as f:
    f.write("".join(out))
print("Done. Wrote season_analysis.md")

# ---------- Emit data.js for the deck ----------
def le_to_key(le):
    return {73788:'mark',73822:'peter',73827:'steven',73835:'geraint',73847:'michael',73858:'christopher'}[le]

data = {
  'final_table': [
    {'rank': s['rank'], 'who': le_to_key(s['league_entry']),
     'w': s['matches_won'], 'd': s['matches_drawn'], 'l': s['matches_lost'],
     'pf': s['points_for'], 'pa': s['points_against'], 'pts': s['total']}
    for s in LD['standings']
  ],
  'race_pts': {le_to_key(le): [POINTS_BY_GW[g][le] for g in range(1, 39)] for le in ALL_LE},
  'race_pf':  {le_to_key(le): [PF_BY_GW[g][le] for g in range(1, 39)] for le in ALL_LE},
  'rank_per_gw': {le_to_key(le): [RANK_BY_GW[g][le] for g in range(1, 39)] for le in ALL_LE},
  'gw_scores': {le_to_key(le): [gw_score(le, g) for g in range(1, 39)] for le in ALL_LE},
  'streaks_seq': {le_to_key(le): ''.join(SEQS[le]) for le in ALL_LE},
  'tx_per_gw': {le_to_key(le): [TX_PER_LE_GW[le].get(g, 0) for g in range(1, 39)] for le in ALL_LE},
  'squad_changes_per_gw': {le_to_key(le): [SQUAD_CHANGES[le].get(g, 0) for g in range(2, 39)] for le in ALL_LE},
  'gk_howler': {le_to_key(le): GK_HOWLER.get(le, 0) for le in ALL_LE},
  'tx_total':  {le_to_key(le): TX_COUNTS[le] for le in ALL_LE},
  'dormant':   {le_to_key(le): {'len':d, 'start':s, 'end':e} for le, (d, s, e) in DORMANT.items()},
  'weeks_at_top': {le_to_key(le): weeks_at_top.get(le, 0) for le in ALL_LE},
  'phantom_xi': [{'who': le_to_key(le), 'gw': gw, 'count': c, 'names': [pname(p) for p in pids]} for c, le, gw, pids in PHANTOMS],
  'biggest_beating': {
    'gw': H2H_MARGIN_SORTED[0][1],
    'winner': le_to_key(H2H_MARGIN_SORTED[0][2]),
    'loser':  le_to_key(H2H_MARGIN_SORTED[0][3]),
    'ws': H2H_MARGIN_SORTED[0][4], 'ls': H2H_MARGIN_SORTED[0][5],
    'margin': H2H_MARGIN_SORTED[0][0],
  },
  'coin_flips': [
    {'gw':ev,'winner':le_to_key(w),'loser':le_to_key(l),'ws':ws,'ls':ls,'margin':margin}
    for margin, ev, w, l, ws, ls in CLOSEST if margin == 1
  ],
  'trades': [
    {'gw': td['event'],
     'offered': le_to_key(td['le_offered']), 'received': le_to_key(td['le_received']),
     'offered_gave': [pname(p) for p in td['offered_gave']],
     'received_gave': [pname(p) for p in td['received_gave']],
     'offered_received_pts': td['offered_received_pts'],
     'received_received_pts': td['received_received_pts'],}
    for td in TRADE_DETAILS
  ],
  'champion_haaland': {
    'pick': 1, 'player': 'Haaland', 'who': 'geraint', 'pts': DRAFT_RESULTS[0][0],
  },
  'best_draft_top': [
    {'pick': pick_no, 'player': pname(pid), 'who': le_to_key(le), 'pts': tp}
    for tp, pick_no, le, pid in DRAFT_RESULTS[:6]
  ],
  'highest_gw': {'pts': highest_gw_score[0], 'who': le_to_key(highest_gw_score[1]), 'gw': highest_gw_score[2]},
  'lowest_gw':  {'pts': lowest_gw_score[0],  'who': le_to_key(lowest_gw_score[1]),  'gw': lowest_gw_score[2]},
  'total_tx': sum(TX_COUNTS.values()),
  'total_trades': sum(1 for t in TRADES if t.get('state') == 'p'),
  'total_pf': sum(s['points_for'] for s in LD['standings']),
  'distinct_starters': len(all_starters),
  'distinct_owned': len(all_owned),
  'n_decided_le5': n_5,
  'n_decided_le10': n_10,
  'n_draws': sum(1 for m in H2H_MARGIN if m[0] == 0),
  'hot_potatoes': [
    {'player': pname(pid), 'distinct': len(DISTINCT_SIGNERS[pid]), 'signs': SIGN_COUNT[pid],
     'timeline': [{'gw': ev, 'who': le_to_key(le), 'dir': dir}
                  for (ev, le, dir, k) in OWNERSHIP_EVENTS[pid] if ev > 0]}
    for n, pid in HOT_POTATOES[:6]
  ],
  'most_signed_per_mgr': {
    le_to_key(le): [{'player': pname(pid), 'count': c} for pid, c in REPEATS_BY_MGR[le][:8]]
    for le in ALL_LE
  },
  'nemesis': {le_to_key(le): {'opp': le_to_key(NEMESIS[le][0]), 'n': NEMESIS[le][1], 'gws': NEMESIS[le][2]} for le in ALL_LE if le in NEMESIS},
  'high_low': {le_to_key(le): {'hi': HIGH_LOW[le][0][0], 'hi_gw': HIGH_LOW[le][0][1], 'lo': HIGH_LOW[le][1][0], 'lo_gw': HIGH_LOW[le][1][1]} for le in ALL_LE},
  'cf_pete': {le_to_key(le): {'w':cf1[le]['W'],'d':cf1[le]['D'],'l':cf1[le]['L'],'pts':cf1[le]['pts'],'pf':round(cf1[le]['PF'],0)} for le in ALL_LE},
  'cf_optimal': {le_to_key(le): {'w':cf2[le]['W'],'d':cf2[le]['D'],'l':cf2[le]['L'],'pts':cf2[le]['pts'],'pf':cf2[le]['PF']} for le in ALL_LE},
  'cf_drop_top': {le_to_key(le): {'w':cf3[le]['W'],'d':cf3[le]['D'],'l':cf3[le]['L'],'pts':cf3[le]['pts'],'pf':cf3[le]['PF']} for le in ALL_LE},
  'avg_score': {le_to_key(le): round(avg_score[le], 1) for le in ALL_LE},
  # Story 5 — the cliff (Dewsbury-Hall trajectory)
  'cliff_dewsbury': {
    'player': 'Dewsbury-Hall', 'sign_gw': 16, 'before': 9.8, 'after': 0.2,
    'pts_per_gw': [HIST.get(242,{}).get(g,0) for g in range(1, 39)],
  },
  # Geraint late panic
  'geraint_tx_per_gw': [TX_PER_LE_GW[73835].get(g, 0) for g in range(1, 39)],
  # Michael identity crisis (squad changes per GW from GW2)
  'michael_squad_changes': [SQUAD_CHANGES[73847].get(g, 0) for g in range(2, 39)],
  'michael_gw7_liverpool': 5,
  # Mukiele timeline
  'mukiele_signings': [{'gw': ev, 'who': le_to_key(le)} for (ev, le, dir, k) in OWNERSHIP_EVENTS[694] if dir == 'IN' and ev > 0],
  # Lacroix full
  'lacroix_events': [{'gw': ev, 'who': le_to_key(le), 'dir': dir} for (ev, le, dir, k) in OWNERSHIP_EVENTS[257] if ev > 0],
  # Senesi events
  'senesi_events': [{'gw': ev, 'who': le_to_key(le), 'dir': dir} for (ev, le, dir, k) in OWNERSHIP_EVENTS[72] if ev > 0],
  # The Chase cumulative
  'chase_pts': {
    'mark': [POINTS_BY_GW[g][73788] for g in range(1, 39)],
    'steven': [POINTS_BY_GW[g][73827] for g in range(1, 39)],
    'christopher': [POINTS_BY_GW[g][73858] for g in range(1, 39)],
  },
  # Welcome and goodbye - pick best example
  'wag': [
    {'player': pname(pid), 'who': le_to_key(le), 'in_gw': in_gw, 'out_gw': out_gw}
    for pid, le, in_gw, out_gw in WELCOME_GOODBYE
  ],
  # Best/worst acquisition per manager (tenure-adjusted, all sources)
  'best_worst_per_mgr': {},
}
# Populate best_worst_per_mgr from the computed function
for le in ALL_LE:
    best, worst, _ = best_worst_move(le)
    data['best_worst_per_mgr'][le_to_key(le)] = {
        'best':  {'player': pname(best[1]),  'source': best[0],  'label': best[3],  'pts': best[2]}  if best  else None,
        'worst': {'player': pname(worst[1]), 'source': worst[0], 'label': worst[3], 'pts': worst[2]} if worst else None,
    }

import json as _json
with open('analysis_data.js', 'w') as f:
    f.write("// Auto-generated by analyze.py — do not edit by hand.\n")
    f.write("window.CC = " + _json.dumps(data, ensure_ascii=False, indent=1) + ";\n")
print("Wrote analysis_data.js")

# Quick sanity checks
print("\n--- SANITY CHECKS ---")
print(f"Final standings (totals): {[(s['rank'], LE2FN[s['league_entry']], s['total']) for s in LD['standings']]}")
print(f"Highest GW: {highest_gw_score[0]} by {FN(highest_gw_score[1])} GW{highest_gw_score[2]}")
print(f"Lowest GW: {lowest_gw_score[0]} by {FN(lowest_gw_score[1])} GW{lowest_gw_score[2]}")
print(f"Peter last tx: GW{peter_tx_gws[-1] if peter_tx_gws else 'never'}")
print(f"GK Howler: {dict(GK_HOWLER)}")
print(f"Steven's W streak: {longest_run(SEQS[73827], {'W'})}")
print(f"Steven's L streak: {longest_run(SEQS[73827], {'L'})}")
print(f"Christopher's W streak: {longest_run(SEQS[73858], {'W'})}")
print(f"Michael's L streak: {longest_run(SEQS[73847], {'L'})}")
print(f"Peter's L streak: {longest_run(SEQS[73822], {'L'})}")
print(f"All-six-owned: {[pname(p) for p in ALL_SIX_OWNED]}")
print(f"Total accepted tx: {sum(TX_COUNTS.values())}")
print(f"Trades: {len(TRADE_DETAILS)}")
print(f"Top hot potatoes: {[(n, pname(p)) for n,p in HOT_POTATOES[:6]]}")
print(f"Weeks at #1: {dict(weeks_at_top)}")
