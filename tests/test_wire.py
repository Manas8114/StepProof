from stepproof.wire import parse_wire

LINE = ("<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334;c=0.96|><|mask;x=0;y=0;c=0.96;data=27,60,!ab|>cd|>,"
        "2<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334;c=0.5|><|mask;x=0;y=0;c=0.5;data=27,48,~xyz|>")


def test_sparse_ids_confidence_and_payload_with_delimiter():
    d = parse_wire(LINE)
    assert [x.obj_id for x in d] == [0, 2]
    assert d[0].box == (211, 228, 270, 254) and d[0].conf == 0.96 and d[0].w == 320
    assert d[0].mask.endswith("ab|>cd")


def test_frames_can_skip_and_be_unordered_and_conf_optional():
    txt = "<5f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|><|mask;x=0;y=0;data=1,1,!a|>\n<2f>1<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|><|mask;x=0;y=0;data=1,1,!a|>"
    d = parse_wire(txt)
    assert [x.frame for x in d] == [5, 2] and d[0].conf is None


def test_zero_matches_is_empty_not_error():
    assert parse_wire("") == [] and parse_wire("   \n") == []
