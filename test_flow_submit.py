"""Test: Flow single-submit-at-end behavior."""
import json, time, sys
from selenium import webdriver

PORT = 57166
PW = "test123"
BASE = f"http://127.0.0.1:{PORT}"

opts = webdriver.EdgeOptions()
opts.add_argument("--headless=new")
opts.add_argument("--no-sandbox")
d = webdriver.Edge(options=opts)
jsa = lambda s: d.execute_async_script(
    'const done=arguments[arguments.length-1];(async()=>{'+s+'})().then(r=>done(r)).catch(e=>done("ERR:"+e.message));')

try:
    d.get(BASE); time.sleep(3)
    jsa("const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:'"+PW+"'})}); return r.ok?'ok':'fail';")
    d.get(BASE); time.sleep(2)

    # Create a flow session with PHQ-9 + C-SSRS
    r = jsa("""
        const qids = ['aguqu2kg', 'vd5vesbs'];
        const qd = {};
        await Promise.all(qids.map(async q => { qd[q] = await api('/api/questionnaire/' + q); }));
        session = new FlowSession({ flowId: 'daily', sessionId: crypto.randomUUID(), order: qids, qDefs: qd, gapHours: 24 });
        questionIndex = 0;
        renderQuestion();
        return 'ok';
    """)
    print(f"Session created: {r}")
    time.sleep(1)

    # Answer all PHQ-9 questions with first option, go to summary
    r = jsa("""
        const qid = session.currentQId();
        const vis = session.visibleQuestions(qid);
        for (const q of vis) {
            if (q.options && q.options.length) session.setAnswer(qid, q.id, q.options[0].id);
        }
        questionIndex = vis.length;
        renderSummary();
        const btn = document.querySelector('.sticky-submit-bar button');
        return btn ? btn.textContent : 'NO BUTTON';
    """)
    print(f'PHQ-9 review button text: "{r}"')
    assert "Next" in r, f"Expected Next button, got: {r}"
    assert "Submit All" not in r, f"Non-last Q should not say Submit All, got: {r}"

    # Click Next → should advance without submitting
    r = jsa("await advanceToNext(); return session.step + ' ' + session.currentQId();")
    print(f"After Next: {r}")
    time.sleep(0.5)

    # No entries should exist yet
    entries = json.loads(jsa('return JSON.stringify(await api("/api/entries"));'))
    print(f"Entries after Next: {len(entries)} (should be 0)")
    assert len(entries) == 0, f"Expected 0 entries, got {len(entries)}"

    # Answer C-SSRS questions, go to summary
    r = jsa("""
        const qid = session.currentQId();
        const vis = session.visibleQuestions(qid);
        for (const q of vis) {
            if (q.options && q.options.length) session.setAnswer(qid, q.id, q.options[q.options.length - 1].id);
        }
        questionIndex = vis.length;
        renderSummary();
        const btn = document.querySelector('.sticky-submit-bar button');
        return btn ? btn.textContent : 'NO BUTTON';
    """)
    print(f'C-SSRS review button text: "{r}"')
    assert "Submit All" in r, f"Expected Submit All, got: {r}"

    # Click Submit All
    r = jsa('await submitAll(); return "done";')
    print(f"Submit All result: {r}")
    time.sleep(0.5)

    # Both entries should exist
    entries = json.loads(jsa('return JSON.stringify(await api("/api/entries"));'))
    print(f"Entries after Submit All: {len(entries)} (should be 2)")
    qids_submitted = sorted([e["questionnaire_id"] for e in entries])
    print(f"Questionnaires: {qids_submitted}")
    assert len(entries) == 2, f"Expected 2, got {len(entries)}"
    assert "aguqu2kg" in qids_submitted and "vd5vesbs" in qids_submitted

    print("\n\u2705 PASS: Flow single-submit test")
finally:
    d.quit()
    print("Done.")
