import importlib.util, json, subprocess
spec = importlib.util.spec_from_file_location('aud', 'audits/self/audit.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

base, source = m.d12_base_ref()
print("base", base, source, flush=True)
d = subprocess.run(["git", "diff", "--unified=0", base, "--", "harness/"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
added = m._parse_added_lines(d.stdout)
print("files changed:", {k: len(v) for k, v in added.items()}, flush=True)
doc, cov_source = m.d12_coverage_doc(base)
print("coverage source:", cov_source[:400], flush=True)
if doc is None:
    print("NO COVERAGE DOC", flush=True)
else:
    checked, executed, gaps = m._coverage_ratio(ROOT if False else m.ROOT, added,
                                               doc.get("modules", {}), doc.get("executable_lines", {}))
    print(f"checked={checked} executed={executed} ratio={executed/max(1,checked):.3f}", flush=True)
    for f in sorted(gaps):
        print("GAP", f, sorted(gaps[f])[:20], flush=True)
