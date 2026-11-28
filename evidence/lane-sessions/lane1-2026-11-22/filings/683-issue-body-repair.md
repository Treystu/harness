# Repair note: issue bodies posted with their JSON envelope

The 21 issues filed for #683 from batch 6 onward (#768-#788) were created with
`gh issue create --title ... --body-file .issue-body.json`. That flag posts the
file verbatim, so each issue carried the `{"title": ..., "body": ...}`
envelope instead of the markdown it wrapped. The titles, the gate receipts and
the artifact text were all present; they were inside one JSON string.

Repaired on 2026-11-25 by `repair_issue_bodies.py`: for each number it reads
the issue body back, unwraps the envelope, and edits the issue with the plain
text. Nothing was rewritten by hand and no artifact was re-gated, because the
repaired text is byte-for-byte the text the gate passed. 21 repaired, 0 failed.
A scan of every open issue for a body starting with `{"title"` now returns an
empty list.

Earlier issues (#749-#767) are unaffected: they were created by writing the
markdown body file directly, which is the pattern the repair restores.

Forward rule: the payload file is an argument to the API call, never the body
file. `gh issue create --body-file` receives markdown only.
