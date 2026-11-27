from datetime import datetime, timedelta, timezone
from unittest import TestCase

from vortex import press_schedule as schedule


class PressScheduleTest(TestCase):
    def test_times_and_correction(self):
        html = """<h2>THURSDAY’S PRESS CONFERENCE TIMES</h2>
        <blockquote><p>Thursday’s FPL Press Conferences<br>🍒 1.30pm – Rose<br>
        🦅 4pm – Frank https://t.co/example</p></blockquote>
        <p>*Frank’s presser has now been moved to 4.30pm</p>"""
        self.assertEqual(schedule.parse_slots(html), [["13:30", "Rose"], ["16:30", "Frank"]])
        self.assertEqual(schedule.parse_slots("<p>2pm – Wrong</p>"), [])

    def test_distinguishes_verified_summary_from_other_competitions(self):
        page = schedule.Article()
        page.feed("""
            <h2>Key Gameweek 12 team news from Thursday</h2>
            <ul><li>Chelsea: <a href="#chelsea">Caicedo cleared</a></li>
                <li>Brentford: Coming soon…</li></ul>
            <h2>Europa League team news</h2><ul><li>Chelsea: Unrelated</li></ul>
        """)
        self.assertEqual(page.summary, ["Chelsea: Caicedo cleared", "Brentford: Coming soon…"])

    def test_reschedules_deduplicates_and_converts_british_summer_time(self):
        deadline = datetime(2027, 5, 23, 13, tzinfo=timezone.utc)
        days = {
            "2027-05-21": {"slots": [["13:00", "Hürzeler"]]},
            "2027-05-22": {"slots": [["15:00", "Hurzeler"]]},
            "2027-05-23": {"slots": [["16:00", "Too Late"]]},
        }
        self.assertEqual(schedule.conference_times(days, deadline),
                         [datetime(2027, 5, 22, 14, tzinfo=timezone.utc)])

    def test_timetable_is_source_only(self):
        self.assertFalse(hasattr(schedule, "retire_graphics"))
        self.assertFalse(hasattr(schedule, "STATE"))
