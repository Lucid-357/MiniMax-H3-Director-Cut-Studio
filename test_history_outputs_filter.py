"""ComfyUI 0.35.0 lists LoadVideo's INPUT in /history outputs; it must never be taken as a result."""
import unittest

from comfy_submit_worker import _history_outputs


def history_035(input_first=True):
    load = ("12", {"images": [{"filename": "continuity_tail.mp4", "subfolder": "", "type": "input"}], "animated": [True]})
    save = ("40", {"images": [{"filename": "segment_00001_.mp4", "subfolder": "video", "type": "output"}], "animated": [True]})
    order = [load, save] if input_first else [save, load]
    return {"outputs": dict(order)}


class HistoryOutputsFilter(unittest.TestCase):
    def test_input_preview_is_dropped_whatever_its_position(self):
        for input_first in (True, False):
            files = _history_outputs(history_035(input_first))
            self.assertEqual([f["filename"] for f in files], ["segment_00001_.mp4"])
            self.assertEqual(files[0]["type"], "output")

    def test_output_and_temp_entries_are_kept(self):
        item = {"outputs": {
            "7": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]},
            "8": {"images": [{"filename": "p.png", "subfolder": "", "type": "temp"}]},
            "9": {"images": [{"filename": "legacy.png", "subfolder": ""}]},
        }}
        self.assertEqual([f["filename"] for f in _history_outputs(item)], ["a.png", "p.png", "legacy.png"])


if __name__ == "__main__":
    unittest.main()
