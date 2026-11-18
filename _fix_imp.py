from pathlib import Path
p = Path("harness/cli.py")
s = p.read_text(encoding="utf-8")
old = """    elif opts.ledger_cmd == "sweep":
        from .ledger_sweep import run_daily_sweep, state_path
        _emit(run_daily_sweep(ledger, state_file=state_path(ledger.path),
                              force=opts.force), opts.out)"""
new = """    elif opts.ledger_cmd == "sweep":
        _emit(run_daily_sweep(ledger, state_file=state_path(ledger.path),
                              force=opts.force), opts.out)"""
assert old in s
s = s.replace(old, new, 1)
# module-level import next to the ledger import
anchor = "from .ledger import AutonomyLedger"
if anchor not in s:
    raise SystemExit("ledger import missing")
if "from .ledger_sweep import run_daily_sweep, state_path" not in s:
    s = s.replace(anchor, anchor + "\nfrom .ledger_sweep import run_daily_sweep, state_path", 1)
p.write_text(s, encoding="utf-8")
print("import moved")
