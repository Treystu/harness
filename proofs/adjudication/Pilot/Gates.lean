/-
  Tier 0 + documentation-tier pilot: soundness of the *checker schemas*.

  HONEST SCOPE (cold-review cure, 2026-11-26): the theorems below are about
  Bool flags on records. `receiptCheck_sound` proves that IF the four flags
  are true THEN they are true — it does NOT prove that `headMatches`
  corresponds to any actual git head, `censusComplete` to any actual census,
  or `sorryFree` to any actual absence of sorry. That binding — flags to
  reality — is the job of the executable checker (proofgate.py), which in v2
  computes the census from a git diff range and verifies each claim's
  evidence as the sha256 of the claimed file's content at the receipt head.
  What Lean proves here is the schema's internal logic: the conjunction
  cannot partially hold, and a false census flag can never check out.
  Content truth of the underlying claims stays with evidence/Jev, always.
-/

namespace Pilot

/-- A load-bearing claim extracted from a documentation (or any) diff. -/
structure DocClaim where
  id : Nat
  hasEvidence : Bool
  numberChecked : Bool   -- printed quantities re-derived from a primary source
  deriving Repr

/-- The doc gate: every claim in the diff must carry evidence and have its
    printed numbers checked. -/
def docCheck (claims : List DocClaim) : Bool :=
  claims.all fun c => c.hasEvidence && c.numberChecked

theorem docCheck_sound {claims : List DocClaim} (h : docCheck claims = true) :
    ∀ c ∈ claims, c.hasEvidence = true ∧ c.numberChecked = true := by
  intro c hc
  have h2 := List.all_eq_true.mp h c hc
  simp only [Bool.and_eq_true] at h2
  exact h2

/-- Contrapositive used by the gate: one unevidenced claim fails the whole diff. -/
theorem docCheck_rejects {claims : List DocClaim} {c : DocClaim}
    (hc : c ∈ claims) (he : c.hasEvidence = false) :
    docCheck claims = false := by
  cases h : docCheck claims with
  | false => rfl
  | true =>
    have h1 := (docCheck_sound h c hc).1
    rw [he] at h1
    exact Bool.noConfusion h1

/-- Tier 0 verification receipt for any commit (code, docs, config, mixed). -/
structure Receipt where
  headMatches : Bool      -- evidence hash-bound to the exact head SHA
  censusComplete : Bool   -- claim covers the full obligation census
  sorryFree : Bool        -- no UNVERIFIED / pending / hand-assembled proof
  axiomsDeclared : Bool   -- every assumption listed in the statement
  deriving Repr

/-- Companion to docCheck_rejects for the numbers half of the conjunction. -/
theorem docCheck_rejects_numbers {claims : List DocClaim} {c : DocClaim}
    (hc : c ∈ claims) (hn : c.numberChecked = false) :
    docCheck claims = false := by
  cases h : docCheck claims with
  | false => rfl
  | true =>
    have h2 := (docCheck_sound h c hc).2
    rw [hn] at h2
    exact Bool.noConfusion h2

def receiptCheck (r : Receipt) : Bool :=
  r.headMatches && r.censusComplete && r.sorryFree && r.axiomsDeclared

theorem receiptCheck_sound {r : Receipt} (h : receiptCheck r = true) :
    r.headMatches = true ∧ r.censusComplete = true ∧
    r.sorryFree = true ∧ r.axiomsDeclared = true := by
  simp only [receiptCheck, Bool.and_eq_true] at h
  exact ⟨h.1.1.1, h.1.1.2, h.1.2, h.2⟩

/-- A receipt for a partial census can never check out, whatever else is true.
    This is the formal version of our recorded failure: a claim covering part
    of a set reported as complete. -/
theorem receipt_rejects_partial_census {r : Receipt}
    (h : r.censusComplete = false) : receiptCheck r = false := by
  simp [receiptCheck, h]

end Pilot
