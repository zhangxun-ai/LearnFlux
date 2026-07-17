import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = REPO_ROOT / "src" / "web" / "static"
RUNTIME_JS = STATIC_ROOT / "js" / "study-player-runtime.js"
STUDY_HTML = STATIC_ROOT / "study.html"


def _run_node(script: str) -> dict:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_player_runtime_toggles_play_and_pause():
    result = _run_node(
        f"""
        const runtime = require({json.dumps(str(RUNTIME_JS))});
        (async () => {{
          const events = [];
          const media = {{
            paused: true,
            async play() {{ events.push('play'); this.paused = false; }},
            pause() {{ events.push('pause'); this.paused = true; }}
          }};
          await runtime.togglePlayback(media);
          const afterPlay = media.paused;
          await runtime.togglePlayback(media);
          console.log(JSON.stringify({{ events, afterPlay, afterPause: media.paused }}));
        }})().catch((error) => {{ console.error(error); process.exit(1); }});
        """
    )

    assert result == {
        "events": ["play", "pause"],
        "afterPlay": False,
        "afterPause": True,
    }


def test_player_runtime_estimates_weighted_timeline_and_active_line():
    result = _run_node(
        f"""
        const runtime = require({json.dumps(str(RUNTIME_JS))});
        const timeline = runtime.estimateTimeline([
          {{ id: 'short', text: '短句' }},
          {{ id: 'long', text: '这是一句明显更长的文稿内容' }}
        ], 60);
        const active = runtime.activeLineAt(timeline, 30);
        console.log(JSON.stringify({{ timeline, activeId: active && active.id }}));
        """
    )

    assert result["timeline"][0]["start_seconds"] == 0
    assert result["timeline"][-1]["end_seconds"] == 60
    assert result["timeline"][1]["end_seconds"] - result["timeline"][1]["start_seconds"] > (
        result["timeline"][0]["end_seconds"]
        - result["timeline"][0]["start_seconds"]
    )
    assert result["activeId"] == "long"


def test_player_runtime_previews_and_commits_progress_seek():
    result = _run_node(
        f"""
        const runtime = require({json.dumps(str(RUNTIME_JS))});
        (async () => {{
          const events = [];
          const media = {{
            duration: 200,
            currentTime: 10,
            paused: true,
            async play() {{ events.push('play'); this.paused = false; }}
          }};
          const previewSeconds = runtime.progressSeconds(25, media.duration);
          const committedSeconds = await runtime.seekFromProgress(media, 25);
          console.log(JSON.stringify({{
            previewSeconds,
            committedSeconds,
            currentTime: media.currentTime,
            paused: media.paused,
            events
          }}));
        }})().catch((error) => {{ console.error(error); process.exit(1); }});
        """
    )

    assert result == {
        "previewSeconds": 50,
        "committedSeconds": 50,
        "currentTime": 50,
        "paused": False,
        "events": ["play"],
    }


def test_player_runtime_clamps_progress_before_seeking():
    result = _run_node(
        f"""
        const runtime = require({json.dumps(str(RUNTIME_JS))});
        console.log(JSON.stringify({{
          beforeStart: runtime.progressSeconds(-10, 80),
          afterEnd: runtime.progressSeconds(120, 80),
          unavailable: runtime.progressSeconds(50, 0)
        }}));
        """
    )

    assert result == {
        "beforeStart": 0,
        "afterEnd": 80,
        "unavailable": 0,
    }


def test_player_runtime_applies_bounded_playback_rate():
    result = _run_node(
        f"""
        const runtime = require({json.dumps(str(RUNTIME_JS))});
        const media = {{ playbackRate: 1, defaultPlaybackRate: 1 }};
        const selected = runtime.setPlaybackRate(media, 1.5);
        const bounded = runtime.setPlaybackRate(media, 4);
        console.log(JSON.stringify({{
          selected,
          bounded,
          playbackRate: media.playbackRate,
          defaultPlaybackRate: media.defaultPlaybackRate
        }}));
        """
    )

    assert result == {
        "selected": 1.5,
        "bounded": 2,
        "playbackRate": 2,
        "defaultPlaybackRate": 2,
    }


def test_study_player_keeps_controls_before_media_and_exposes_follow_toggle():
    html = STUDY_HTML.read_text(encoding="utf-8")

    assert html.index('id="study-play-strip"') < html.index('id="video-frame"')
    assert 'id="transcript-follow"' in html
    assert 'id="video-progress" type="range"' in html
    assert 'id="playback-rate"' in html
    assert 'id="ai-overview-expand"' in html
    assert 'id="ai-reading-dialog"' in html
    assert 'id="ai-reading-content"' in html
    assert '/static/js/study-player-runtime.js?v=__ASSET_VERSION__' in html
