"""Pydantic models for projects/<slug>/screenplay.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Series(_Model):
    name: str
    episode: Optional[int] = None
    show_timer: bool = False


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


class Camera(_Model):
    type: Literal["static", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"] = "static"
    from_: float = Field(1.0, alias="from")
    to: float = 1.0
    shake: float = 0.0                   # 0..1
    focus_x: float = 0.5
    focus_y: float = 0.5


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
    x: float = 0.5
    y: float = 0.5
    scale: float = 1.0
    rotation: float = 0.0
    params: dict[str, Any] = Field(default_factory=dict)
    attach_to: Optional[str] = None      # "<actor_id>.hand_l" etc.


class Line(_Model):
    speaker: str = "narrator"
    text: str
    highlight: list[str] = Field(default_factory=list)
    voice: Optional[str] = None          # per-line override
    rate: Optional[str] = None           # e.g. "+10%"
    pitch: Optional[str] = None


class SfxCue(_Model):
    name: str
    at: float = 0.0                      # seconds from shot start
    volume: float = 1.0


Transition = Literal["cut", "whip", "flash", "fade"]


class Shot(_Model):
    camera: Camera = Field(default_factory=Camera)
    actors: list[Actor] = Field(default_factory=list)
    props: list[PropPlacement] = Field(default_factory=list)
    line: Optional[Line] = None
    duration: Optional[float] = None     # required if no line (else default_shot)
    sfx: list[SfxCue] = Field(default_factory=list)
    transition_out: Transition = "cut"
    background: Optional[str] = None     # overrides scene background


class Scene(_Model):
    id: str
    background: str = "plain"
    shots: list[Shot]


class Ending(_Model):
    type: Literal["poll", "cliffhanger", "cta", "none"] = "none"
    question: Optional[str] = None
    options: list[str] = Field(default_factory=list)
    text: Optional[str] = None
    duration: float = 3.0


class Music(_Model):
    mood: Optional[str] = None
    file: Optional[str] = None
    volume: float = 0.15


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
