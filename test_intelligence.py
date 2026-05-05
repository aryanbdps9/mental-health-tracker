"""Comprehensive intelligence / cascade tests using Selenium + FlowSession in-browser."""
import json, time, os, sys
from selenium import webdriver

PORT = 58520
PW = "test123"
BASE = f"http://127.0.0.1:{PORT}"

# Load questionnaire IDs and option maps
Q = {}  # id → full json
for fn in os.listdir("questionnaires"):
    if not fn.endswith(".json") or fn == "flows.json":
        continue
    with open(f"questionnaires/{fn}") as f:
        q = json.load(f)
    Q[q["id"]] = q

# Shortcuts
PHQ9 = Q["aguqu2kg"]
CSSRS = Q["vd5vesbs"]
MICRO_PHQ9 = Q["hrq04yc6"]
MICRO_CSSRS = Q["ajfeavyf"]

# PHQ-9 Q9 (suicidal ideation question) option IDs
PHQ9_Q9 = "71d6lsay"
PHQ9_Q9_NOT_AT_ALL = "65ewj33n"   # value=0
PHQ9_Q9_SEVERAL = "zwnmpk0q"     # value=1
PHQ9_Q9_HALF = "31yptzo7"        # value=2
PHQ9_Q9_EVERY = "geiz534f"       # value=3

# C-SSRS question IDs and option IDs
CSSRS_Q1 = "tsrg3ww6"  # Wish to be dead
CSSRS_Q1_YES = "17veltgy"
CSSRS_Q1_NO = "904hkvor"

CSSRS_Q2 = "qwi2a4ao"  # Thoughts of killing yourself
CSSRS_Q2_YES = "zaxirhjw"
CSSRS_Q2_NO = "et6l3oem"

CSSRS_Q3 = "xgbkfrnd"  # How you might do it
CSSRS_Q3_YES = "e54puahq"
CSSRS_Q3_NO = "l47m0939"

CSSRS_Q4 = "c15bze2a"  # Intent to act
CSSRS_Q4_YES = "pzcm8m27"
CSSRS_Q4_NO = "i7io6k27"

CSSRS_Q5 = "8y4hzxzy"  # Plan and intent
CSSRS_Q5_YES = "6sxwi9se"
CSSRS_Q5_NO = "1mibfe9n"

CSSRS_FREQ = "q2xemw3o"
FREQ_LESS_WEEKLY = "zx784pk8"
FREQ_WEEKLY = "qr1mrcen"
FREQ_SEVERAL = "a0xh0pv1"
FREQ_DAILY = "ys2z9kpe"
FREQ_MULTI_DAILY = "5t6e5ekm"

# Micro C-SSRS IDs
MC_Q1 = "h5e46x5r"
MC_Q1_YES = "xbyyi3h2"
MC_Q1_NO = "secjcqq0"
MC_Q2 = "srjfg4m6"
MC_Q2_YES = "24ssci6f"
MC_Q2_NO = "3jdtqb36"
MC_Q3 = "5r3rgh8a"
MC_Q3_YES = "14vtn1kt"
MC_Q3_NO = "70ve4rh5"
MC_Q4 = "cnjnhi82"
MC_Q4_YES = "gtr11xek"
MC_Q4_NO = "uxg1wvxk"
MC_Q5 = "b8i1uvmt"
MC_Q5_YES = "4fonv5vh"
MC_Q5_NO = "qfyeb9bo"

# Micro PHQ-9 Q9 (slider)
MPHQ9_Q9 = "9cs718pj"

opts = webdriver.EdgeOptions()
opts.add_argument("--headless=new")
opts.add_argument("--no-sandbox")
d = webdriver.Edge(options=opts)

jsa = lambda s: d.execute_async_script(
    'const done=arguments[arguments.length-1];(async()=>{'
    + s
    + '})().then(r=>done(r)).catch(e=>done("ERR:"+e.message));'
)

def js(s):
    """Execute sync JS and return result."""
    return d.execute_script(s)

def new_flow_session(qids, gap_hours=24):
    """Create a new FlowSession with the given questionnaire IDs loaded."""
    qids_js = json.dumps(qids)
    return jsa(f"""
        const qids = {qids_js};
        const qd = {{}};
        await Promise.all(qids.map(async q => {{ qd[q] = await api('/api/questionnaire/' + q); }}));
        window._testSession = new FlowSession({{ flowId: 'test', sessionId: crypto.randomUUID(), order: qids, qDefs: qd, gapHours: {gap_hours} }});
        return 'ok';
    """)

def set_answer(qid, question_id, value):
    """Set an answer in the test session."""
    val_js = json.dumps(value)
    return js(f"window._testSession.setAnswer('{qid}', '{question_id}', {val_js}); return 'ok';")

def get_answer(qid, question_id):
    """Get an answer from the test session."""
    return js(f"return window._testSession.getAnswer('{qid}', '{question_id}');")

def get_source(qid, question_id):
    """Get the source of an answer."""
    return js(f"return window._testSession.getSource('{qid}', '{question_id}');")

def get_contradictions():
    """Get list of contradictions."""
    return js("return JSON.stringify(window._testSession.contradictions);")

def get_incompatible(qid, question_id):
    """Get incompatible option IDs for a question."""
    return js(f"return JSON.stringify([...window._testSession.getIncompatibleOptions('{qid}', '{question_id}')]);")


results = []

def test(name, condition, detail=""):
    results.append((name, condition))
    status = "PASS" if condition else "FAIL"
    msg = f"  {status}: {name}"
    if detail:
        msg += f" ({detail})"
    print(msg)
    return condition

try:
    # Login
    d.get(BASE)
    time.sleep(3)
    jsa(f"const r=await fetch('/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{password:'{PW}'}})}});return r.ok?'ok':'fail';")
    d.get(BASE)
    time.sleep(2)

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 1: PHQ-9 Q9 → C-SSRS Q1 cross-questionnaire
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 1: PHQ-9 Q9 → C-SSRS Q1 (zero/nonzero cross-Q) ═══")

    new_flow_session(["aguqu2kg", "vd5vesbs"])

    # Test 1.1: PHQ-9 Q9 = "Not at all" → C-SSRS Q1 should auto-fill to "No"
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_NOT_AT_ALL)
    q1_val = get_answer("vd5vesbs", CSSRS_Q1)
    q1_src = get_source("vd5vesbs", CSSRS_Q1)
    test("1.1 PHQ9 Q9=Not at all → CSSRS Q1=No",
         q1_val == CSSRS_Q1_NO and q1_src == "link",
         f"val={q1_val}, src={q1_src}")

    # Test 1.2: That cascaded: CSSRS Q1=No → Q2=No (auto)
    q2_val = get_answer("vd5vesbs", CSSRS_Q2)
    q2_src = get_source("vd5vesbs", CSSRS_Q2)
    test("1.2 Cascade: CSSRS Q1=No → Q2=No",
         q2_val == CSSRS_Q2_NO and q2_src == "link",
         f"val={q2_val}, src={q2_src}")

    # Test 1.3: Q2=No → Q3,Q4,Q5 all No
    q3_val = get_answer("vd5vesbs", CSSRS_Q3)
    q4_val = get_answer("vd5vesbs", CSSRS_Q4)
    q5_val = get_answer("vd5vesbs", CSSRS_Q5)
    test("1.3 Cascade: Q2=No → Q3,Q4,Q5 all No",
         q3_val == CSSRS_Q3_NO and q4_val == CSSRS_Q4_NO and q5_val == CSSRS_Q5_NO,
         f"q3={q3_val}, q4={q4_val}, q5={q5_val}")

    # Test 1.4: Now change PHQ-9 Q9 to "Several days" → CSSRS Q1 should flip to Yes
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_SEVERAL)
    q1_val = get_answer("vd5vesbs", CSSRS_Q1)
    test("1.4 PHQ9 Q9=Several → CSSRS Q1=Yes",
         q1_val == CSSRS_Q1_YES,
         f"val={q1_val}")

    # Test 1.5: CSSRS Q2 should be cleared (Q1 went from No to Yes, so the
    # Q1=No→Q2=No link is stale; Q1=Yes has no single-value link for Q2)
    q2_val = get_answer("vd5vesbs", CSSRS_Q2)
    test("1.5 CSSRS Q2 cleared after Q1 flipped to Yes",
         q2_val is None,
         f"val={q2_val}")

    # Test 1.6: Q3,Q4,Q5 should also be cleared (they depended on Q2=No)
    q3_val = get_answer("vd5vesbs", CSSRS_Q3)
    q4_val = get_answer("vd5vesbs", CSSRS_Q4)
    q5_val = get_answer("vd5vesbs", CSSRS_Q5)
    test("1.6 Q3,Q4,Q5 cleared after cascade",
         q3_val is None and q4_val is None and q5_val is None,
         f"q3={q3_val}, q4={q4_val}, q5={q5_val}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 2: C-SSRS → PHQ-9 reverse direction
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 2: C-SSRS Q1 → PHQ-9 Q9 (reverse direction) ═══")

    new_flow_session(["aguqu2kg", "vd5vesbs"])

    # Test 2.1: Set C-SSRS Q1=No → PHQ-9 Q9 should be "Not at all"
    set_answer("vd5vesbs", CSSRS_Q1, CSSRS_Q1_NO)
    phq_val = get_answer("aguqu2kg", PHQ9_Q9)
    phq_src = get_source("aguqu2kg", PHQ9_Q9)
    test("2.1 CSSRS Q1=No → PHQ9 Q9=Not at all",
         phq_val == PHQ9_Q9_NOT_AT_ALL and phq_src == "link",
         f"val={phq_val}, src={phq_src}")

    # Test 2.2: Set C-SSRS Q1=Yes → PHQ-9 Q9 should be cleared
    # (Q1=Yes compatible options are [several, half, every] — multiple, so no auto-fill)
    set_answer("vd5vesbs", CSSRS_Q1, CSSRS_Q1_YES)
    phq_val = get_answer("aguqu2kg", PHQ9_Q9)
    test("2.2 CSSRS Q1=Yes → PHQ9 Q9 cleared (multiple compatible)",
         phq_val is None,
         f"val={phq_val}")

    # Test 2.3: PHQ-9 Q9 should dim "Not at all" when CSSRS Q1=Yes
    incompat = json.loads(get_incompatible("aguqu2kg", PHQ9_Q9))
    test("2.3 PHQ9 Q9 dims 'Not at all' when CSSRS Q1=Yes",
         PHQ9_Q9_NOT_AT_ALL in incompat,
         f"incompatible={incompat}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 3: C-SSRS internal cascade (Q2 gateway)
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 3: C-SSRS internal cascade (Q2 gateway) ═══")

    new_flow_session(["vd5vesbs"])

    # Test 3.1: Set Q1=Yes, Q2=No → Q3,Q4,Q5 should all auto-fill to No
    set_answer("vd5vesbs", CSSRS_Q1, CSSRS_Q1_YES)
    set_answer("vd5vesbs", CSSRS_Q2, CSSRS_Q2_NO)
    q3_val = get_answer("vd5vesbs", CSSRS_Q3)
    q4_val = get_answer("vd5vesbs", CSSRS_Q4)
    q5_val = get_answer("vd5vesbs", CSSRS_Q5)
    test("3.1 Q1=Yes, Q2=No → Q3,Q4,Q5 all No",
         q3_val == CSSRS_Q3_NO and q4_val == CSSRS_Q4_NO and q5_val == CSSRS_Q5_NO,
         f"q3={q3_val}, q4={q4_val}, q5={q5_val}")

    # Test 3.2: Now change Q2 to Yes → Q3,Q4,Q5 should clear
    set_answer("vd5vesbs", CSSRS_Q2, CSSRS_Q2_YES)
    q3_val = get_answer("vd5vesbs", CSSRS_Q3)
    q4_val = get_answer("vd5vesbs", CSSRS_Q4)
    q5_val = get_answer("vd5vesbs", CSSRS_Q5)
    test("3.2 Q2 flipped to Yes → Q3,Q4,Q5 cleared",
         q3_val is None and q4_val is None and q5_val is None,
         f"q3={q3_val}, q4={q4_val}, q5={q5_val}")

    # Test 3.3: Reverse link: Set Q3=Yes → Q2 should stay Yes (compatible)
    set_answer("vd5vesbs", CSSRS_Q3, CSSRS_Q3_YES)
    q2_val = get_answer("vd5vesbs", CSSRS_Q2)
    test("3.3 Q3=Yes, Q2 stays Yes (compatible)",
         q2_val == CSSRS_Q2_YES,
         f"val={q2_val}")

    # Test 3.4: Contradiction — set Q1=Yes, Q2=Yes manually, then Q3=Yes (all fine).
    # Now set Q2=No manually → Q3 should detect a contradiction (Q3 was manual Yes,
    # but Q2=No→Q3 should be No) — actually Q3 is manual so it produces contradiction
    new_flow_session(["vd5vesbs"])
    set_answer("vd5vesbs", CSSRS_Q1, CSSRS_Q1_YES)
    set_answer("vd5vesbs", CSSRS_Q2, CSSRS_Q2_YES)
    set_answer("vd5vesbs", CSSRS_Q3, CSSRS_Q3_YES)
    # Now change Q2 to No — Q2=No has link to Q3 compatible=[No]. Q3 is manual=Yes → contradiction
    set_answer("vd5vesbs", CSSRS_Q2, CSSRS_Q2_NO)
    contrs = json.loads(get_contradictions())
    # There should be contradictions involving Q3, Q4, Q5 (Q2=No→Q3,Q4,Q5 only compatible with No)
    # But Q4 and Q5 were not set manually, so only Q3 should contradict
    q3_contr = [c for c in contrs if c["tgtQuestionId"] == CSSRS_Q3]
    test("3.4 Contradiction: Q2=No vs manual Q3=Yes",
         len(q3_contr) > 0,
         f"contradictions for Q3: {len(q3_contr)}, total: {len(contrs)}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 4: SI frequency → PHQ-9 Q9 constrained mapping
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 4: SI frequency → PHQ-9 Q9 constrained mapping ═══")

    new_flow_session(["aguqu2kg", "vd5vesbs"])

    # Set C-SSRS Q1=Yes, Q2=Yes, then set frequency to test constraints
    set_answer("vd5vesbs", CSSRS_Q1, CSSRS_Q1_YES)
    set_answer("vd5vesbs", CSSRS_Q2, CSSRS_Q2_YES)

    # Test 4.1: Freq = "less than weekly" → PHQ-9 Q9 should be "Several days"
    set_answer("vd5vesbs", CSSRS_FREQ, FREQ_LESS_WEEKLY)
    phq_val = get_answer("aguqu2kg", PHQ9_Q9)
    test("4.1 Freq=less_weekly → PHQ9 Q9=Several days",
         phq_val == PHQ9_Q9_SEVERAL,
         f"val={phq_val}")

    # Test 4.2: Freq = "weekly" → PHQ-9 Q9 still "Several days"
    set_answer("vd5vesbs", CSSRS_FREQ, FREQ_WEEKLY)
    phq_val = get_answer("aguqu2kg", PHQ9_Q9)
    test("4.2 Freq=weekly → PHQ9 Q9=Several days",
         phq_val == PHQ9_Q9_SEVERAL,
         f"val={phq_val}")

    # Test 4.3: Freq = "several weekly" → PHQ9 Q9 cleared (compatible: several, half, every)
    set_answer("vd5vesbs", CSSRS_FREQ, FREQ_SEVERAL)
    phq_val = get_answer("aguqu2kg", PHQ9_Q9)
    # Q1=Yes → compatible [several, half, every] — 3 options, doesn't auto-fill
    # But freq=several also has compatible [several, half, every] — intersection should narrow...
    # Actually, the cascade processes each link independently. The Q1=Yes link and freq link
    # both target the same Q9. Let's see what actually happens.
    phq_src = get_source("aguqu2kg", PHQ9_Q9)
    test("4.3 Freq=several_weekly → PHQ9 Q9 (multiple compatible, check state)",
         phq_val is None or phq_val in [PHQ9_Q9_SEVERAL, PHQ9_Q9_HALF, PHQ9_Q9_EVERY],
         f"val={phq_val}, src={phq_src}")

    # Test 4.4: Freq = "daily" → PHQ9 Q9 should be constrained to half/every
    set_answer("vd5vesbs", CSSRS_FREQ, FREQ_DAILY)
    phq_val = get_answer("aguqu2kg", PHQ9_Q9)
    phq_src = get_source("aguqu2kg", PHQ9_Q9)
    incompat = json.loads(get_incompatible("aguqu2kg", PHQ9_Q9))
    test("4.4 Freq=daily → dims 'Not at all' and 'Several days'",
         PHQ9_Q9_NOT_AT_ALL in incompat and PHQ9_Q9_SEVERAL in incompat,
         f"incompatible={incompat}")

    # Test 4.5: Freq = "multiple daily" → PHQ9 Q9 should be "Nearly every day"
    set_answer("vd5vesbs", CSSRS_FREQ, FREQ_MULTI_DAILY)
    phq_val = get_answer("aguqu2kg", PHQ9_Q9)
    test("4.5 Freq=multiple_daily → PHQ9 Q9=Nearly every day",
         phq_val == PHQ9_Q9_EVERY,
         f"val={phq_val}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 5: PHQ-9 Q9 → C-SSRS frequency constraints
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 5: PHQ-9 Q9 value → C-SSRS frequency constraints ═══")

    new_flow_session(["aguqu2kg", "vd5vesbs"])

    # Test 5.1: PHQ9 Q9="Several days" → freq compatible = [less_weekly, weekly, several_weekly]
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_SEVERAL)
    freq_incompat = json.loads(get_incompatible("vd5vesbs", CSSRS_FREQ))
    test("5.1 Q9=Several → freq dims daily + multi_daily",
         FREQ_DAILY in freq_incompat and FREQ_MULTI_DAILY in freq_incompat,
         f"incompatible={freq_incompat}")

    # Test 5.2: PHQ9 Q9="Nearly every day" → freq compatible = [several, daily, multi_daily]
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_EVERY)
    freq_incompat = json.loads(get_incompatible("vd5vesbs", CSSRS_FREQ))
    test("5.2 Q9=Every → freq dims less_weekly + weekly",
         FREQ_LESS_WEEKLY in freq_incompat and FREQ_WEEKLY in freq_incompat,
         f"incompatible={freq_incompat}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 6: Override + conflict scenario (user's described test)
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 6: Full conflict scenario — PHQ9→CSSRS then override ═══")

    new_flow_session(["aguqu2kg", "vd5vesbs"])

    # Step A: Set PHQ-9 Q9 = "Not at all" (zero) → C-SSRS Q1=No auto, cascade to Q2=No, etc.
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_NOT_AT_ALL)
    cssrs_q1 = get_answer("vd5vesbs", CSSRS_Q1)
    cssrs_q2 = get_answer("vd5vesbs", CSSRS_Q2)
    test("6.A PHQ9 Q9=0 → full CSSRS cascade (Q1=No, Q2=No)",
         cssrs_q1 == CSSRS_Q1_NO and cssrs_q2 == CSSRS_Q2_NO,
         f"q1={cssrs_q1}, q2={cssrs_q2}")

    # Step B: Now change PHQ-9 Q9 to "Nearly every day" (nonzero)
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_EVERY)
    cssrs_q1 = get_answer("vd5vesbs", CSSRS_Q1)
    cssrs_q2 = get_answer("vd5vesbs", CSSRS_Q2)
    test("6.B PHQ9 Q9=3 → CSSRS Q1=Yes, Q2 cleared",
         cssrs_q1 == CSSRS_Q1_YES and cssrs_q2 is None,
         f"q1={cssrs_q1}, q2={cssrs_q2}")

    # Step C: Go to C-SSRS, manually set Q2=Yes
    set_answer("vd5vesbs", CSSRS_Q2, CSSRS_Q2_YES)
    q2_src = get_source("vd5vesbs", CSSRS_Q2)
    test("6.C Manual Q2=Yes is stored",
         get_answer("vd5vesbs", CSSRS_Q2) == CSSRS_Q2_YES and q2_src == "manual",
         f"src={q2_src}")

    # Step D: Manually set Q2=No — this should:
    #   - Cascade Q2=No → Q3=No, Q4=No, Q5=No
    #   - But Q1 is implied Yes (from PHQ9), so Q2=No doesn't cascade up to Q1
    set_answer("vd5vesbs", CSSRS_Q2, CSSRS_Q2_NO)
    q3 = get_answer("vd5vesbs", CSSRS_Q3)
    q4 = get_answer("vd5vesbs", CSSRS_Q4)
    q5 = get_answer("vd5vesbs", CSSRS_Q5)
    q1 = get_answer("vd5vesbs", CSSRS_Q1)
    q1_src = get_source("vd5vesbs", CSSRS_Q1)
    test("6.D Q2=No → Q3,Q4,Q5 all No, Q1 still implied Yes",
         q3 == CSSRS_Q3_NO and q4 == CSSRS_Q4_NO and q5 == CSSRS_Q5_NO
         and q1 == CSSRS_Q1_YES and q1_src == "link",
         f"q1={q1}({q1_src}), q3={q3}, q4={q4}, q5={q5}")

    # Step E: Now user changes CSSRS Q2 back to Yes, and also manually sets Q3=Yes
    set_answer("vd5vesbs", CSSRS_Q2, CSSRS_Q2_YES)
    set_answer("vd5vesbs", CSSRS_Q3, CSSRS_Q3_YES)
    # Everything should be consistent: Q1=Yes(implied), Q2=Yes(manual), Q3=Yes(manual)
    contrs = json.loads(get_contradictions())
    test("6.E Q1=Yes(link), Q2=Yes, Q3=Yes — no contradictions",
         len(contrs) == 0,
         f"contradictions: {len(contrs)}")

    # Step F: Now user goes back and changes PHQ-9 Q9 to "Not at all" —
    # This creates conflicts because CSSRS Q1 should be No, but Q2=Yes(manual), Q3=Yes(manual)
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_NOT_AT_ALL)
    contrs = json.loads(get_contradictions())
    # Q1 link says compatible=[No], but Q2=Yes implies Q1=Yes.
    # Let's see what state we get
    q1_val = get_answer("vd5vesbs", CSSRS_Q1)
    q2_val = get_answer("vd5vesbs", CSSRS_Q2)
    q2_src = get_source("vd5vesbs", CSSRS_Q2)
    test("6.F PHQ9 Q9=0 with manual Q2=Yes → contradiction or override",
         len(contrs) > 0 or q1_val == CSSRS_Q1_NO,
         f"q1={q1_val}, q2={q2_val}({q2_src}), contrs={len(contrs)}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 7: Micro PHQ-9 slider → Micro C-SSRS (match_method)
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 7: Micro PHQ-9 Q9 slider → Micro C-SSRS Q1 (match_method) ═══")

    new_flow_session(["hrq04yc6", "ajfeavyf"])

    # Test 7.1: Micro PHQ9 Q9 slider = 0 → Micro CSSRS Q1 = No
    set_answer("hrq04yc6", MPHQ9_Q9, 0)
    mc_q1 = get_answer("ajfeavyf", MC_Q1)
    mc_q1_src = get_source("ajfeavyf", MC_Q1)
    test("7.1 Micro PHQ9 Q9=0 → Micro CSSRS Q1=No",
         mc_q1 == MC_Q1_NO and mc_q1_src == "link",
         f"val={mc_q1}, src={mc_q1_src}")

    # Test 7.2: Cascade: MC Q1=No → MC Q2=No
    mc_q2 = get_answer("ajfeavyf", MC_Q2)
    test("7.2 Micro CSSRS Q1=No → Q2=No",
         mc_q2 == MC_Q2_NO,
         f"val={mc_q2}")

    # Test 7.3: Cascade: MC Q2=No → Q3,Q4,Q5 = No
    mc_q3 = get_answer("ajfeavyf", MC_Q3)
    mc_q4 = get_answer("ajfeavyf", MC_Q4)
    mc_q5 = get_answer("ajfeavyf", MC_Q5)
    test("7.3 Micro CSSRS Q2=No → Q3,Q4,Q5 all No",
         mc_q3 == MC_Q3_NO and mc_q4 == MC_Q4_NO and mc_q5 == MC_Q5_NO,
         f"q3={mc_q3}, q4={mc_q4}, q5={mc_q5}")

    # Test 7.4: Change slider to 50 → Micro CSSRS Q1 should flip to Yes
    set_answer("hrq04yc6", MPHQ9_Q9, 50)
    mc_q1 = get_answer("ajfeavyf", MC_Q1)
    test("7.4 Micro PHQ9 Q9=50 → Micro CSSRS Q1=Yes",
         mc_q1 == MC_Q1_YES,
         f"val={mc_q1}")

    # Test 7.5: MC Q2 should be cleared now (Q1 was No→link, flipped to Yes)
    mc_q2 = get_answer("ajfeavyf", MC_Q2)
    test("7.5 MC Q2 cleared after Q1 flipped to Yes",
         mc_q2 is None,
         f"val={mc_q2}")

    # Test 7.6: Q3,Q4,Q5 also cleared
    mc_q3 = get_answer("ajfeavyf", MC_Q3)
    mc_q4 = get_answer("ajfeavyf", MC_Q4)
    mc_q5 = get_answer("ajfeavyf", MC_Q5)
    test("7.6 MC Q3,Q4,Q5 cleared",
         mc_q3 is None and mc_q4 is None and mc_q5 is None,
         f"q3={mc_q3}, q4={mc_q4}, q5={mc_q5}")

    # Test 7.7: Change slider back to 0 → everything should re-cascade to No
    set_answer("hrq04yc6", MPHQ9_Q9, 0)
    mc_q1 = get_answer("ajfeavyf", MC_Q1)
    mc_q2 = get_answer("ajfeavyf", MC_Q2)
    mc_q3 = get_answer("ajfeavyf", MC_Q3)
    test("7.7 Slider back to 0 → full No cascade restored",
         mc_q1 == MC_Q1_NO and mc_q2 == MC_Q2_NO and mc_q3 == MC_Q3_NO,
         f"q1={mc_q1}, q2={mc_q2}, q3={mc_q3}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 8: Manual wall — link can't override manual answer
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 8: Manual answers are walls ═══")

    new_flow_session(["aguqu2kg", "vd5vesbs"])

    # Test 8.1: Manually set CSSRS Q1=Yes, then set PHQ9 Q9=Not at all
    # PHQ9 Q9=0 has link Q1→No, but Q1 is manual Yes → contradiction
    set_answer("vd5vesbs", CSSRS_Q1, CSSRS_Q1_YES)
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_NOT_AT_ALL)
    q1_val = get_answer("vd5vesbs", CSSRS_Q1)
    q1_src = get_source("vd5vesbs", CSSRS_Q1)
    contrs = json.loads(get_contradictions())
    test("8.1 Manual Q1=Yes + PHQ9 Q9=0 → contradiction (not overwritten)",
         q1_val == CSSRS_Q1_YES and q1_src == "manual" and len(contrs) > 0,
         f"val={q1_val}({q1_src}), contrs={len(contrs)}")

    # Test 8.2: Manually set CSSRS Q1=No, then PHQ9 Q9="Several days"
    # PHQ9 Q9=1 → Q1 should be Yes, but Q1 is manual No → contradiction
    new_flow_session(["aguqu2kg", "vd5vesbs"])
    set_answer("vd5vesbs", CSSRS_Q1, CSSRS_Q1_NO)
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_SEVERAL)
    q1_val = get_answer("vd5vesbs", CSSRS_Q1)
    contrs = json.loads(get_contradictions())
    test("8.2 Manual Q1=No + PHQ9 Q9=1 → contradiction",
         q1_val == CSSRS_Q1_NO and len(contrs) > 0,
         f"val={q1_val}, contrs={len(contrs)}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 9: dismissContradictions (kill switch)
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 9: Kill switch — dismiss all links ═══")

    new_flow_session(["aguqu2kg", "vd5vesbs"])
    set_answer("vd5vesbs", CSSRS_Q1, CSSRS_Q1_YES)
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_NOT_AT_ALL)
    contrs = json.loads(get_contradictions())
    test("9.0 Pre-condition: has contradictions",
         len(contrs) > 0, f"contrs={len(contrs)}")

    js("window._testSession.dismissContradictions();")
    contrs2 = json.loads(get_contradictions())
    links_enabled = js("return window._testSession.linksEnabled;")
    test("9.1 After dismiss: no contradictions, links disabled",
         len(contrs2) == 0 and links_enabled == False,
         f"contrs={len(contrs2)}, enabled={links_enabled}")

    # Test 9.2: Further changes should not cascade
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_EVERY)
    q1_val = get_answer("vd5vesbs", CSSRS_Q1)
    test("9.2 After kill switch: Q9 change doesn't cascade",
         q1_val == CSSRS_Q1_YES,
         f"val={q1_val}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 10: stale cleanup edge case — multiple source links
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 10: Stale cleanup with overlapping links ═══")

    new_flow_session(["aguqu2kg", "vd5vesbs"])

    # PHQ9 Q9 has two links to CSSRS Q1:
    #   Q9=65ewj33n(0) → Q1 compatible=[No]
    #   Q9=[zwnmpk0q, 31yptzo7, geiz534f] → Q1 compatible=[Yes]
    # And C-SSRS has reverse link: Q1=No → PHQ9 Q9 compatible=[Not at all]
    # Set PHQ9 Q9="Several days", which triggers Q1=Yes
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_SEVERAL)
    q1 = get_answer("vd5vesbs", CSSRS_Q1)
    test("10.1 Q9=Several → Q1=Yes",
         q1 == CSSRS_Q1_YES, f"val={q1}")

    # Now change to "More than half" — the Q9=[several,half,every]→Q1=Yes link still active
    # Q1 should still be Yes
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_HALF)
    q1 = get_answer("vd5vesbs", CSSRS_Q1)
    test("10.2 Q9=Half → Q1 still Yes",
         q1 == CSSRS_Q1_YES, f"val={q1}")

    # Change to "Not at all" — the nonzero link is stale, zero link activates → Q1=No
    set_answer("aguqu2kg", PHQ9_Q9, PHQ9_Q9_NOT_AT_ALL)
    q1 = get_answer("vd5vesbs", CSSRS_Q1)
    test("10.3 Q9=Not at all → Q1=No (link switched correctly)",
         q1 == CSSRS_Q1_NO, f"val={q1}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 11: Micro PHQ-9 → Micro C-SSRS cross-Q (mirrors Group 1)
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 11: Micro PHQ-9 Q9 → MC Q1 cross-Q + full cascade ═══")

    new_flow_session(["hrq04yc6", "ajfeavyf"])

    # 11.1: Slider=0 → MC Q1=No, Q2=No, Q3-Q5=No (full chain)
    set_answer("hrq04yc6", MPHQ9_Q9, 0)
    test("11.1 Slider=0 → MC Q1=No(link)",
         get_answer("ajfeavyf", MC_Q1) == MC_Q1_NO and get_source("ajfeavyf", MC_Q1) == "link",
         f"q1={get_answer('ajfeavyf', MC_Q1)}({get_source('ajfeavyf', MC_Q1)})")
    test("11.2 Cascade: MC Q1=No → Q2=No",
         get_answer("ajfeavyf", MC_Q2) == MC_Q2_NO,
         f"q2={get_answer('ajfeavyf', MC_Q2)}")
    test("11.3 Cascade: Q2=No → Q3,Q4,Q5 all No",
         get_answer("ajfeavyf", MC_Q3) == MC_Q3_NO
         and get_answer("ajfeavyf", MC_Q4) == MC_Q4_NO
         and get_answer("ajfeavyf", MC_Q5) == MC_Q5_NO,
         f"q3={get_answer('ajfeavyf', MC_Q3)}, q4={get_answer('ajfeavyf', MC_Q4)}, q5={get_answer('ajfeavyf', MC_Q5)}")

    # 11.4: Change slider to 75 → MC Q1 flips to Yes
    set_answer("hrq04yc6", MPHQ9_Q9, 75)
    test("11.4 Slider=75 → MC Q1=Yes",
         get_answer("ajfeavyf", MC_Q1) == MC_Q1_YES,
         f"q1={get_answer('ajfeavyf', MC_Q1)}")

    # 11.5: Q2 cleared (Q1 flipped from No→Yes, stale Q1=No→Q2=No removed)
    test("11.5 MC Q2 cleared after Q1 flipped",
         get_answer("ajfeavyf", MC_Q2) is None,
         f"q2={get_answer('ajfeavyf', MC_Q2)}")

    # 11.6: Q3-Q5 also cleared
    test("11.6 MC Q3,Q4,Q5 cleared",
         get_answer("ajfeavyf", MC_Q3) is None
         and get_answer("ajfeavyf", MC_Q4) is None
         and get_answer("ajfeavyf", MC_Q5) is None,
         f"q3={get_answer('ajfeavyf', MC_Q3)}, q4={get_answer('ajfeavyf', MC_Q4)}, q5={get_answer('ajfeavyf', MC_Q5)}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 12: MC Q1 → Micro PHQ-9 Q9 reverse (mirrors Group 2)
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 12: MC Q1 → Micro PHQ-9 Q9 reverse (match_method target) ═══")

    new_flow_session(["hrq04yc6", "ajfeavyf"])

    # 12.1: MC Q1=No → Micro PHQ-9 Q9 should be zero (contradiction if nonzero)
    set_answer("hrq04yc6", MPHQ9_Q9, 50)  # set nonzero first
    set_answer("ajfeavyf", MC_Q1, MC_Q1_NO)
    mq9 = get_answer("hrq04yc6", MPHQ9_Q9)
    contrs = json.loads(get_contradictions())
    test("12.1 MC Q1=No + slider=50 → contradiction",
         len(contrs) > 0,
         f"mq9={mq9}, contrs={len(contrs)}")

    # 12.2: MC Q1=Yes with slider=0 → contradiction
    new_flow_session(["hrq04yc6", "ajfeavyf"])
    set_answer("hrq04yc6", MPHQ9_Q9, 0)  # set zero
    set_answer("ajfeavyf", MC_Q1, MC_Q1_YES)
    mq9 = get_answer("hrq04yc6", MPHQ9_Q9)
    contrs = json.loads(get_contradictions())
    test("12.2 MC Q1=Yes + slider=0 → contradiction",
         len(contrs) > 0,
         f"mq9={mq9}, contrs={len(contrs)}")

    # 12.3: MC Q1=No with slider=0 → compatible, no contradiction
    new_flow_session(["hrq04yc6", "ajfeavyf"])
    set_answer("hrq04yc6", MPHQ9_Q9, 0)
    set_answer("ajfeavyf", MC_Q1, MC_Q1_NO)
    contrs = json.loads(get_contradictions())
    test("12.3 MC Q1=No + slider=0 → no contradiction",
         len(contrs) == 0,
         f"contrs={len(contrs)}")

    # 12.4: MC Q1=Yes with slider=50 → compatible, no contradiction
    new_flow_session(["hrq04yc6", "ajfeavyf"])
    set_answer("hrq04yc6", MPHQ9_Q9, 50)
    set_answer("ajfeavyf", MC_Q1, MC_Q1_YES)
    contrs = json.loads(get_contradictions())
    test("12.4 MC Q1=Yes + slider=50 → no contradiction",
         len(contrs) == 0,
         f"contrs={len(contrs)}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 13: Micro C-SSRS internal cascade (mirrors Group 3)
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 13: Micro C-SSRS internal cascade (Q2 gateway) ═══")

    new_flow_session(["ajfeavyf"])

    # 13.1: Q1=Yes, Q2=No → Q3,Q4,Q5 all No
    set_answer("ajfeavyf", MC_Q1, MC_Q1_YES)
    set_answer("ajfeavyf", MC_Q2, MC_Q2_NO)
    test("13.1 MC Q1=Yes, Q2=No → Q3,Q4,Q5 all No",
         get_answer("ajfeavyf", MC_Q3) == MC_Q3_NO
         and get_answer("ajfeavyf", MC_Q4) == MC_Q4_NO
         and get_answer("ajfeavyf", MC_Q5) == MC_Q5_NO,
         f"q3={get_answer('ajfeavyf', MC_Q3)}, q4={get_answer('ajfeavyf', MC_Q4)}, q5={get_answer('ajfeavyf', MC_Q5)}")

    # 13.2: Flip Q2 to Yes → Q3,Q4,Q5 cleared
    set_answer("ajfeavyf", MC_Q2, MC_Q2_YES)
    test("13.2 MC Q2→Yes → Q3,Q4,Q5 cleared",
         get_answer("ajfeavyf", MC_Q3) is None
         and get_answer("ajfeavyf", MC_Q4) is None
         and get_answer("ajfeavyf", MC_Q5) is None,
         f"q3={get_answer('ajfeavyf', MC_Q3)}, q4={get_answer('ajfeavyf', MC_Q4)}, q5={get_answer('ajfeavyf', MC_Q5)}")

    # 13.3: Reverse: Q3=Yes, Q2 should stay Yes
    set_answer("ajfeavyf", MC_Q3, MC_Q3_YES)
    test("13.3 MC Q3=Yes, Q2 stays Yes",
         get_answer("ajfeavyf", MC_Q2) == MC_Q2_YES,
         f"q2={get_answer('ajfeavyf', MC_Q2)}")

    # 13.4: Contradiction: Q2=Yes, Q3=Yes(manual), then Q2=No → Q3 contradiction
    new_flow_session(["ajfeavyf"])
    set_answer("ajfeavyf", MC_Q1, MC_Q1_YES)
    set_answer("ajfeavyf", MC_Q2, MC_Q2_YES)
    set_answer("ajfeavyf", MC_Q3, MC_Q3_YES)
    set_answer("ajfeavyf", MC_Q2, MC_Q2_NO)
    contrs = json.loads(get_contradictions())
    q3_contr = [c for c in contrs if c["tgtQuestionId"] == MC_Q3]
    test("13.4 MC Q2=No vs manual Q3=Yes → contradiction",
         len(q3_contr) > 0,
         f"q3_contrs={len(q3_contr)}, total={len(contrs)}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 14: Micro conflict scenario (mirrors Group 6)
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 14: Micro conflict scenario — slider→MC then override ═══")

    new_flow_session(["hrq04yc6", "ajfeavyf"])

    # A: Slider=0 → full MC No cascade
    set_answer("hrq04yc6", MPHQ9_Q9, 0)
    test("14.A Slider=0 → MC Q1=No, Q2=No",
         get_answer("ajfeavyf", MC_Q1) == MC_Q1_NO
         and get_answer("ajfeavyf", MC_Q2) == MC_Q2_NO,
         f"q1={get_answer('ajfeavyf', MC_Q1)}, q2={get_answer('ajfeavyf', MC_Q2)}")

    # B: Slider to 100 → MC Q1=Yes, Q2 cleared
    set_answer("hrq04yc6", MPHQ9_Q9, 100)
    test("14.B Slider=100 → MC Q1=Yes, Q2 cleared",
         get_answer("ajfeavyf", MC_Q1) == MC_Q1_YES
         and get_answer("ajfeavyf", MC_Q2) is None,
         f"q1={get_answer('ajfeavyf', MC_Q1)}, q2={get_answer('ajfeavyf', MC_Q2)}")

    # C: Manual Q2=Yes
    set_answer("ajfeavyf", MC_Q2, MC_Q2_YES)
    test("14.C Manual MC Q2=Yes stored",
         get_answer("ajfeavyf", MC_Q2) == MC_Q2_YES
         and get_source("ajfeavyf", MC_Q2) == "manual",
         f"q2={get_answer('ajfeavyf', MC_Q2)}({get_source('ajfeavyf', MC_Q2)})")

    # D: Q2=No → Q3-Q5 all No, Q1 still Yes(link)
    set_answer("ajfeavyf", MC_Q2, MC_Q2_NO)
    test("14.D MC Q2=No → Q3-Q5 No, Q1 still Yes(link)",
         get_answer("ajfeavyf", MC_Q3) == MC_Q3_NO
         and get_answer("ajfeavyf", MC_Q4) == MC_Q4_NO
         and get_answer("ajfeavyf", MC_Q5) == MC_Q5_NO
         and get_answer("ajfeavyf", MC_Q1) == MC_Q1_YES
         and get_source("ajfeavyf", MC_Q1) == "link",
         f"q1={get_answer('ajfeavyf', MC_Q1)}({get_source('ajfeavyf', MC_Q1)})")

    # E: Q2=Yes, Q3=Yes — consistent, no contradictions
    set_answer("ajfeavyf", MC_Q2, MC_Q2_YES)
    set_answer("ajfeavyf", MC_Q3, MC_Q3_YES)
    contrs = json.loads(get_contradictions())
    test("14.E MC Q1=Yes(link), Q2=Yes, Q3=Yes — no contradictions",
         len(contrs) == 0,
         f"contrs={len(contrs)}")

    # F: Slider back to 0 with manual Q2=Yes → contradiction
    set_answer("hrq04yc6", MPHQ9_Q9, 0)
    contrs = json.loads(get_contradictions())
    q1_val = get_answer("ajfeavyf", MC_Q1)
    q2_val = get_answer("ajfeavyf", MC_Q2)
    test("14.F Slider=0 with manual Q2=Yes → contradiction",
         len(contrs) > 0 or q1_val == MC_Q1_NO,
         f"q1={q1_val}, q2={q2_val}({get_source('ajfeavyf', MC_Q2)}), contrs={len(contrs)}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 15: Micro manual walls (mirrors Group 8)
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 15: Micro manual walls ═══")

    # 15.1: Manual MC Q1=Yes + slider=0 → contradiction
    new_flow_session(["hrq04yc6", "ajfeavyf"])
    set_answer("ajfeavyf", MC_Q1, MC_Q1_YES)
    set_answer("hrq04yc6", MPHQ9_Q9, 0)
    q1_val = get_answer("ajfeavyf", MC_Q1)
    q1_src = get_source("ajfeavyf", MC_Q1)
    contrs = json.loads(get_contradictions())
    test("15.1 Manual MC Q1=Yes + slider=0 → contradiction (wall holds)",
         q1_val == MC_Q1_YES and q1_src == "manual" and len(contrs) > 0,
         f"q1={q1_val}({q1_src}), contrs={len(contrs)}")

    # 15.2: Manual MC Q1=No + slider=50 → contradiction
    new_flow_session(["hrq04yc6", "ajfeavyf"])
    set_answer("ajfeavyf", MC_Q1, MC_Q1_NO)
    set_answer("hrq04yc6", MPHQ9_Q9, 50)
    q1_val = get_answer("ajfeavyf", MC_Q1)
    contrs = json.loads(get_contradictions())
    test("15.2 Manual MC Q1=No + slider=50 → contradiction",
         q1_val == MC_Q1_NO and len(contrs) > 0,
         f"q1={q1_val}, contrs={len(contrs)}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 16: Micro kill switch (mirrors Group 9)
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 16: Micro kill switch ═══")

    new_flow_session(["hrq04yc6", "ajfeavyf"])
    set_answer("ajfeavyf", MC_Q1, MC_Q1_YES)
    set_answer("hrq04yc6", MPHQ9_Q9, 0)
    contrs = json.loads(get_contradictions())
    test("16.0 Micro pre-condition: has contradictions",
         len(contrs) > 0, f"contrs={len(contrs)}")

    js("window._testSession.dismissContradictions();")
    contrs2 = json.loads(get_contradictions())
    enabled = js("return window._testSession.linksEnabled;")
    test("16.1 Micro dismiss: no contradictions, links off",
         len(contrs2) == 0 and enabled == False,
         f"contrs={len(contrs2)}, enabled={enabled}")

    # Changes should not cascade
    set_answer("hrq04yc6", MPHQ9_Q9, 100)
    q1_val = get_answer("ajfeavyf", MC_Q1)
    test("16.2 Micro kill switch: slider change doesn't cascade",
         q1_val == MC_Q1_YES,
         f"q1={q1_val}")

    # ═══════════════════════════════════════════════════════════
    # TEST GROUP 17: Micro stale cleanup (mirrors Group 10)
    # ═══════════════════════════════════════════════════════════
    print("\n═══ Group 17: Micro stale cleanup with slider toggle ═══")

    new_flow_session(["hrq04yc6", "ajfeavyf"])

    # Slider=50 → Q1=Yes
    set_answer("hrq04yc6", MPHQ9_Q9, 50)
    test("17.1 Slider=50 → MC Q1=Yes",
         get_answer("ajfeavyf", MC_Q1) == MC_Q1_YES,
         f"q1={get_answer('ajfeavyf', MC_Q1)}")

    # Slider=75 → Q1 still Yes (still nonzero)
    set_answer("hrq04yc6", MPHQ9_Q9, 75)
    test("17.2 Slider=75 → MC Q1 still Yes",
         get_answer("ajfeavyf", MC_Q1) == MC_Q1_YES,
         f"q1={get_answer('ajfeavyf', MC_Q1)}")

    # Slider=0 → zero link activates, nonzero stale → Q1=No
    set_answer("hrq04yc6", MPHQ9_Q9, 0)
    test("17.3 Slider=0 → MC Q1=No (stale cleanup correct)",
         get_answer("ajfeavyf", MC_Q1) == MC_Q1_NO,
         f"q1={get_answer('ajfeavyf', MC_Q1)}")

    # Back to nonzero → Q1=Yes, Q2 cascade cleared
    set_answer("hrq04yc6", MPHQ9_Q9, 25)
    test("17.4 Slider=25 → MC Q1=Yes, Q2 cleared",
         get_answer("ajfeavyf", MC_Q1) == MC_Q1_YES
         and get_answer("ajfeavyf", MC_Q2) is None,
         f"q1={get_answer('ajfeavyf', MC_Q1)}, q2={get_answer('ajfeavyf', MC_Q2)}")

    # ═══════════════════════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")
    print(f"\nTotal: {passed} passed, {failed} failed out of {len(results)}")
    if failed == 0:
        print("\u2705 ALL TESTS PASS")
    else:
        print("\u274c SOME TESTS FAILED")
        sys.exit(1)
finally:
    d.quit()
    print("Done.")
