"""Erosion Alert pydantic schemas (v3): the active-alert response + dismissal.

The cross-repo contract for the alert endpoints (Product.md section 4.9,
HardRules/Api/Modules/Alerts.md). The app mirrors AlertView field-for-field and
renders the api's VERBATIM governed copy (it never authors or paraphrases alert
text); the api is the authoritative schema and the only source of the copy.

  - SignpostView: one community/statutory support resource {label, url?}. url is
    null for a contextual resource (e.g. local carer organisations) the app surfaces
    as guidance rather than a single link. Never a clinical referral (section 4.9).
  - AlertView: one active (non-dismissed) alert as GET /api/v1/alerts returns it:
    {chapter, level, copy, action_label, signposts}. `copy` is the verbatim section
    4.9 prompt with [chapter] resolved; `level` is 1/2/3 (a higher level replaces a
    lower one upstream, so at most one alert is active per chapter).
  - DismissResult: the POST /api/v1/alerts/{chapter}/dismiss response, the dismissed
    alert's chapter + the level that was dismissed.

The stored shape (the DB row) is alert_record (migration 0005): per-chapter active
alert with the level, the trigger condition that fired it, and the dismissed state.
The app's mirror is AlertView (the rendered, copy-carrying view), NOT the raw row.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Literal

from app.models.chapters import Chapter

# The alert level on the wire is the plain 1/2/3 (the AlertLevel IntEnum's value),
# matching ChapterStatus.alert_level and the app's expectation.
AlertLevelCode = Literal[1, 2, 3]


class SignpostView(BaseModel):
    """One community/statutory support resource attached to an alert (section 4.9).

    label is the display text; url is the resource link or null for a contextual
    resource. Both are non-clinical (the engine guards every emitted string).
    """

    label: str
    url: Optional[str] = None


class AlertView(BaseModel):
    """One active Erosion Alert as the app renders it (Product.md section 4.9).

    Mirrored by the app field-for-field. `copy` and `action_label` are the VERBATIM
    governed text (the app never paraphrases); `signposts` are the chapter's
    community/statutory resources. `level` is the active level (1/2/3); a higher level
    replaces a lower one upstream so a chapter has at most one active alert.

    The wire field is `copy` (the app contract). pydantic's BaseModel.copy() is the
    deprecated v1 method, so the model attribute is named `copy_text` with a
    serialization/validation alias of `copy`: the JSON the app sees is
    `{..., "copy": "..."}` while the Python attribute does not shadow BaseModel.copy.
    populate_by_name lets the service construct it with copy_text=...; the response
    serializes the `copy` alias.
    """

    model_config = ConfigDict(use_enum_values=True, populate_by_name=True)

    chapter: Chapter
    level: AlertLevelCode
    copy_text: str = Field(serialization_alias="copy", validation_alias="copy")
    action_label: str
    signposts: List[SignpostView]


class DismissResult(BaseModel):
    """The result of dismissing a chapter's active alert (section 4.9).

    Carries the chapter and the level that was dismissed. A dismissed alert returns
    only if conditions worsen past the next threshold (handled server-side); this is
    just the acknowledgement the app updates its UI from.
    """

    model_config = ConfigDict(use_enum_values=True)

    chapter: Chapter
    dismissed_level: AlertLevelCode
