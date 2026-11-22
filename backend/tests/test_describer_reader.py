from app import describer, reader


def det(label, side, x1, y1, x2, y2):
    return {"label": label, "conf": 0.9, "box": (x1, y1, x2, y2), "side": side}


DETS = [
    det("person", "left", 0, 0, 100, 300),
    det("chair", "center", 250, 100, 450, 400),
    det("door", "right", 500, 0, 640, 480),
    det("cup", "center", 300, 300, 320, 320),
]


def test_describe_top_three_by_size_with_position():
    assert describer.describe("all", DETS, light=600) == (
        "A door on the right, a chair in the centre, a person on the left.")


def test_describe_focus_only_that_side():
    assert describer.describe("left", DETS, light=600) == "A person on the left."
    assert describer.describe("right", DETS, light=600) == "A door on the right."


def test_describe_focus_names_side_once():
    dets = [det("chair", "left", 0, 0, 60, 120), det("chair", "left", 70, 0, 130, 110),
            det("couch", "left", 0, 130, 100, 200), det("bottle", "left", 140, 0, 150, 30)]
    assert describer.describe("left", dets, light=600) == (
        "Two chairs, a couch and a bottle on the left.")


def test_describe_groups_duplicates():
    dets = [det("person", "left", 0, 0, 50, 100), det("person", "left", 60, 0, 110, 100)]
    assert describer.describe("all", dets, light=600) == "Two people on the left."


def test_describe_empty_and_dark():
    assert describer.describe("all", [], light=600) == "I don't see any objects I recognise."
    assert describer.describe("left", DETS[1:], light=600) == "I don't see anything I recognise on the left."
    # Dark only matters when nothing is recognised.
    assert describer.describe("all", [], light=20) == "Too dark to describe."
    assert describer.describe("all", DETS, light=20).startswith("A ")


def test_describe_unknown_light_still_describes():
    assert describer.describe("right", DETS, light=None).startswith("A door")


def box(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def test_order_lines_biggest_first_then_top_to_bottom():
    results = [
        (box(10, 10, 200, 30), "Take with food", 0.9),
        (box(10, 50, 120, 130), "ASPIRIN", 0.95),
        (box(130, 60, 260, 125), "500mg", 0.9),
        (box(10, 150, 220, 170), "Keep out of reach", 0.8),
        (box(10, 180, 100, 190), "noise", 0.1),
    ]
    assert reader.order_lines(results) == ["ASPIRIN 500mg", "Take with food", "Keep out of reach"]


def test_read_text_no_text(monkeypatch):
    class Empty:
        def readtext(self, _frame):
            return []

    monkeypatch.setattr(reader, "_get_reader", lambda: Empty())
    assert reader.read_text(frame=object()) == reader.NO_TEXT


def test_read_text_joins_lines(monkeypatch):
    class Fake:
        def readtext(self, _frame):
            return [(box(0, 0, 100, 40), "EXIT", 0.9), (box(0, 50, 100, 60), "Door 3", 0.9)]

    monkeypatch.setattr(reader, "_get_reader", lambda: Fake())
    assert reader.read_text(frame=object()) == "EXIT. Door 3"
