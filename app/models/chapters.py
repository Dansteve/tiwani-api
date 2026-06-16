"""Life Chapter pydantic schemas (v3): the six fixed chapters + ChapterStatus.

The api contract for the six-chapter dashboard (Product.md section 4.3,
Tasks/4.DashboardChapters.md, HardRules/Api/Modules/Dashboard.md). The set of
Life Chapters is FIXED at six; this module is the single definition of their
codes and display names, and of the ChapterStatus shape the app mirrors exactly.

Named chapters (not chapter) on purpose: the pre-v3 prototype already defines
a class Chapter in app/models/chapter.py (the "going_well / needs_support" model
being replaced). This is the v1 surface, alongside app/routes/chapters.py and
app/services/chapters.py, the way profile sits beside the prototype profile.

Status colour is NOT computed here. The api returns the raw inputs (the chapter
LCI if any, the active alert level if any, the last-prepared timestamp, and the
activity count); the app maps those to grey / green / amber / red per section 4.3.
Keeping the mapping in one place (the app) means the colour rules can change
without an api change, and the api never ships a presentation decision.
"""

from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Literal

# The wire codes for a SURFACED engagement band (a subset of the EngagementBand enum). Only a
# once-active chapter that has gone quiet carries a signal: "not_started" and "active" surface
# nothing (the engagement field is None for them), so the wire only ever sees these two.
EngagementBandCode = Literal["quiet", "resting"]


class Chapter(str, Enum):
    """The six fixed Life Chapters (Product.md section 4.3).

    Declaration order is the stable order the dashboard endpoint returns them in
    (School first, matching the PRD list); the app renders the 2x3 grid in this
    order. The prototype's five-chapter set (missing School) is corrected here:
    School is first-class. The values are the stable codes the app keys on; the
    human labels live in CHAPTER_DISPLAY_NAMES below.
    """

    SCHOOL = "school"
    CAREER = "career"
    FAMILY = "family"
    SOCIAL = "social"
    TRAVEL = "travel"
    CULTURE = "culture"


# Code -> display name. The app shows the display name; the wire still carries the
# code (ChapterStatus.chapter) so the client keys on a stable identifier, never on
# the label text. These are the labels from the PRD section 4.3 chapter list.
CHAPTER_DISPLAY_NAMES: Dict[Chapter, str] = {
    Chapter.SCHOOL: "School",
    Chapter.CAREER: "Career",
    Chapter.FAMILY: "Family Life & Routine",
    Chapter.SOCIAL: "Social & Community",
    Chapter.TRAVEL: "Travel & Holiday",
    Chapter.CULTURE: "Culture & Faith",
}


class EngagementView(BaseModel):
    """The GOVERNED engagement signal for one chapter (the app renders it verbatim).

    Present on ChapterStatus.engagement ONLY when the engagement signal is enabled (the
    Task-12 OFF-by-default flag) AND the chapter is in a SURFACED band (a once-active chapter
    that has gone quiet/resting); it is None otherwise, so the contract is unchanged while the
    signal is gated off. The strings are the api's VERBATIM governed copy (the app authors no
    wording, exactly as it renders alerts): factual about the plan record, never the carer as
    the subject of a failure, with no count / streak / trend.

    Fields:
      band        the surfaced band code ("quiet" or "resting").
      label       the short status word ("Quiet" / "Resting"); never "Dormant" / "Abandoned".
      note        the factual one-line statement about the plan record (the chapter is the
                  subject, never the carer).
      invitation  the warm forward invitation (a door, never a scold).
    """

    band: EngagementBandCode
    label: str
    note: str
    invitation: str


class ChapterStatus(BaseModel):
    """One chapter's dashboard inputs for the current user (cross-repo contract).

    This shape is mirrored exactly by the app (HardRules/App/Modules/Dashboard.md);
    do not change a field name or type without changing it there too. It carries
    only INPUTS, never the status colour: the app maps these to the section 4.3
    bands (grey not-started / green stable / amber under-pressure / red attention).

    Fields:
      chapter           the stable chapter code (serialized as the string value).
      display_name      the human label for the chapter.
      lci               the chapter Life Continuity Index (0 to 100) once at least
                        one pulse exists, else null. Float to match section 4.8's
                        score type; null means "no LCI yet" (a fresh chapter).
      alert_level       the active Erosion Alert level (1, 2, or 3) if one is
                        raised for this chapter, else null. A higher level replaces
                        a lower one upstream (section 4.9), so at most one is active.
      last_prepared_at  the ISO-8601 timestamp of the most recent activity prepared
                        in this chapter, or null if none has been prepared. A string
                        on the wire (the client formats it for display).
      activity_count    how many activities have been prepared in this chapter; 0
                        for a fresh user (the "not started" baseline).
      engagement        the GOVERNED engagement signal for this chapter (the warm
                        "Quiet" / "Resting" copy), present ONLY when the Task-12
                        OFF-by-default engagement flag is on AND the chapter is in a
                        surfaced band; null otherwise. So while the signal is gated
                        off (the default) this field is always null and the contract
                        is unchanged.

    For a fresh user, with no activities, LCI, or alerts yet (the state until
    Tasks 5 to 7 land), every chapter is lci=null, alert_level=null,
    last_prepared_at=null, activity_count=0, engagement=null: the app reads that as
    grey "not started".
    """

    # use_enum_values: serialize chapter as its string code ("school"), not the
    # Enum object, so the JSON contract is the plain code the app keys on.
    model_config = ConfigDict(use_enum_values=True)

    chapter: Chapter
    display_name: str
    lci: Optional[float] = None
    alert_level: Optional[Literal[1, 2, 3]] = None
    last_prepared_at: Optional[str] = None
    activity_count: int = Field(default=0, ge=0)
    engagement: Optional[EngagementView] = None
