"""Plan-lane vocabulary contract: stage, state, outcome and round-trip bounds.

Owner split per #308: one owner for the words the plan lane is allowed to
say. Stage composition, context intake, consensus and the waist all import
these names instead of redefining them, so the vocabulary cannot drift
between the concerns that use it."""




MAX_WAIST_ROUNDS = 2

MAX_WINDOWS_PER_ROUND = 8

MAX_WINDOW_LINES = 200

WAIST_MAX_TOKENS = 1500
MAX_BRIEF_FILES = 12

STAGE_CONTEXT = "context"

STAGE_PLANNING = "planning"

STAGE_EXECUTION = "execution"

STAGE_VERIFICATION = "verification"

STAGE_ORDER = (STAGE_CONTEXT, STAGE_PLANNING,
               STAGE_EXECUTION, STAGE_VERIFICATION)

HOURGLASS_DEFAULT_STAGES = STAGE_ORDER

STAGE_BYPASS_REASONS = {
    STAGE_CONTEXT: "a brief was supplied; intake already ran",
    STAGE_PLANNING: "a plan was supplied; decomposition already ran",
}

STAGE_DENIED_BYPASS = {
    STAGE_CONTEXT: "supplied brief is not fresh; intake runs again",
}

STATE_COMPLETED = "completed"

STATE_SKIPPED = "skipped"

STATE_PENDING = "pending"

STAGE_STATES = (STATE_COMPLETED, STATE_SKIPPED, STATE_PENDING)

STAGE_INPUT_DECAY = 0.5

STAGE_OUTPUT_DECAY = 0.5

MIN_STAGE_INPUT_TOKENS = 1024

MIN_STAGE_OUTPUT_TOKENS = 256

PLANNING_SHRINK = 0.5

MIN_ROUND_TOKENS = 1024

OUTCOME_SUFFICIENT = "sufficient"

OUTCOME_PLAN = "plan"

OUTCOME_EVIDENCE_REQUEST = "evidence_request"

OUTCOME_DEFER = "defer"

PLAN_OUTCOMES = (OUTCOME_SUFFICIENT, OUTCOME_PLAN,
                 OUTCOME_EVIDENCE_REQUEST, OUTCOME_DEFER)

MAX_EVIDENCE_QUESTIONS = 5

MAX_EVIDENCE_QUESTION_CHARS = 400

MAX_EVIDENCE_REQUEST_CHARS = MAX_EVIDENCE_QUESTIONS * MAX_EVIDENCE_QUESTION_CHARS

MAX_DEFER_REASON_CHARS = 400
