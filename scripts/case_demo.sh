#!/usr/bin/env bash
# scripts/case_demo.sh — end-to-end Anaheim phantom-vehicle demo.

set -euo pipefail

API="${SPECTER_API:-http://localhost:8000}"
PY="${PY:-.venv/bin/python}"

# ANSI escapes via printf so they don't fight with bash interpolation.
B=$(printf '\033[1m'); D=$(printf '\033[2m'); R=$(printf '\033[0m')
CY=$(printf '\033[36m'); YL=$(printf '\033[33m')

hr() { printf '━%.0s' $(seq 1 92); echo; }
section() {
    printf '\n%s%s%s' "$CY$B" "$(hr)" "$R"
    printf '%s%s  %s%s\n' "$CY$B" "" "$1" "$R"
    printf '%s%s%s' "$CY$B" "$(hr)" "$R"
}

if ! curl -sf "$API/healthz" >/dev/null 2>&1; then
    printf '%s⚠  API not reachable at %s. Run "make serve" first.%s\n' "$YL" "$API" "$R"
    exit 1
fi

# ---------- shared Python renderers (passed as -c args) ----------

RENDER_RESULTS='import sys, json
d = json.load(sys.stdin)
B="\033[1m"; D="\033[2m"; R="\033[0m"; GN="\033[32m"; MG="\033[35m"
results = d.get("results") or d.get("hits") or []
if not results:
    print(f"  {D}(no results){R}"); sys.exit(0)
for r in results:
    cite  = r.get("citation") or r.get("id")
    topic = r.get("legal_topic") or "?"
    score = r.get("score") or 0.0
    text  = (r.get("text") or "").strip()
    if len(text) > 220:
        text = text[:220] + "…"
    url = r.get("source_url") or ""
    print()
    print(f"  {B}{cite}{R}    {MG}[topic: {topic}]{R}    score={GN}{score:.2f}{R}")
    print(f"    {text}")
    print(f"    {D}{url}{R}")
'

RENDER_AUTHORITY='import sys, json
d = json.load(sys.stdin)
B="\033[1m"; D="\033[2m"; R="\033[0m"; YL="\033[33m"
ps = d.get("primary_statute") or {}
cl = d.get("case_law") or {}
st = d.get("statistics") or {}
ps_name = ps.get("name") or ""
ps_url  = ps.get("url") or ""
cl_name = cl.get("name") or ""
cl_url  = cl.get("url") or ""
st_name = st.get("name") or ""
st_url  = st.get("url") or ""
print()
print(f"  {B}Primary statute (California):{R}")
print(f"    {ps_name}")
print(f"    {D}{ps_url}{R}")
print()
print(f"  {B}Case law database:{R}")
print(f"    {cl_name}")
print(f"    {D}{cl_url}{R}")
print()
print(f"  {B}Damages / statistics:{R}")
print(f"    {st_name}")
print(f"    {D}{st_url}{R}")
note = d.get("authority_note")
if note:
    print()
    print(f"  {YL}⚠ Authority note:{R}")
    for line in str(note).strip().splitlines():
        print(f"    {D}{line}{R}")
'

RENDER_ROUTES='import sys, json
d = json.load(sys.stdin)
D="\033[2m"; R="\033[0m"
for r in d.get("routes", []):
    for p in r.get("primary", []):
        name = p.get("name") or ""
        url  = p.get("url") or ""
        print(f"    -> {name}  {D}{url}{R}")
'

RENDER_BY_STATE='import sys, json
d = json.load(sys.stdin)
B="\033[1m"; D="\033[2m"; R="\033[0m"
by_state = {}
for r in d.get("results", []):
    by_state.setdefault(r.get("state_code","??"), []).append(r)
for st in ("CA","TX","FL","PA"):
    rs = by_state.get(st, [])
    print()
    print(f"  {B}{st}{R}  ({len(rs)} statutes)")
    for r in rs[:2]:
        cite = r.get("citation") or "?"
        url  = r.get("source_url") or ""
        print(f"    {cite:<32s}")
        print(f"      {D}{url}{R}")
'

# ---------- helpers ----------

# Run a GET search, render with $RENDER_RESULTS.
search() { curl -sf "$1" | "$PY" -c "$RENDER_RESULTS"; }

# POST /ask with given JSON body, render with $RENDER_RESULTS.
ask() {
    curl -sf -X POST "$API/ask" -H 'Content-Type: application/json' -d "$1" \
        | "$PY" -c "$RENDER_RESULTS"
}

# ============================================================================
section "📞  CASE INTAKE"
# ============================================================================

cat <<'EOF'
  ┌──────────────────────────────────────────────────────────────────┐
  │  CLIENT     Single mother, 2 minor children                      │
  │  WHEN       ~11:40 PM, single-vehicle crash                      │
  │  WHERE      I-5 SB, Anaheim, California                          │
  │  WHAT       Lifted pickup tailgated client w/ high beams,        │
  │             passed her, then cut back into her lane forcing an   │
  │             evasive maneuver. She struck the center divider,     │
  │             spun, hit the wall.                                  │
  │  KEY FACT   No physical contact. Other driver fled.              │
  │  EVIDENCE   CHP report (no plate). Dashcam (plate unreadable).   │
  │             Possible Chevron exterior cams ¼ mile back.          │
  │  INJURIES   Concussion. Cervical strain. Distal radius fracture. │
  │             6 weeks off work.                                    │
  │  COVERAGE   UM/UIM. Carrier pre-denying — "phantom vehicle,      │
  │             no contact."                                         │
  └──────────────────────────────────────────────────────────────────┘
EOF

# ============================================================================
section "🧠  HEADLINE QUERY  —  what statutes apply (plain English)"
# ============================================================================

ask '{
  "question": "lifted pickup tailgated my client with high beams on I-5 in Anaheim then passed her and cut back into her lane forcing her to swerve into the center divider, the other driver fled without stopping or making contact, what California vehicle code statutes apply",
  "state": "CA",
  "k": 8
}'

# ============================================================================
section "🚨  HIT-AND-RUN  —  duty to stop / identify after a crash"
# ============================================================================

printf "  %sCarrier's argument: 'no contact = not a phantom vehicle.'%s\n" "$D" "$R"
printf "  %sCounter: even without contact, conduct that CAUSES a crash invokes%s\n" "$D" "$R"
printf "  %sduty-to-stop provisions. Pull every CA hit-and-run-adjacent statute:%s\n" "$D" "$R"
search "$API/search?q=duty+to+stop+after+causing+a+collision+driver+left+the+scene&state=CA&legal_topic=hit+and+run&k=5"

# ============================================================================
section "💨  FOLLOWING TOO CLOSELY  —  the tailgating with high beams"
# ============================================================================

search "$API/search?q=tailgating+aggressive+driving+high+beams+at+night+behind+other+vehicle&state=CA&legal_topic=following+too+closely&k=5"

# ============================================================================
section "↩️   IMPROPER LANE USAGE  —  the swerve-back maneuver"
# ============================================================================

search "$API/search?q=unsafe+lane+change+passing+then+cutting+back+forcing+other+driver+off+road+improper+lane+usage&state=CA&k=6"

# ============================================================================
section "🏁  SPEED-RELATED  —  basic speed law / unsafe for conditions"
# ============================================================================

printf "  %sClient was at posted 65. Other driver presumed faster.%s\n" "$D" "$R"
printf "  %sPull California's basic speed law + 'unsafe for conditions' statutes:%s\n" "$D" "$R"
search "$API/search?q=basic+speed+law+unsafe+speed+for+conditions+exceeding+reasonable+speed&state=CA&legal_topic=speeding&k=5"

# ============================================================================
section "⚡  RECKLESS DRIVING  —  the catch-all wanton-disregard provision"
# ============================================================================

search "$API/search?q=reckless+driving+wilful+wanton+disregard+for+safety+of+persons+or+property&state=CA&legal_topic=reckless+driving&k=4"

# ============================================================================
section "📚  AUTHORITY WIKI  —  where do I do my case-law workup"
# ============================================================================

curl -sf "$API/authority?legal_topic=hit+and+run&state=CA" | "$PY" -c "$RENDER_AUTHORITY"

printf "\n  %sFor ethics / coverage-bad-faith angles on the UM/UIM denial:%s\n" "$D" "$R"
curl -sf "$API/authority?need=ethics&jurisdiction=California" | "$PY" -c "$RENDER_ROUTES"

# ============================================================================
section "🌐  CROSS-JURISDICTION CHECK  —  same conduct in TX / FL / PA"
# ============================================================================

printf "  %sIf the firm has cross-state operations, here's the same legal topic%s\n" "$D" "$R"
printf "  %sacross all 4 jurisdictions in our Harvester:%s\n" "$D" "$R"
curl -sf "$API/search?q=driver+left+the+scene+after+causing+single-vehicle+crash&legal_topic=hit+and+run&k=10" \
    | "$PY" -c "$RENDER_BY_STATE"

# ============================================================================
section "✅  WORKUP COMPLETE"
# ============================================================================

cat <<EOF

  ${D}Specter delivered, in one query session:${R}

    • Statutes for the unidentified driver's conduct across 5 legal theories
        (hit-and-run, following too closely, improper lane usage,
         speed law, reckless driving)
    • Every statute with full text + verifiable source URL
    • Multi-state comparison for cross-jurisdiction operations
    • Authority routing: where to do case-law workup, where to find
        damages framing, and where ethics / bad-faith authority lives

  ${B}Time saved: hours of paralegal Ctrl-F, replaced by one structured query.${R}

EOF
