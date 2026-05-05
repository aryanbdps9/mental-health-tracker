"""Test suite: create micro, generate full, export, history filter."""
import json, time, os, sys
from selenium import webdriver

PORT = 56008
PW = "test123"
BASE = f"http://127.0.0.1:{PORT}"

phq9_id = micro_phq9_id = None
for fn in os.listdir("questionnaires"):
    if not fn.endswith(".json") or fn == "flows.json": continue
    with open(f"questionnaires/{fn}") as f: q = json.load(f)
    if q["title"] == "PHQ-9 Depression": phq9_id = q["id"]
    elif q["title"] == "Micro PHQ-9": micro_phq9_id = q["id"]

opts = webdriver.EdgeOptions()
opts.add_argument("--headless=new"); opts.add_argument("--no-sandbox")
d = webdriver.Edge(options=opts)
jsa = lambda s: d.execute_async_script(
    'const done=arguments[arguments.length-1];(async()=>{'+s+'})().then(r=>done(r)).catch(e=>done("ERR:"+e.message));')

results = []
try:
    d.get(BASE); time.sleep(3)
    jsa("const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:'"+PW+"'})}); return r.ok?'ok':'fail';")
    d.get(BASE); time.sleep(2)

    print("Test 1: Create micro PHQ-9 entry")
    r = jsa("const qd={}; const mid='"+micro_phq9_id+"'; qd[mid]=await api('/api/questionnaire/'+mid); session=new FlowSession({flowId:null,sessionId:crypto.randomUUID(),order:[mid],qDefs:qd,gapHours:24}); const vis=session.visibleQuestions(mid); for(const q of vis){if(q.type==='slider')session.setAnswer(mid,q.id,50);else if(q.options&&q.options.length)session.setAnswer(mid,q.id,q.options[0].id);} questionIndex=0; await doAutosave(); await submitCurrent(); return 'ok';")
    print(f"  Created: {r}")
    entries_r = jsa("const e=await api('/api/entries'); return JSON.stringify(e);")
    entries = json.loads(entries_r)
    micro_count = sum(1 for e in entries if e.get("micro"))
    print(f"  Entries: {len(entries)}, micro: {micro_count}")
    results.append(("Create micro", micro_count >= 1))

    print("\nTest 2: Generate full PHQ-9")
    gen_r = jsa("const r=await api('/api/generate',{method:'POST',body:JSON.stringify({targets:[{questionnaire_id:'"+phq9_id+"',days:14}]})}); return JSON.stringify(r);")
    gen = json.loads(gen_r)
    print(f"  Generated: {gen.get('generated')}")
    if gen.get("generated", 0) > 0:
        ge = gen["entries"][0]
        print(f"  Score: {ge.get('scores',{}).get('total','N/A')}, severity: {ge.get('scores',{}).get('severity','N/A')}")
        print(f"  Generated: {ge.get('generated')}, method: {ge.get('generation_method')}")
    t2_ok = gen.get("generated", 0) > 0 and gen["entries"][0].get("generated") == True
    results.append(("Generate full", t2_ok))

    print("\nTest 3: Export md")
    entries_r2 = jsa("return JSON.stringify(await api('/api/entries'));")
    entries2 = json.loads(entries_r2)
    eids = json.dumps([e["entry_id"] for e in entries2[:2]])
    export_r = jsa("const r=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({entry_ids:"+eids+",formats:['md']})}); const b=await r.blob(); return 'size='+b.size+' type='+r.headers.get('Content-Type');")
    print(f"  Export: {export_r}")
    t3_ok = "size=" in str(export_r) and "ERR" not in str(export_r)
    results.append(("Export md", t3_ok))

    print("\nTest 4: History types")
    entries3 = json.loads(jsa("return JSON.stringify(await api('/api/entries'));"))
    has_micro = any(e.get("micro") for e in entries3)
    has_gen = any(e.get("generated") for e in entries3)
    print(f"  Micro: {has_micro}, Generated: {has_gen}")
    results.append(("Both types", has_micro and has_gen))

    print("\n" + "=" * 40)
    all_pass = all(ok for _, ok in results)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")
    print(f"\n{'pass_emoji' if all_pass else 'fail_emoji'}".replace("pass_emoji", "\u2705 ALL PASS").replace("fail_emoji", "\u274c SOME FAILED"))
    if not all_pass: sys.exit(1)
finally:
    d.quit()
    print("Done.")
