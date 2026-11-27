"""Regression checks for verified GW-wide press cards and deduplicated edits."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path
from PIL import Image
from unittest import TestCase, mock

from vortex import matchday_press as press
from vortex.press_sources import evidence
from vortex.publishing_window import is_press_delivery


def clock(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)


class MatchdayPress(TestCase):
    def setUp(self):
        teams = {i: {"name": f"Club {i}", "code": i} for i in range(1, 21)}
        fixtures = [
            dict(event=11, kickoff_time=clock(day, 13).isoformat(), team_h=i,
                 team_a=i+1)
            for i, day in zip(range(1, 20, 2), [21]*7 + [22]*2 + [24])
        ]
        self.snap = SimpleNamespace(teams=teams, fixtures=fixtures, events=[
            dict(id=11, deadline_time=clock(21, 11).isoformat()),
            dict(id=12, deadline_time=clock(27, 19).isoformat()),
        ])
        self.state = {}
        self.schedule = {"2026-11-21": {
            "slots": [["06:30", f"Manager {i}"] for i in range(1, 21)],
            "url": "https://example.org/gameweek-11-team-news",
        }}
        self.sent = []
        self.edited = []
        self.deleted = []
        self.covered = {"Club 1", "Club 2", "Club 3", "Club 4"}

    def fetch(self, club, opponent, now, since):
        if club["name"] in self.covered:
            return dict(
                club=club["name"], news=club["name"] + " confirmed a player is available.",
                title="Press conference ahead of " + opponent["name"],
                quote="", url="https://example.org/" + club["name"].replace(" ", "-"),
                published=now.isoformat(),
            )
        return None

    def send_shared_png(self, path, caption, title, gw, **kwargs):
        assert is_press_delivery()
        assert gw == 11 and len(caption.splitlines()) == 5
        self.sent.append(caption)
        return 101

    def edit_shared_png(self, path, caption, mid, **kwargs):
        assert is_press_delivery() and mid == 101
        self.edited.append(caption)
        return mid

    def delete_shared_message(self, message_id):
        self.deleted.append(message_id)
        return True

    def check(self, now):
        with mock.patch("vortex.telegram_spacing.blocked_until", return_value=None):
            return press.run(
                self.snap, now, lambda _: self.state, lambda *args: None,
                lambda: self, fetch=self.fetch,
                render_image=lambda *args, **kwargs: None,
                schedule_lookup=lambda *args: self.schedule,
            )

    def test_all_clubs_one_gameweek_and_cutoff(self):
        day, = press.matchdays(self.snap, clock(21, 7))
        self.assertEqual(day["gw"], 11)
        self.assertEqual(day["key"], "2026:GW11")
        self.assertEqual(day["date"], "2026-11-21")
        self.assertEqual(len(day["pairs"]), 20)
        self.assertEqual(len(list(press.matchdays(self.snap, clock(21, 11)))), 0)
        self.assertEqual(len(list(press.matchdays(self.snap, clock(15, 9)))), 0)

    @mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "false"})
    def test_hourly_collection_single_send_edit_and_no_duplicate(self):
        self.assertFalse(self.check(clock(21, 5)))
        self.assertFalse(self.check(clock(21, 6)))
        self.assertEqual(self.state["2026:GW11"]["checked"], clock(21, 6).isoformat())
        self.assertTrue(self.check(clock(21, 7)))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("4/20 clubs", self.sent[0])
        self.assertFalse(self.check(clock(21, 7, 20)))
        self.covered.add("Club 5")
        self.assertTrue(self.check(clock(21, 8)))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(self.edited), 1)
        self.assertIn("5/20 clubs", self.edited[0])
        self.assertIn("UPDATED 21 Nov 2026 08:00 UTC", self.edited[0])
        self.assertFalse(self.check(clock(21, 8, 30)))
        self.assertFalse(self.check(clock(21, 11)))
        self.assertEqual(len(self.edited), 1)

    @mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "false"})
    def test_never_publish_one_club_as_a_full_roundup(self):
        self.covered = {"Club 1"}
        self.assertFalse(self.check(clock(21, 7)))
        self.assertEqual(self.sent, [])
        self.assertEqual(len(self.state["2026:GW11"]["facts"]), 1)

    @mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "false"})
    def test_identified_bad_old_post_only_deleted_once(self):
        self.state["11:2026-11-21"] = dict(
            message=521, facts={"8": {"title":
                "Every word from Thomas Frank's first Palace press conference"}}
        )
        self.covered = set()
        self.assertFalse(self.check(clock(21, 7)))
        self.assertEqual(self.deleted, [521])
        self.assertTrue(self.state["11:2026-11-21"]["removed"])
        self.assertFalse(self.check(clock(21, 8)))
        self.assertEqual(self.deleted, [521])

    @mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "false"})
    def test_waits_for_changed_last_conference_with_partial_schedule(self):
        self.schedule["2026-11-21"]["slots"] = [["09:45", "Last manager"]]
        self.assertFalse(self.check(clock(21, 9, 59)))
        self.schedule["2026-11-21"]["slots"] = [["10:15", "Last manager"]]
        self.assertFalse(self.check(clock(21, 10, 14)))
        self.assertFalse(self.check(clock(21, 10, 29)))
        self.assertTrue(self.check(clock(21, 10, 30)))
        self.assertFalse(self.check(clock(21, 11)))
        self.assertEqual(len(self.sent), 1)

    @mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "false"})
    def test_gw11_sources_can_generate_report_without_club_site_results(self):
        self.covered.clear()
        self.schedule = {
            "2026-11-20": {
                "slots": [["14:00", f"Manager {i}"] for i in range(1, 21)],
                "summary": [*(f"Club {i}: First-team player available" for i in range(1, 5)),
                            "Club 5: Coming soon…", "Unrelated Club: Player ready"],
                "url": "https://example.org/gameweek-11-team-news",
            }
        }
        self.assertFalse(self.check(clock(20, 14, 20)))
        self.assertTrue(self.check(clock(20, 14, 31)))
        self.assertIn("4/20 clubs", self.sent[0])
        self.assertFalse(self.check(clock(20, 15)))

    def test_maps_full_club_name_to_official_fpl_short_label(self):
        day = {"pairs": {"1": 2}}
        schedule = {"2026-11-20": {"url": "https://example.org",
                    "summary": ["Tottenham Hotspur: Player cleared to return"]}}
        reports = press._scout_reports(schedule, day, {"1": "Spurs"}, clock(20, 15))
        self.assertEqual(reports["1"]["club"], "Spurs")

    def test_official_pre_match_evidence_and_false_positive_guard(self):
        html = ('<meta property="article:published_time" content="2026-11-20T09:00:00Z">'
                '<h1>Team news before Brentford</h1>'
                '<p>Our manager held his press conference ahead of Brentford.</p>'
                '<p>Smith is available for selection.</p>')
        check = lambda body: evidence(
            body, "https://www.arsenal.com/news/team-news",
            "Arsenal", ["Brentford"], clock(21, 8), clock(18, 8))
        self.assertEqual(check(html)["news"], "Smith is available for selection.")
        self.assertIsNone(check(html.replace("held his", "will host a")))
        self.assertIsNone(check(html.replace("Brentford", "Chelsea")))
        appointment = html.replace(
            "Team news before Brentford",
            "Every word from Thomas Frank's first Palace press conference",
        )
        self.assertIsNone(check(appointment))
        interview = html.replace(
            "Smith is available for selection.",
            "What makes this club a good fit for Thomas Frank?",
        )
        self.assertIsNone(check(interview))

    def test_render_reference_style_locally_without_telegram(self):
        # Exercise actual Pillow layout and bundled VORTEX logo/footer in CI.
        # The synthetic Club N copy is never sent to a live channel.
        from vortex.press_graphic import render as render_press
        day, = press.matchdays(self.snap, clock(21, 8))
        names = {str(i): f"Club {i}" for i in range(1, 21)}
        facts = {
            str(i): self.fetch(self.snap.teams[i], self.snap.teams[i+1],
                               clock(21, 8), clock(20, 8))
            for i in range(1, 5)
        }
        out = Path("output/pr-preview/press-layout-review.png")
        render_press(out, day, names, facts, False, teams=None)
        with Image.open(out) as im:
            self.assertEqual(im.size, (1920, 1080))
            self.assertEqual(im.mode, "RGB")
        self.assertGreater(out.stat().st_size, 10_000)

    def test_source_links_point_to_real_items(self):
        day, = press.matchdays(self.snap, clock(21, 8))
        facts = {"1": self.fetch(self.snap.teams[1], self.snap.teams[2], clock(21, 8), clock(20, 8))}
        names = {str(i): f"Club {i}" for i in range(1, 21)}
        caption, entities = press.caption_for(day, names, facts, clock(21, 8))
        self.assertEqual(len(caption.splitlines()), 5)
        self.assertLess(len(caption), 1024)
        self.assertEqual(len(entities), 1)
        self.assertIn("example.org", entities[0]["url"])
