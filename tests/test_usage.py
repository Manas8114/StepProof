"""Unit tests for the P1 usage meter: aggregates, cached-vs-network accounting,
median/p90 latency, cumulative-over-N totals."""
from stepproof.usage import UsageMeter


def test_summary_counts_network_vs_cached():
    m = UsageMeter()
    m.record("sam-3.1", "sam_video", 40.0, frames_returned=300, billed_frames=100)
    m.record("sam-3.1", "sam_video", 1.0, frames_returned=10, billed_frames=0, cached=True)
    m.record("muse-spark-1.3", "muse_state", 2.0, input_tokens=800, output_tokens=40)
    s = m.summary()
    assert s["sam-3.1"]["requests"] == 1 and s["sam-3.1"]["cached_hits"] == 1
    assert s["sam-3.1"]["billed_frames"] == 100 and s["sam-3.1"]["frames_returned"] == 310
    assert s["muse-spark-1.3"]["input_tokens"] == 800 and s["muse-spark-1.3"]["output_tokens"] == 40
    assert s["total"]["network_requests"] == 2 and s["total"]["billed_frames"] == 100
    assert s["total"]["tokens"] == 840


def test_cumulative_is_totals_across_calls():
    m = UsageMeter()
    for _ in range(3):
        m.record("sam-3.1", "sam_video", 5.0, billed_frames=50)
    c = m.cumulative()
    assert c["calls"] == 3 and c["billed_frames"] == 150 and c["total_tokens"] == 0


def test_latency_median_and_p90():
    m = UsageMeter()
    for v in (1.0, 2.0, 3.0, 4.0, 100.0):
        m.record("x", "k", v, cached=False)
    lat = m.summary()["x"]["latency"]
    assert lat["median_s"] == 3.0
    assert lat["p90_s"] == 100.0      # 90th percentile of 5 sorted values = index 4
    assert m.latency_stats([]) == {"median_s": None, "p90_s": None}


def test_sink_writes_jsonl(tmp_path):
    sink = tmp_path / "usage.jsonl"
    m = UsageMeter(sink=sink)
    m.record("sam-3.1", "sam_video", 1.0, frames_returned=2)
    lines = sink.read_text().strip().splitlines()
    assert len(lines) == 1 and '"cached": false' in lines[0] and '"frames_returned": 2' in lines[0]
