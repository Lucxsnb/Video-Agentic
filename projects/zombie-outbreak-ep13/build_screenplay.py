"""Builds screenplay.json for Zombie Outbreak EP 13 (kept with the project so revisions are easy).

    python projects/zombie-outbreak-ep13/build_screenplay.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent


def A(id, x=0.5, y=0.88, pose="idle", expr="neutral", facing="front", flip=False, scale=1.0):
    return {"id": id, "x": x, "y": y, "pose": pose, "expression": expr, "facing": facing, "flip": flip,
            "scale": scale}


def L(text, speaker="narrator", hl=()):
    return {"speaker": speaker, "text": text, "highlight": list(hl)}


def cam(type="static", z0=1.0, z1=None, target=None, **kw):
    c = {"type": type, "from": z0}
    if z1 is not None:
        c["to"] = z1
    if target:
        c["target"] = target
    c.update(kw)
    return c


def S(line=None, camera=None, actors=(), props=(), **kw):
    s = {"camera": camera or cam(), "actors": list(actors), "props": list(props)}
    if line:
        s["line"] = line
    s.update(kw)
    return s


PHONE_RING = {"svg": "phone_incoming_call", "id": "phone1", "attach_to": "courier.hand_r", "anim": "ring",
              "scale": 1.15, "params": {"name": "Mom", "initial": "M", "avatar": "#D14A8B"}}
PHONE_EAR = {"svg": "phone", "id": "phone1", "attach_to": "clerk.hand_r", "rotation": -12, "scale": 0.95,
             "params": {"screen": "#3CC46A"}}
SIGN_TEXT = "Hi mom, everything is going according to plan. Don't come in."
SIGN_ON_BOX = [{"svg": "cardboard_box", "x": 0.2, "y": 0.9, "layer": "back", "scale": 1.6},
               {"svg": "cardboard_sign", "id": "sign1", "x": 0.2, "y": 0.73, "layer": "back", "rotation": -3,
                "scale": 1.15, "params": {"text": SIGN_TEXT}}]
HAMMER = {"svg": "hammer", "id": "hammer1", "attach_to": "manager.hand_r", "rotation": -25, "scale": 1.15}

# ---------------------------------------------------------------- scene 1: hook
aisle_light = {"darkness": 0.5, "lights": [{"type": "spot", "x": 0.5, "y": 0.1, "radius": 0.75, "flicker": 0.12}]}
hook = [
    S(L("Day thirteen of the outbreak.", hl=["thirteen"]),
      cam(z0=2.0, target="courier.head", punch=0.35), [A("courier", 0.5, pose="nervous", expr="worried")]),
    S(L("The delivery guy is still trapped inside the FreshMart.", hl=["trapped"]),
      cam("zoom_in", 1.0, 1.15), [A("courier", 0.5, pose="idle", expr="tired")]),
    S(L("Thirteen days of canned beans and bad ideas.", hl=["beans"]),
      cam(z0=1.5, target="courier.head", rotate=-3), [A("courier", 0.5, pose="shrug", expr="tired")],
      props=[{"svg": "sack", "x": 0.15, "y": 0.92, "layer": "back", "params": {"label": "BEANS", "color": "#3B6EA5"}},
             {"svg": "sack", "x": 0.85, "y": 0.92, "layer": "back", "params": {"label": "BEANS", "color": "#3B6EA5"}}],
      transition_out="whip"),
]
street = [
    S(L("Outside, the infected never stop walking.", hl=["infected"]),
      cam("zoom_in", 1.05, 1.18, shake=0.15),
      [A("infected_a", 0.3, 0.86, "reach", "zombie", scale=0.95), A("infected_b", 0.7, 0.88, "reach", "zombie")],
      [{"svg": "glass_doors", "x": 0.5, "y": 0.5, "layer": "front"}], sfx=[{"name": "footstep", "at": 0.4, "volume": 0.6}]),
    S(L("And the glass doors are the only thing between them.", hl=["glass"]),
      cam(z0=1.6, target="infected_b.head", punch=0.6),
      [A("infected_a", 0.25, 0.86, "reach", "zombie", scale=0.95), A("infected_b", 0.62, 0.9, "reach", "zombie")],
      [{"svg": "glass_doors", "x": 0.5, "y": 0.5, "layer": "front"}],
      sfx=[{"name": "hit", "at": 0.1, "volume": 0.7}], transition_out="whip"),
]
inside = [
    S(L("Inside, there's Mr. Hollis, the nervous store manager.", hl=["Hollis"]),
      cam(z0=1.7, target="manager.head"), [A("manager", 0.5, pose="nervous", expr="nervous")]),
    S(L("Nina, the clerk in the green cap.", hl=["Nina"]),
      cam(z0=1.7, target="clerk.head"), [A("clerk", 0.5, pose="cross_arms", expr="suspicious")]),
    S(L("Three strangers. And nobody trusts anybody.", hl=["nobody"]),
      cam("zoom_in", 1.0, 1.1), [A("manager", 0.2, 0.86, "cross_arms", "suspicious", facing="right"),
                                 A("courier", 0.5, 0.9, "nervous", "worried"),
                                 A("clerk", 0.8, 0.86, "cross_arms", "suspicious", facing="left")]),
    S(L("And a secret under his sleeve.", hl=["secret"]),
      cam(z0=1.3, target="courier.chest"), [A("courier", 0.5, pose="idle", expr="nervous")]),
    S(L("A bite. Wrapped in a bandage nobody has noticed yet.", hl=["bite"]),
      cam(z0=2.7, target="courier.hand_l", frame_y=0.45, punch=0.5),
      [A("courier", 0.5, pose="idle", expr="nervous")], sfx=[{"name": "heartbeat", "at": 0.2, "volume": 0.9}],
      transition_out="flash"),
    S(L("Last episode, you voted. He answers his phone.", hl=["voted", "answers"]),
      cam("zoom_in", 1.0, 1.12), [A("courier", 0.5, pose="hold", expr="worried")], [PHONE_RING]),
]

# ---------------------------------------------------------------- scene 2: the call
lock = {"time": "21:41", "date": "Friday, October 30", "battery": "6%"}
call = [
    S(L("And it's ringing right now.", hl=["ringing"]), cam("zoom_in", 1.0, 1.06),
      props=[{"svg": "notification", "x": 0.5, "y": 0.42, "anim": "pop", "scale": 1.05,
              "params": {"app": "Phone", "title": "Mom", "text": "Incoming call...", "avatar": "#D14A8B"}}],
      overlays=False, blur=0, background="phone_lockscreen", background_params=lock,
      sfx=[{"name": "ring", "at": 0.0, "volume": 0.5, "params": {"dur": 2.5}}], transition_out="whip"),
    S(L("It's my mom. If I don't pick up, she'll come looking.", "courier", ["mom"]),
      cam(z0=1.8, target="courier.head"), [A("courier", 0.5, pose="hold", expr="scared")], [PHONE_RING]),
    S(L("Then pick up. But not one word about that arm.", "manager", ["arm"]),
      cam(z0=1.8, target="manager.head"), [A("manager", 0.5, pose="point", expr="angry", facing="right")]),
    S(L("If she panics, she calls the army.", "manager", ["army"]),
      cam(z0=1.5, target="manager.head"), [A("manager", 0.5, pose="talk", expr="nervous")]),
    S(L("And the army burns places like this.", "manager", ["burns"]),
      cam(z0=1.9, target="manager.head", punch=0.4), [A("manager", 0.5, pose="talk", expr="scared")]),
    S(L("So what do I tell her?", "courier", ["tell"]),
      cam("zoom_in", 1.0, 1.1), [A("manager", 0.26, pose="cross_arms", expr="worried", facing="right"),
                                 A("courier", 0.74, pose="shrug", expr="nervous", facing="left")], [PHONE_RING]),
    S(L("Mr. Hollis grabs a marker and a piece of cardboard.", hl=["cardboard"]),
      cam("zoom_in", 1.3, 1.5, target="manager.chest"), [A("manager", 0.5, pose="hold_both", expr="determined")],
      [{"svg": "cardboard_sign", "attach_to": "manager.chest", "dy": 0.05, "scale": 1.05, "params": {"text": " "}}]),
    S(L("He writes fast.", hl=["fast"]),
      cam(z0=2.2, target="sign1", frame_y=0.62), [A("manager", 0.5, pose="hold_both", expr="determined")],
      [{"svg": "cardboard_sign", "id": "sign1", "attach_to": "manager.chest", "dy": 0.05, "scale": 1.05,
        "params": {"text": "Hi mom, everything is going"}}], caption_y=0.84,
      sfx=[{"name": "tick", "at": 0.1}, {"name": "tick", "at": 0.3}, {"name": "tick", "at": 0.5}]),
    S(L("But there's a problem.", hl=["problem"]),
      cam(z0=1.8, target="courier.head", punch=0.3), [A("courier", 0.5, pose="nervous", expr="worried")]),
    S(L("His left hand won't stop shaking.", hl=["shaking"]),
      cam(z0=2.6, target="courier.hand_l", frame_y=0.75, shake=0.5), [A("courier", 0.5, pose="nervous", expr="nervous")],
      sfx=[{"name": "heartbeat", "at": 0.0, "volume": 0.8}]),
    S(L("So Nina holds the phone to his ear.", hl=["Nina"]),
      cam(z0=1.5, target="courier.head", frame_y=0.42),
      [A("clerk", 0.07, 0.86, "point", "worried", facing="right"), A("courier", 0.62, 0.92, "idle", "nervous", facing="left")],
      [PHONE_EAR]),
    S(L("Read the sign. Slowly.", "clerk", ["slowly"]),
      cam(z0=1.7, target="clerk.head"), [A("clerk", 0.5, pose="talk", expr="worried", facing="right")],
      transition_out="whip"),
]

# ---------------------------------------------------------------- scene 3: reading the sign
ear_shot = lambda expr, z=1.6, **kw: S(camera=cam(z0=z, target="courier.head", frame_y=0.42, **kw.pop("cam", {})),
                                       actors=[A("clerk", 0.07, 0.86, "point", "worried", facing="right"),
                                               A("courier", 0.62, 0.92, "idle", expr, facing="left")],
                                       props=[PHONE_EAR], **kw)
reading = [
    {**ear_shot("worried"), "line": L("Sweetie? Is that you? You sound strange.", "mom", ["strange"])},
    S(L("Hi mom.", "courier", ["mom"]), cam(z0=1.9, target="sign1"), props=SIGN_ON_BOX, caption_y=0.84),
    {**ear_shot("nervous", 1.9), "line": L("Everything is going according to plan.", "courier", ["plan"])},
    {**ear_shot("worried"), "line": L("What plan? You said you'd be home on Tuesday.", "mom", ["Tuesday"])},
    S(L("Tuesday was nine days ago.", hl=["nine"]),
      cam("zoom_in", 1.0, 1.15), [A("courier", 0.5, pose="idle", expr="sad")], clock="21:43",
      card={"title": "DAY 4", "text": "The day the outbreak reached the city", "highlight": ["outbreak"], "at": 0.3}),
    S(L("Don't come in.", "courier", ["Don't"]), cam(z0=2.4, target="sign1", frame_y=0.4),
      props=SIGN_ON_BOX, caption_y=0.84),
    {**ear_shot("scared", 1.8), "line": L("Don't come in? Don't come in where?", "mom", ["where?"])},
    S(L("He has no idea what to say.", hl=["no", "idea"]),
      cam(z0=2.1, target="courier.head"), [A("courier", 0.5, pose="nervous", expr="nervous")]),
    S(L("And that's when he feels it.", hl=["feels"]),
      cam(z0=2.0, target="courier.head", frame_y=0.45), [A("courier", 0.5, pose="idle", expr="scared")],
      sfx=[{"name": "riser", "at": 0.0, "volume": 0.6, "params": {"dur": 2.0}}]),
    S(L("Something cold, right behind his head.", hl=["behind"]),
      cam(z0=2.3, target="courier.head", frame_y=0.4), [A("courier", 0.5, pose="idle", expr="shock")],
      transition_out="flash"),
]

# ---------------------------------------------------------------- scene 4: the hammer
reveal_actors = [A("manager", 0.56, 0.83, "hold_up", "suspicious", facing="left"),
                 A("courier", 0.48, 0.93, "idle", "scared", facing="right"),
                 A("clerk", 0.86, 0.88, "nervous", "shock", facing="left")]
hammer = [
    S(L("Mr. Hollis is holding a hammer. Raised. Just in case.", hl=["hammer"]),
      cam("zoom_out", 1.35, 1.0, target="hammer1", target_to="courier.head", punch=0.7),
      reveal_actors, [HAMMER] + SIGN_ON_BOX, caption_y=0.84),
    S(L("Just in case.", "manager", ["case"]),
      cam(z0=2.0, target="manager.head"), [A("manager", 0.5, pose="hold_up", expr="suspicious", facing="left")],
      [HAMMER]),
    S(L("Put that down! He's not sick!", "clerk", ["down!"]),
      cam(z0=1.8, target="clerk.head"), [A("clerk", 0.5, pose="point", expr="angry", facing="left", flip=True)]),
    S(L("Then why is his bandage bleeding again?", "manager", ["bleeding"]),
      cam(z0=1.8, target="manager.head", punch=0.3), [A("manager", 0.5, pose="hold_up", expr="angry", facing="left")],
      [HAMMER]),
    S(L("It's a scratch! I told you, it's just a scratch!", "courier", ["scratch!"]),
      cam(z0=1.9, target="courier.head", shake=0.3), [A("courier", 0.5, pose="shock", expr="shock")]),
    {**ear_shot("scared", 1.7), "line": L("Who's there with you? I'm coming over right now.", "mom", ["coming"])},
    S(L("No! Mom, don't!", "courier", ["don't!"]),
      cam(z0=2.2, target="courier.head", punch=0.8), [A("courier", 0.5, pose="shock", expr="shock")]),
    # action burst
    S(None, cam(z0=2.4, target="hammer1", frame_y=0.3, shake=0.6), [A("manager", 0.5, pose="hit", expr="angry")], [HAMMER],
      duration=0.6, sfx=[{"name": "whoosh", "at": 0.05}]),
    S(None, cam(z0=2.4, target="courier.head", punch=0.9), [A("courier", 0.5, pose="shock", expr="scared")],
      duration=0.5),
    S(None, cam(z0=2.0, target="clerk.head", shake=0.5), [A("clerk", 0.5, pose="shock", expr="shock")],
      duration=0.5),
    S(None, cam(z0=1.7, focus_y=0.78, shake=0.4), props=[{"svg": "phone", "x": 0.5, "y": 0.8, "rotation": 70, "scale": 1.6,
                                            "anim": "drop", "params": {"screen": "#3CC46A"}}] + SIGN_ON_BOX,
      duration=0.8, sfx=[{"name": "hit", "at": 0.25, "volume": 0.5}], transition_out="fade"),
]

# ---------------------------------------------------------------- scene 5: cold storage
cold_light = {"darkness": 0.6, "lights": [{"type": "spot", "x": 0.5, "y": 0.3, "radius": 0.5, "color": "#9FD0FF",
                                           "intensity": 0.6, "flicker": 0.2}]}
cold = [
    S(L("Then, from the back of the store…", hl=["back"]), cam("zoom_in", 1.0, 1.2), clock="21:47",
      sfx=[{"name": "door_slam", "at": 1.6, "volume": 0.9}]),
    S(L("Three slow knocks.", hl=["Three"]), cam(z0=1.6, focus_x=0.5, focus_y=0.5, shake=0.3),
      sfx=[{"name": "door_slam", "at": 0.0}, {"name": "door_slam", "at": 0.7}, {"name": "door_slam", "at": 1.4}]),
    S(L("From inside the cold storage room.", hl=["cold", "storage"]), cam("zoom_in", 1.2, 1.5, focus_y=0.42)),
    S(L("That room has been locked since day one.", "clerk", ["locked"]),
      cam(z0=1.8, target="clerk.head"), [A("clerk", 0.5, pose="nervous", expr="scared")]),
    S(L("Nobody went in there. Nobody.", "manager", ["Nobody."]),
      cam(z0=1.8, target="manager.head"), [A("manager", 0.5, pose="hold_up", expr="scared")], [HAMMER]),
    S(L("On the floor, the phone is still on.", hl=["phone"]),
      cam(z0=2.0, focus_y=0.84), props=[{"svg": "phone", "id": "phone2", "x": 0.5, "y": 0.84, "rotation": 70,
                                          "scale": 1.6, "params": {"screen": "#3CC46A"}}]),
    S(L("Honey? I heard knocking. Where are you?", "mom", ["knocking"]),
      cam(z0=2.4, target="phone2", frame_y=0.45), props=[{"svg": "phone", "id": "phone2", "x": 0.5, "y": 0.84,
                                                          "rotation": 70, "scale": 1.6, "params": {"screen": "#3CC46A"}}]),
    S(L("The knocking starts again.", hl=["again"]), cam(z0=1.4, shake=0.4),
      sfx=[{"name": "door_slam", "at": 0.1}, {"name": "door_slam", "at": 0.6}, {"name": "door_slam", "at": 1.1}]),
    S(L("Same rhythm as his heartbeat.", hl=["heartbeat"]),
      cam(z0=2.6, target="courier.hand_l", frame_y=0.45), [A("courier", 0.5, pose="idle", expr="scared")],
      sfx=[{"name": "heartbeat", "at": 0.0}, {"name": "heartbeat", "at": 0.9}]),
    S(L("Rule number one. We never open that door.", "clerk", ["never"]),
      cam(z0=1.6, target="clerk.head", frame_y=0.5), [A("clerk", 0.5, pose="cross_arms", expr="determined")],
      card={"title": "RULE #1", "text": "Never open the cold storage", "highlight": ["never"], "at": 0.4}),
    S(L("What if someone's alive in there?", "courier", ["alive"]),
      cam(z0=1.9, target="courier.head"), [A("courier", 0.5, pose="talk", expr="worried")]),
    S(L("What if they're not?", "manager", ["not?"]),
      cam(z0=2.1, target="manager.head", punch=0.5), [A("manager", 0.5, pose="hold_up", expr="suspicious")],
      [HAMMER], transition_out="whip"),
]

# ---------------------------------------------------------------- poll
two = [A("courier", 0.28, 0.88, "nervous", "worried", facing="right"),
       A("manager", 0.74, 0.86, "hold_up", "suspicious", facing="left")]
poll = [
    S(L("So, should they open the cold storage room?", hl=["open"]), cam("zoom_in", 1.0, 1.2, focus_y=0.42)),
    S(L("Option one: they open it and find out who's knocking.", hl=["one"]),
      cam("zoom_in", 1.0, 1.1), two, [HAMMER], poll=[1]),
    S(L("Option two: it stays locked, no matter what they hear.", hl=["two"]),
      cam("zoom_in", 1.1, 1.2), two, [HAMMER], poll=[1, 2]),
    S(L("And remember: his mom is already on her way.", hl=["mom"]),
      cam(z0=1.0), props=[{"svg": "glass_doors", "x": 0.5, "y": 0.5, "layer": "front"}],
      actors=[A("infected_a", 0.3, 0.86, "reach", "zombie", scale=0.95), A("infected_b", 0.7, 0.88, "reach", "zombie")],
      background="street_night", blur=3, poll=[1, 2]),
]

sp = {
    "title": "Locked in the FreshMart",
    "series": {"name": "Zombie Outbreak", "slug": "zombie-outbreak", "episode": 13, "clock": "21:40"},
    "style_preset": "dark_miniseries",
    "style_overrides": {"timing": {"target_duration": [170, 180]}},
    "characters": [{"id": n, "library": f"zombie-outbreak/{n}"}
                   for n in ("courier", "manager", "clerk", "mom", "infected_a", "infected_b")],
    "scenes": [
        {"id": "s1_hook", "background": "supermarket_aisle", "lighting": aisle_light, "shots": hook},
        {"id": "s2_street", "background": "street_night", "blur": 3, "shots": street},
        {"id": "s3_inside", "background": "supermarket_aisle", "lighting": aisle_light, "shots": inside},
        {"id": "s4_call", "background": "supermarket_aisle", "lighting": aisle_light, "shots": call},
        {"id": "s5_sign", "background": "supermarket_aisle", "lighting": aisle_light, "shots": reading},
        {"id": "s6_hammer", "background": "storage_room", "lighting": {"darkness": 0.45, "lights": [
            {"type": "spot", "x": 0.5, "y": 0.1, "radius": 0.8}]}, "shots": hammer},
        {"id": "s7_cold", "background": "cold_storage", "lighting": cold_light, "shots": cold},
        {"id": "s8_poll", "background": "cold_storage", "lighting": cold_light, "shots": poll},
    ],
    "ending": {"type": "poll", "question": "Should they open the cold storage room?", "badge": "Day 14",
               "cta": "Comment 1 or 2",
               "options": [{"text": "Open it", "detail": "find out who's knocking"},
                           {"text": "Keep it locked", "detail": "no matter what they hear"}],
               "line": {"speaker": "narrator", "text": "Day fourteen is up to you.",
                        "highlight": ["you."]}, "duration": 3.5},
    "music": {"mood": "tense", "volume": 0.15},
    "post": {"caption": "Day 13: his mom is on the phone, a hammer is behind his head… and something is knocking "
                        "from inside the cold storage. 🧟\nShould they open it? Comment 1 or 2 👇",
             "hashtags": ["zombie", "zombieoutbreak", "animation", "miniseries", "storytime", "horror", "fyp",
                          "shorts"]},
}

(HERE / "screenplay.json").write_text(json.dumps(sp, indent=1, ensure_ascii=False), encoding="utf-8")
print("shots:", sum(len(s["shots"]) for s in sp["scenes"]),
      "words:", sum(len(sh["line"]["text"].split()) for s in sp["scenes"] for sh in s["shots"] if "line" in sh))
