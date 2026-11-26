"""Reader settings: the same values as icbOfficerAssoAPI/app/config.py of the counting system."""

from types import SimpleNamespace

settings = SimpleNamespace(
    OCR_DPI=200,                    # every page is brought to A4 width at this resolution
    BALLOT_COLUMNS=2,               # candidates printed side by side per row
    MARK_THRESHOLD=0.06,            # ink ratio inside a box that counts as "marked"
    FAINT_MARK_THRESHOLD=0.01,      # one connected stroke of this share of the box = faint mark
    LOW_CONFIDENCE_THRESHOLD=0.65,  # below this the ballot is listed for a look by hand
    OUTSIDE_INK_THRESHOLD=0.04,     # ink in the ring around a box: mark crosses the border / is beside the box
    SMUDGE_THRESHOLD=0.55,          # ink ratio inside a box that counts as rubbed / scribbled over
    BALLOT_NUMBER_DIGITS=6,         # ballot paper numbers are shown as 000001 ... 000455
)
