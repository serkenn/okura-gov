import datetime as dt
import io
import json
import zipfile

from stubs import StubFetcher, resp

from okura_monitor import egov

HEADER = "法令種別,法令番号,法令名,法令名読み,旧法令名,公布日,改正法令名,改正法令番号,改正法令公布日,施行日,施行日備考,法令ID,本文URL,未施行\n"
ROWS = (
    "法律,昭和三十二年法律第二十六号,租税特別措置法,そぜいとくべつそちほう,,昭和三十二年三月三十一日,所得税法等の一部を改正する法律,"
    "令和七年法律第十三号,令和七年三月三十一日,令和八年十一月一日,,332AC0000000026,"
    "https://laws.e-gov.go.jp/law/332AC0000000026/20261101_507AC0000000013,\n"
    "法律,昭和六十三年法律第百八号,消費税法,しょうひぜいほう,,昭和六十三年十二月三十日,所得税法等の一部を改正する法律,"
    "令和七年法律第十三号,令和七年三月三十一日,令和九十九年十二月三十一日,"
    "\"医療法等の一部を改正する法律（令和七年法律第　　　号）附則第一条第五号に掲げる規定の施行の日, 仮\",363AC0000000108,"
    "https://laws.e-gov.go.jp/law/363AC0000000108/21171231_507AC0000000013,○\n"
)


def test_parse_bulk_csv_bom_quotes_and_provisional_date():
    rows = egov.parse_bulk_csv(("﻿" + HEADER + ROWS).encode("utf-8"))
    assert [r.law_id for r in rows] == ["332AC0000000026", "363AC0000000108"]
    assert rows[0].enforcement_date == "2026-11-01" and not rows[0].enforcement_provisional and not rows[0].unenforced
    r = rows[1]
    assert r.enforcement_date is None and r.enforcement_provisional and r.unenforced
    assert r.enforcement_raw == "令和九十九年十二月三十一日"
    assert r.enforcement_note.endswith("施行の日, 仮")  # 引用符の中のカンマで列がずれない


def test_parse_bulk_csv_rejects_unknown_columns():
    try:
        egov.parse_bulk_csv("a,b\n1,2\n".encode("utf-8"))
    except ValueError as e:
        assert "列がない" in str(e)
    else:
        raise AssertionError("ValueError にならない")


def _zip(csv_bytes):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("R081101.csv", csv_bytes)
        z.writestr("332AC0000000026_20261101_507AC0000000013/x.xml", b"<Law/>")
    return buf.getvalue()


def test_fetch_bulk_day_reads_csv_from_zip_and_treats_500_as_no_data():
    day = dt.date(2026, 11, 1)
    url = egov.EGOV_BULK_UPDATED.format(yyyymmdd="20261101")
    ok = egov.fetch_bulk_day(StubFetcher({url: resp(200, _zip((HEADER + ROWS).encode("utf-8-sig")))}), day)
    assert ok.status == "ok" and ok.csv_name == "R081101.csv" and len(ok.rows) == 2
    sunday = egov.fetch_bulk_day(StubFetcher({url: resp(500, b"<html>error</html>")}), day)
    assert sunday.status == "no_data" and sunday.http_status == 500


def test_bulk_dates_to_check():
    today = dt.date(2026, 11, 12)
    assert egov.bulk_dates_to_check(None, today, 7) == []  # 初回は基準の記録だけ
    days = egov.bulk_dates_to_check({"cursor": "2026-11-09"}, today, 7)
    assert days == [dt.date(2026, 11, 10), dt.date(2026, 11, 11)]  # 今日の分は翌日に
    assert len(egov.bulk_dates_to_check({"cursor": "2026-10-01"}, today, 7)) == 7


REV = {
    "law_title": "所得税法", "amendment_law_num": "令和八年法律第十二号", "amendment_law_title": "所得税法等の一部を改正する法律",
    "amendment_promulgate_date": "2026-03-31", "amendment_enforcement_date": "2026-12-01",
    "amendment_scheduled_enforcement_date": None, "amendment_enforcement_comment": None, "repeal_status": "None",
    "mission": "Partial", "amendment_type": "3", "current_revision_status": "UnEnforced", "updated": "2026-09-08T11:20:43+09:00",
}


def test_diff_revisions_new_changed_touched():
    a, b, c = "340AC0000000033_20261201_508AC0000000012", "340AC0000000033_20270101_508AC0000000012", "340AC0000000033_20280101_508AC0000000012"
    old = {a: dict(REV), b: dict(REV)}
    new = {
        a: dict(REV, updated="2026-11-11T03:00:00+09:00"),  # updated だけ（隣の版の更新で同時に変わる：実測 §3）
        b: dict(REV, amendment_enforcement_date="2027-04-01", updated="2026-11-11T03:00:00+09:00"),
        c: dict(REV, amendment_enforcement_date="2028-01-01"),
    }
    kinds = {e.revision_id: e.kind for e in egov.diff_revisions(old, new, "340AC0000000033")}
    assert kinds == {a: "touched", b: "changed", c: "new"}
    # 施行日の到来で状態だけが変わったものは issue にしない
    assert egov.diff_revisions(old, {a: dict(REV, current_revision_status="CurrentEnforced")}, "x") == []


def test_check_law_baseline_then_updated_from():
    law = "340AC0000000033"
    body = json.dumps({"law_info": {"law_id": law}, "revisions": [dict(REV, law_revision_id=f"{law}_20261201_508AC0000000012")]}).encode()
    f = StubFetcher({egov.revisions_url(law): resp(200, body),
                     egov.revisions_url(law, "2026-11-10"): resp(200, json.dumps({"revisions": []}).encode())})
    check, state = egov.check_law(f, law, None, dt.date(2026, 11, 11))
    assert check.status == "baseline" and check.events == [] and state["checked_on"] == "2026-11-11"
    check2, state2 = egov.check_law(f, law, state, dt.date(2026, 11, 12))
    assert f.calls[-1][0].endswith("?updated_from=2026-11-10")  # 前回の確認日の前日から
    assert check2.status == "checked" and check2.events == [] and len(state2["revisions"]) == 1


def test_check_law_error_keeps_state():
    law = "340AC0000000033"
    check, state = egov.check_law(StubFetcher({egov.revisions_url(law): resp(503)}), law, None, dt.date(2026, 11, 12))
    assert check.status == "error" and state is None
