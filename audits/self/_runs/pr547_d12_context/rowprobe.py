import importlib.util

spec = importlib.util.spec_from_file_location('aud', 'audits/self/audit.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

skip = {"D12", "D8"}
for dim, rows in m.CHECKS.items():
    for rid, title, fn in rows:
        if rid in skip:
            print(f"{dim}.{rid} SKIPPED(by probe)", flush=True)
            continue
        try:
            r = fn()
            score = r[0] if isinstance(r, tuple) else r
            ev = r[1] if isinstance(r, tuple) and len(r) > 1 else ""
            flag = "OK " if (isinstance(score, (int, float)) and score >= 1.0) else "BAD"
            print(f"{flag} {dim}.{rid} {title[:52]} :: {str(ev)[:240]}", flush=True)
        except Exception as e:
            print(f"ERR {dim}.{rid} {title[:52]} :: {type(e).__name__}: {e}", flush=True)
