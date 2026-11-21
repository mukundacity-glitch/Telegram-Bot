from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, mock

from vortex import press_schedule as schedule


class PressScheduleTest(TestCase):
    def test_times_and_correction(self):
        html = """<h2>THURSDAY’S PRESS CONFERENCE TIMES</h2>
        <blockquote><p>Thursday’s FPL Press Conferences<br>🍒 1.30pm – Rose<br>
        🦅 4pm – Frank https://t.co/example</p></blockquote>
        <p>*Frank’s presser has now been moved to 4.30pm</p>"""
        self.assertEqual(schedule.parse_slots(html), [["13:30", "Rose"], ["16:30", "Frank"]])
        self.assertEqual(schedule.parse_slots("<p>2pm – Wrong</p>"), [])

    def test_final_gameweek_send_edit_repeat_and_cutoff(self):
        deadline = datetime(2027,5,23,13,tzinfo=timezone.utc)
        snapshot = SimpleNamespace(events=[dict(id=38,deadline_time=deadline.isoformat())])
        client = mock.Mock()
        client.send_shared_png.return_value = client.edit_shared_png.return_value = 123
        state = {}
        fetch = mock.Mock(return_value={"2027-05-21": {"slots":[["13:00","Example"]],"url":"https://example.org"}})
        def check(now):
            return schedule.run(snapshot, now, lambda _:state, lambda *_:None, lambda:client, lookup=fetch)
        with TemporaryDirectory() as tmp, mock.patch.object(schedule,"ROOT",Path(tmp)), mock.patch.object(schedule,"render"), mock.patch.dict("os.environ",{"GITHUB_ACTIONS":"false"}):
            now = deadline-timedelta(days=1)
            self.assertTrue(check(now))
            self.assertFalse(check(now+timedelta(minutes=31)))
            fetch.return_value = {"2027-05-21":{"slots":[["15:00","Example"]],"url":"https://example.org"}}
            self.assertTrue(check(now+timedelta(hours=1,minutes=2)))
            self.assertFalse(check(deadline))
            client.send_shared_png.assert_called_once()
            client.edit_shared_png.assert_called_once()
            self.assertEqual(client.edit_shared_png.call_args.args[2],123)
