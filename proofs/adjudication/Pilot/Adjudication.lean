/-
  Tier 1 pilot: Lean model of Treystu/harness `harness/adjudication.py`
  (main c167a0c; the Python file is 199 lines — verdict mapping, aggregation,
  the DEFER validation, and `non_jev_fallback` are all modelled below).

  MODEL FIDELITY NOTES (declared limitations of the model, not hidden):
  * Python floats support/risk are modelled as per-mille Nat (×1000).
    Thresholds: SUPPORT_REAL_MIN 0.65 → 650, SUPPORT_NOT_REAL_MAX 0.35 → 350,
    RISK_MAX 0.30 → 300. The model is EXACT only for inputs that are
    multiples of 0.001 inside [0,1]. Every other float input is outside the
    model: sub-per-mille values round across boundaries, 0.65 is not exact
    in binary, NaN makes all Python comparisons false (→ DEFER), and
    out-of-range values (support 2.0, negative, inf) have no per-mille
    counterpart. The differential test therefore uses per-mille inputs only.
  * String claim ids/text, evidence refs, and the stored missing_context
    tuple are not fields of the Lean records: they play no role in the
    verdict logic. The missing_context VALUE is a parameter of
    `adjudicateChecked`, which models the Python validation (DEFER without
    a named missing-context list raises ValueError → Lean `none`).
  * Python's runtime string validation (unknown polarity/materiality/
    verdict strings raise in `__post_init__`) is NOT modelled: Lean enums
    make such values unrepresentable inside Lean, which proves nothing
    about the Python entry path where raw strings/JSON enter.
  * `confidence_note` and `per_claim` are not modelled: the model covers
    the verdict path (final, rule, escalate) only. Supporting claims DO
    affect the Python result's confidence note; a tally regression there
    is invisible to this model.
  * Advisory notes are omitted: the verdict path never consults them.
-/

namespace Pilot

inductive Polarity where
  | defect
  | reassurance
  deriving DecidableEq, Repr

inductive Materiality where
  | material
  | supporting
  deriving DecidableEq, Repr

inductive CVerdict where
  | real
  | notReal
  | defer
  deriving DecidableEq, Repr

inductive Final where
  | pass
  | fail
  | defer
  deriving DecidableEq, Repr

structure Claim where
  id : Nat
  polarity : Polarity
  materiality : Materiality
  deriving Repr

structure Adj where
  claim : Claim
  verdict : CVerdict
  support : Nat
  risk : Nat
  contradicted : Bool
  deriving Repr

/-- Deterministic mapping v1: REAL iff support ≥ 650 ∧ risk ≤ 300;
    NOT_REAL iff support ≤ 350 ∧ risk ≤ 300; otherwise DEFER. -/
def adjudicate (c : Claim) (support risk : Nat) : Adj :=
  if support ≥ 650 ∧ risk ≤ 300 then
    { claim := c, verdict := .real, support, risk, contradicted := false }
  else if support ≤ 350 ∧ risk ≤ 300 then
    { claim := c, verdict := .notReal, support, risk, contradicted := false }
  else
    { claim := c, verdict := .defer, support, risk, contradicted := false }

theorem adjudicate_real {c : Claim} {s r : Nat} (hs : s ≥ 650) (hr : r ≤ 300) :
    (adjudicate c s r).verdict = .real := by
  unfold adjudicate
  rw [if_pos ⟨hs, hr⟩]

theorem adjudicate_notReal {c : Claim} {s r : Nat}
    (hs : s ≤ 350) (hr : r ≤ 300) :
    (adjudicate c s r).verdict = .notReal := by
  unfold adjudicate
  rw [if_neg (by omega), if_pos ⟨hs, hr⟩]

theorem adjudicate_defer_of_high_risk {c : Claim} {s r : Nat} (hr : r > 300) :
    (adjudicate c s r).verdict = .defer := by
  unfold adjudicate
  rw [if_neg (by omega), if_neg (by omega)]

theorem adjudicate_defer_of_middle {c : Claim} {s r : Nat}
    (h1 : s < 650) (h2 : 350 < s) :
    (adjudicate c s r).verdict = .defer := by
  unfold adjudicate
  rw [if_neg (by omega), if_neg (by omega)]

/-- Boolean predicates over the material claims, mirroring the Python `any(...)`
    checks over `material = [a for a in adjudications if materiality == material]`. -/
def isMat (a : Adj) : Bool :=
  match a.claim.materiality with
  | .material => true
  | .supporting => false

def hasMatDefer (l : List Adj) : Bool :=
  l.any fun a => isMat a && match a.verdict with | .defer => true | _ => false

def hasMatDefectReal (l : List Adj) : Bool :=
  l.any fun a => isMat a &&
    (match a.verdict, a.claim.polarity with | .real, .defect => true | _, _ => false)

def hasMatReassNotReal (l : List Adj) : Bool :=
  l.any fun a => isMat a &&
    (match a.verdict, a.claim.polarity with | .notReal, .reassurance => true | _, _ => false)

def hasMatContradicted (l : List Adj) : Bool :=
  l.any fun a => isMat a && a.contradicted

/-- Lexicographic aggregation v1: (final, deciding rule, escalate). -/
def aggregate (l : List Adj) : Final × Nat × Bool :=
  if hasMatDefer l then (.defer, 1, true)
  else if hasMatDefectReal l then (.fail, 2, false)
  else if hasMatReassNotReal l then (.fail, 3, false)
  else if hasMatContradicted l then (.defer, 4, false)
  else (.pass, 5, false)

/-- Rule 5: with no material blocker of any kind, the result is PASS by rule 5.
    Supporting claims cannot swing this: they are filtered by `isMat` in every
    predicate above, which is exactly the Python contract. -/
theorem aggregate_pass {l : List Adj}
    (h1 : hasMatDefer l = false) (h2 : hasMatDefectReal l = false)
    (h3 : hasMatReassNotReal l = false) (h4 : hasMatContradicted l = false) :
    aggregate l = (.pass, 5, false) := by
  simp [aggregate, h1, h2, h3, h4]

/-- Rule 1 fires first: a material DEFER can never be a silent pass,
    regardless of what else is present (lexicographic precedence). -/
theorem aggregate_defer_first {l : List Adj} (h : hasMatDefer l = true) :
    aggregate l = (.defer, 1, true) := by
  simp [aggregate, h]

/-- Rule 2: a material defect REAL (and no material DEFER ahead of it) is FAIL. -/
theorem aggregate_fail_defect {l : List Adj}
    (h1 : hasMatDefer l = false) (h2 : hasMatDefectReal l = true) :
    aggregate l = (.fail, 2, false) := by
  simp [aggregate, h1, h2]

/-- Corollary of rules 1–2: a material defect REAL alone rules out PASS. -/
theorem aggregate_ne_pass_of_defect {l : List Adj} (h : hasMatDefectReal l = true) :
    (aggregate l).1 ≠ .pass := by
  by_cases hd : hasMatDefer l
  · simp [aggregate, hd]
  · simp [aggregate, hd, h]

/-- Empty adjudication set passes by rule 5 (matches Python: no material claims). -/
theorem aggregate_nil : aggregate [] = (.pass, 5, false) := by
  decide


/-- RSI cure G1a (2026-11-26): the Python `ClaimAdjudication.__post_init__`
    validation — a DEFER verdict requires a named missing-context list, and
    `adjudicate_claim` raises ValueError without one. Modelled as an Option:
    None = the Python raise. -/
def adjudicateChecked (c : Claim) (support risk : Nat) (missing : List String) : Option Adj :=
  if (adjudicate c support risk).verdict = .defer ∧ missing = [] then none
  else some (adjudicate c support risk)

theorem checked_defer_requires_missing {c : Claim} {s r : Nat} {m : List String} {a : Adj}
    (h : adjudicateChecked c s r m = some a) (hv : a.verdict = .defer) :
    m ≠ [] := by
  intro hm
  subst hm
  unfold adjudicateChecked at h
  cases hvd : (adjudicate c s r).verdict with
  | real =>
    rw [if_neg (by simp [hvd])] at h
    have ha : adjudicate c s r = a := Option.some.inj h
    rw [← ha] at hv
    rw [hvd] at hv
    exact CVerdict.noConfusion hv
  | notReal =>
    rw [if_neg (by simp [hvd])] at h
    have ha : adjudicate c s r = a := Option.some.inj h
    rw [← ha] at hv
    rw [hvd] at hv
    exact CVerdict.noConfusion hv
  | defer =>
    rw [if_pos ⟨hvd, rfl⟩] at h
    cases h

theorem checked_real_always_some {c : Claim} {s r : Nat} (hs : s ≥ 650) (hr : r ≤ 300)
    (m : List String) :
    (adjudicateChecked c s r m).isSome = true := by
  unfold adjudicateChecked
  rw [if_neg (by simp [adjudicate_real hs hr])]
  rfl

/-- RSI cure G1b: `non_jev_fallback` (adjudication.py lines 161-186) —
    (final, deciding rule, escalate, fallback label present). -/
def nonJevFallback (consensus : Final) : Final × Nat × Bool × Bool :=
  (consensus, 0, match consensus with | .defer => true | _ => false, true)

theorem fallback_rule_zero (consensus : Final) :
    (nonJevFallback consensus).2.1 = 0 := rfl

theorem fallback_escalate_iff_defer (consensus : Final) :
    (nonJevFallback consensus).2.2.1 = true ↔ consensus = .defer := by
  cases consensus <;> simp [nonJevFallback]

theorem fallback_preserves_final (consensus : Final) :
    (nonJevFallback consensus).1 = consensus := rfl

/-- RSI cure (reviewer item 8): the returned record preserves the claim and
    echoes support/risk; contradicted starts false. -/
theorem adjudicate_claim_eq {c : Claim} {s r : Nat} :
    (adjudicate c s r).claim = c := by
  by_cases h1 : s ≥ 650 ∧ r ≤ 300
  · unfold adjudicate; rw [if_pos h1]
  · by_cases h2 : s ≤ 350 ∧ r ≤ 300
    · unfold adjudicate; rw [if_neg h1, if_pos h2]
    · unfold adjudicate; rw [if_neg h1, if_neg h2]

theorem adjudicate_support_eq {c : Claim} {s r : Nat} :
    (adjudicate c s r).support = s ∧ (adjudicate c s r).risk = r ∧
    (adjudicate c s r).contradicted = false := by
  by_cases h1 : s ≥ 650 ∧ r ≤ 300
  · unfold adjudicate; rw [if_pos h1]; exact ⟨rfl, rfl, rfl⟩
  · by_cases h2 : s ≤ 350 ∧ r ≤ 300
    · unfold adjudicate; rw [if_neg h1, if_pos h2]; exact ⟨rfl, rfl, rfl⟩
    · unfold adjudicate; rw [if_neg h1, if_neg h2]; exact ⟨rfl, rfl, rfl⟩

/-- RSI cure (reviewer item 7): rules 3 and 4 now have theorems, including
    rule 4's escalate = false. -/
theorem aggregate_fail_reassurance {l : List Adj}
    (h1 : hasMatDefer l = false) (h2 : hasMatDefectReal l = false)
    (h3 : hasMatReassNotReal l = true) :
    aggregate l = (.fail, 3, false) := by
  simp [aggregate, h1, h2, h3]

theorem aggregate_defer_contradicted {l : List Adj}
    (h1 : hasMatDefer l = false) (h2 : hasMatDefectReal l = false)
    (h3 : hasMatReassNotReal l = false) (h4 : hasMatContradicted l = true) :
    aggregate l = (.defer, 4, false) := by
  simp [aggregate, h1, h2, h3, h4]

/-- RSI cure (reviewer item 6): the any-flags are connected to actual list
    membership, so a predicate typo that disconnects a flag from its members
    now breaks a theorem instead of passing silently. -/
theorem hasMatDefer_of_mem {l : List Adj} {a : Adj} (hm : a ∈ l)
    (hmat : a.claim.materiality = .material) (hv : a.verdict = .defer) :
    hasMatDefer l = true := by
  apply List.any_eq_true.mpr
  refine ⟨a, hm, ?_⟩
  cases hvm : a.verdict <;> cases hmm : a.claim.materiality <;> simp_all [isMat]

theorem hasMatDefectReal_of_mem {l : List Adj} {a : Adj} (hm : a ∈ l)
    (hmat : a.claim.materiality = .material) (hv : a.verdict = .real)
    (hp : a.claim.polarity = .defect) :
    hasMatDefectReal l = true := by
  apply List.any_eq_true.mpr
  refine ⟨a, hm, ?_⟩
  cases hvm : a.verdict <;> cases hmm : a.claim.materiality <;>
    cases hpm : a.claim.polarity <;> simp_all [isMat]

theorem hasMatReassNotReal_of_mem {l : List Adj} {a : Adj} (hm : a ∈ l)
    (hmat : a.claim.materiality = .material) (hv : a.verdict = .notReal)
    (hp : a.claim.polarity = .reassurance) :
    hasMatReassNotReal l = true := by
  apply List.any_eq_true.mpr
  refine ⟨a, hm, ?_⟩
  cases hvm : a.verdict <;> cases hmm : a.claim.materiality <;>
    cases hpm : a.claim.polarity <;> simp_all [isMat]

theorem hasMatContradicted_of_mem {l : List Adj} {a : Adj} (hm : a ∈ l)
    (hmat : a.claim.materiality = .material) (hc : a.contradicted = true) :
    hasMatContradicted l = true := by
  apply List.any_eq_true.mpr
  refine ⟨a, hm, ?_⟩
  cases hmm : a.claim.materiality <;> simp_all [isMat]

/-- End-to-end form of rule 1: a material DEFER sitting in the list decides. -/
theorem aggregate_defer_of_mem {l : List Adj} {a : Adj} (hm : a ∈ l)
    (hmat : a.claim.materiality = .material) (hv : a.verdict = .defer) :
    aggregate l = (.defer, 1, true) :=
  aggregate_defer_first (hasMatDefer_of_mem hm hmat hv)

end Pilot
