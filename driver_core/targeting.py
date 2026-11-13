"""#481 -- the bounded input-target model.

``docs/driver.md`` names this gap in its own words: the declared parameters
for ``click``, ``type_text``, ``press_key``, ``scroll`` and
``submit_irreversible`` "do not identify a sufficiently bounded target", which
is why those five refuse and only an exact-title ``focus`` executes. This
module is the target half of the cure, and it is deliberately a *model*
first: the platform backends that will use it need something exact to aim at
before any of them can be written.

A click is a pair -- **which** window, and **where** inside it. A bare title
is exact about the window and silent about the point, so:

* the legacy form (a non-empty string) stays accepted and resolves to itself,
  which keeps every existing consent, test and caller working unchanged. It is
  reported as *unbounded*, never silently upgraded to "somewhere in the
  window" -- guessing the point is precisely the behaviour this package
  exists to prevent.
* the bounded form is a mapping ``{"window": <exact title>, "rect":
  [x, y, width, height]}`` in the window's client coordinates. It resolves to
  a canonical record, and that canonical record is what the consent is bound
  to, because normalisation runs before the consent check and before anything
  is shown to the operator. A person who consented to one rectangle has not
  consented to another.

Refusals are named and total. An unknown key, a missing key, a title that is
not a title, a rectangle that is not four integers, a degenerate rectangle, a
rectangle whose origin or size is outside the declared bounds -- each raises
:class:`TargetError` rather than being trimmed into something plausible. The
vocabulary already refuses undeclared *parameters*; this module refuses
undeclared *shapes of a declared parameter*, for the same reason: something
outside the contract is trying to influence execution.
"""
from .errors import VocabularyError

#: The bounded target's schema name and version, carried on the canonical
#: record so an audit can tell a bounded target from a legacy title without
#: inferring it from the type.
TARGET_SCHEMA = "target@1"

#: The longest window title this model will carry. A title is an identity, not
#: a document; one that long is a payload or a mistake.
MAX_TITLE_LENGTH = 256

#: The largest coordinate and the largest side either axis may declare, in
#: client pixels. Generous enough for any current display matrix, small enough
#: that an arithmetic slip in a caller cannot become an aim point.
MAX_SIDE = 16384

#: The largest rectangle area this model will carry, in client pixels.
#: Deliberately smaller than ``MAX_SIDE * MAX_SIDE``: a 4096-pixel side is a
#: plausible coordinate slip, but a rectangle that fills that square cannot be
#: a control on any display this driver is meant to see, so area is its own
#: rule rather than an arithmetic consequence of the side limit.
MAX_AREA = 16777216

#: The declared keys of the bounded form, exactly. Extra keys are refused, so
#: a caller that tries to smuggle an offset or a selector alongside the
#: rectangle is told rather than obeyed.
BOUNDED_FIELDS = ("rect", "window")


class TargetError(VocabularyError):
    """A target that is not a target this model can bound."""


def _is_int(value):
    """A real integer, and never a ``bool``. ``True`` is an index in Python."""
    return isinstance(value, int) and not isinstance(value, bool)


def _checked_title(window):
    if not isinstance(window, str):
        raise TargetError(
            f"a target's window must be an exact title string, got "
            f"{type(window).__name__}")
    if not window.strip():
        raise TargetError("a target's window title must not be blank")
    if len(window) > MAX_TITLE_LENGTH:
        raise TargetError(
            f"a target's window title is {len(window)} characters; the model "
            f"carries at most {MAX_TITLE_LENGTH}")
    if any(ord(ch) < 32 for ch in window):
        raise TargetError("a target's window title may not contain control "
                          "characters")
    return window


def _checked_rect(rect):
    if isinstance(rect, (str, bytes)) or not isinstance(rect, (list, tuple)):
        raise TargetError(
            "a target's rect must be [x, y, width, height], got "
            f"{type(rect).__name__}")
    if len(rect) != 4:
        raise TargetError(
            f"a target's rect must have exactly four values, got {len(rect)}")
    if not all(_is_int(value) for value in rect):
        raise TargetError(
            f"a target's rect must be four integers, got {list(rect)!r}")
    x, y, width, height = (int(value) for value in rect)
    if x < 0 or y < 0:
        raise TargetError(
            f"a target's rect origin is client-relative and cannot be "
            f"negative, got x={x}, y={y}")
    if width < 1 or height < 1:
        raise TargetError(
            f"a target's rect must have a positive size, got "
            f"width={width}, height={height}")
    for label, value in (("x", x), ("y", y), ("width", width),
                         ("height", height)):
        if value > MAX_SIDE:
            raise TargetError(
                f"a target's rect {label} is {value}, beyond the model's "
                f"declared limit of {MAX_SIDE}")
    if width * height > MAX_AREA:
        raise TargetError(
            f"a target's rect area is {width * height}, beyond the model's "
            f"declared limit of {MAX_AREA}")
    return [x, y, width, height]


def resolve_target(value):
    """Resolve one declared ``target`` parameter to its canonical form.

    This is the normaliser the executor binds consent to, so it is called
    before the consent check, before the operator is shown anything and before
    anything executes. A legacy title resolves to itself; a bounded mapping
    resolves to :data:`TARGET_SCHEMA` with the title and rectangle it declared,
    validated in full.
    """
    if isinstance(value, str):
        return _checked_title(value)
    if not isinstance(value, dict):
        raise TargetError(
            "a target must be an exact window title or a bounded target "
            f"mapping {{'window', 'rect'}}, got {type(value).__name__}")
    unknown = sorted(set(value) - set(BOUNDED_FIELDS))
    if unknown:
        raise TargetError(
            f"a bounded target declares exactly {list(BOUNDED_FIELDS)}; "
            f"unknown key(s) {unknown}")
    missing = sorted(set(BOUNDED_FIELDS) - set(value))
    if missing:
        raise TargetError(
            f"a bounded target needs {list(BOUNDED_FIELDS)}; missing "
            f"key(s) {missing}")
    return {
        "schema": TARGET_SCHEMA,
        "window": _checked_title(value["window"]),
        "rect": _checked_rect(value["rect"]),
    }


def is_bounded(value):
    """Whether a resolved target names a point, or only a window.

    Reports; never decides. A caller that needs a bounded target asks this
    *after* :func:`resolve_target`, so the question is asked of the canonical
    form rather than of the caller's raw input.
    """
    return (isinstance(value, dict) and value.get("schema") == TARGET_SCHEMA
            and isinstance(value.get("rect"), list))


def describe(value):
    """One-line, human-readable form of a resolved target, for refusals.

    The rectangle is shown because the operator consents to it: a refusal that
    said only "target" would leave the reader guessing which point was meant.
    """
    if is_bounded(value):
        x, y, width, height = value["rect"]
        return (f"{value['window']!r} at [{x}, {y}, {width}, {height}] "
                f"({TARGET_SCHEMA})")
    if isinstance(value, str):
        return f"{value!r} (window only; unbounded)"
    return repr(value)
