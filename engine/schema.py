"""Pydantic models for projects/<slug>/screenplay.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Series(_Model):
    name: str
    slug: Optional[str] = None           # series/<slug>/ holds the bible and continuity notes
    episode: Optional[int] = None
    badge: bool = True                   # series name + episode in the top-left corner
    clock: Optional[str] = None          # in-story clock under the badge, e.g. "18:30" (scenes/shots can change it)
    show_timer: bool = False             # if no clock: running mm:ss timer instead


class Card(_Model):
    """Centered text card over the scene (e.g. a rule, a warning, a fact)."""
    title: Optional[str] = None          # small pill, e.g. "RULE #9"
    text: str
    highlight: list[str] = Field(default_factory=list)
    color: Optional[str] = None          # pill color
    at: float = 0.0                      # seconds after shot start
    y: float = 0.22                      # vertical center (fraction of height)


class PollOption(_Model):
    text: str
    detail: Optional[str] = None         # small line under the option


class Look(_Model):
    skin: str = "#E8DCCB"
    shirt: str = "#3B6EA5"
    pants: str = "#22252E"
    hair: Optional[str] = None
    shoes: Optional[str] = None
    sleeves: Literal["short", "long"] = "short"
    build: float = 1.0                   # torso width multiplier (0.8 slim .. 1.35 wide)
    height: float = 1.0                  # overall size multiplier
    accessories: list[str] = Field(default_factory=list)


class Character(_Model):
    id: str
    label: Optional[str] = None          # speaker tag text, e.g. "DELIVERY GUY"
    voice: Optional[str] = None          # edge-tts voice name
    gender: Optional[Literal["male", "female"]] = None
    look: Look = Field(default_factory=Look)
    library: Optional[str] = None        # reuse library/characters/<name>.json
    rig: Optional[str] = None            # body variant (config/rigs/<name>.yaml); default from style
    tag_color: Optional[str] = None      # speaker tag pill color


class Camera(_Model):
    type: Literal["static", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"] = "static"
    from_: float = Field(1.0, alias="from")   # zoom at shot start (1 = full frame, 2 = close-up)
    to: Optional[float] = None                # zoom at shot end (default = from)
    shake: float = 0.0                   # continuous handheld shake 0..1
    punch: float = 0.0                   # impact shake at shot start, decays (0..1)
    rotate: float = 0.0                  # dutch angle (deg)
    focus_x: float = 0.5                 # world point to look at (fractions), used when no target
    focus_y: float = 0.5
    target: Optional[str] = None         # "<actor>" / "<actor>.<anchor>" / "<prop_id>" (head, chest, hand_r, tip...)
    target_to: Optional[str] = None      # rack to another target during the shot
    frame_y: Optional[float] = None      # where the target lands on screen (fraction of height)
    pan: float = 0.12                    # pan distance for pan_* types (fraction of frame)
    ease: Literal["linear", "in", "out", "inout"] = "inout"


class Actor(_Model):
    id: str
    x: float = 0.5
    y: float = 0.82                      # feet position (fraction of height)
    scale: float = 1.0
    pose: str = "idle"
    expression: str = "neutral"
    facing: Literal["left", "right", "front"] = "front"
    flip: bool = False


class PropPlacement(_Model):
    svg: str
    id: Optional[str] = None             # name for camera targets / light sources (default = svg)
    x: float = 0.5                       # world position of the prop's anchor (fractions)
    y: float = 0.5
    scale: float = 1.0
    rotation: float = 0.0
    flip: bool = False
    opacity: float = 1.0
    params: dict[str, Any] = Field(default_factory=dict)
    attach_to: Optional[str] = None      # "<actor_id>.hand_l" etc. (x/y ignored, dx/dy offset)
    dx: float = 0.0                      # offset in fractions of frame height
    dy: float = 0.0
    layer: Literal["back", "front"] = "front"   # back = behind actors
    anim: Optional[Literal["ring", "bob", "pulse", "swing", "pop", "drop"]] = None


class Light(_Model):
    type: Literal["spot", "cone"] = "spot"
    x: float = 0.5                       # world position (fractions) when no source
    y: float = 0.4
    source: Optional[str] = None         # "<prop_id>.tip", "<actor>.hand_r", ...
    radius: float = 0.35                 # spot radius / cone length (fraction of frame height)
    angle: Optional[float] = None        # cone direction (deg, 0 = right, 90 = down); default from prop
    spread: float = 34.0                 # cone width (deg)
    intensity: float = 1.0
    color: Optional[str] = None          # glow tint
    flicker: float = 0.0


class Lighting(_Model):
    darkness: float = 0.0                # 0 = normal, 0.9 = almost black outside the lights
    color: Optional[str] = None
    lights: list[Light] = Field(default_factory=list)


class Line(_Model):
    speaker: str = "narrator"
    text: str
    highlight: list[str] = Field(default_factory=list)
    voice: Optional[str] = None          # per-line override
    rate: Optional[str] = None           # e.g. "+10%"
    pitch: Optional[str] = None


class SfxCue(_Model):
    name: str                            # built-in generator or library/sfx/<name>.wav
    at: float = 0.0                      # seconds from shot start
    volume: float = 1.0
    params: dict[str, Any] = Field(default_factory=dict)   # generator params, e.g. {"dur": 1.5}


Transition = Literal["cut", "whip", "flash", "fade"]


class Shot(_Model):
    camera: Camera = Field(default_factory=Camera)
    actors: list[Actor] = Field(default_factory=list)
    props: list[PropPlacement] = Field(default_factory=list)
    line: Optional[Line] = None
    duration: Optional[float] = None     # required if no line (else default_shot)
    sfx: list[SfxCue] = Field(default_factory=list)
    auto_sfx: bool = True                # automatic sounds for this shot's transition, card, poll, props
    transition_out: Transition = "cut"
    background: Optional[str] = None     # overrides scene background
    blur: Optional[float] = None         # background blur (depth of field), px
    lighting: Optional[Lighting] = None  # overrides scene lighting
    caption_y: Optional[float] = None    # move captions for this shot (e.g. off a sign or face)
    background_params: dict[str, Any] = Field(default_factory=dict)  # fill {{placeholders}} of an SVG set
    clock: Optional[str] = None          # change the story clock from this shot on
    card: Optional[Card] = None
    poll: list[int] = Field(default_factory=list)  # ending poll options (1-based) shown during this shot
    overlays: bool = True                # False hides badge/clock (full-screen inserts)


class Scene(_Model):
    id: str
    background: str = "plain"
    blur: Optional[float] = None
    lighting: Optional[Lighting] = None
    clock: Optional[str] = None
    background_params: dict[str, Any] = Field(default_factory=dict)
    shots: list[Shot]


class Ending(_Model):
    """End card. poll: 'THE MAJORITY DECIDES / <badge> / <cta>' + numbered options.
    cliffhanger / cta: headline + badge + cta only."""
    type: Literal["poll", "cliffhanger", "cta", "none"] = "none"
    question: Optional[str] = None       # kept for post text / narration
    options: list[Union[str, PollOption]] = Field(default_factory=list)
    headline: Optional[str] = None       # default: "THE MAJORITY DECIDES" for polls
    badge: Optional[str] = None          # big pill, e.g. "DAY 14" / "NEXT EPISODE"
    cta: Optional[str] = None            # e.g. "COMMENT 1 OR 2"
    text: Optional[str] = None
    line: Optional[Line] = None          # narration over the end card
    duration: float = 3.0                # minimum length of the end card

    def option_list(self) -> list[PollOption]:
        return [o if isinstance(o, PollOption) else PollOption(text=o) for o in self.options]


class Music(_Model):
    mood: Optional[str] = None           # tense | mystery | sad | upbeat | comedy | action (config/music.yaml)
    file: Optional[str] = None           # own track (path relative to the project or repo)
    volume: float = 0.15                 # 0.15 = default bed level (style audio.music.bed_db); 0.3 = +6 dB
    enabled: bool = True


class Post(_Model):
    """Text for the social post (English)."""
    caption: str                         # 1-3 short lines, hook + question
    hashtags: list[str] = Field(default_factory=list)


class Screenplay(_Model):
    title: str
    series: Optional[Series] = None
    language: str = "en"
    style_preset: Optional[str] = "miniseries"
    style_overrides: dict[str, Any] = Field(default_factory=dict)
    characters: list[Character] = Field(default_factory=list)
    scenes: list[Scene]
    ending: Ending = Field(default_factory=Ending)
    music: Music = Field(default_factory=Music)
    post: Optional[Post] = None

    @model_validator(mode="after")
    def _check_refs(self) -> "Screenplay":
        ids = {c.id for c in self.characters}
        errors = []
        for sc in self.scenes:
            for i, sh in enumerate(sc.shots):
                where = f"{sc.id}/shot{i + 1}"
                if sh.line and sh.line.speaker != "narrator" and sh.line.speaker not in ids:
                    errors.append(f"{where}: unknown speaker '{sh.line.speaker}'")
                for a in sh.actors:
                    if a.id not in ids:
                        errors.append(f"{where}: unknown actor '{a.id}'")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def character(self, cid: str) -> Optional[Character]:
        return next((c for c in self.characters if c.id == cid), None)


def load_screenplay(path: str | Path) -> Screenplay:
    with open(path, encoding="utf-8") as f:
        return Screenplay.model_validate(json.load(f))
