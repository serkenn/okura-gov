from stubs import StubFetcher, resp

from okura_monitor import pages

URL = "https://www.nta.go.jp/information/news/index.htm"
SOFT404 = ("指定されたページを表示できませんでした",)


def _html(*items, title="新着情報"):
    lis = "".join(f"<li>{i}</li>" for i in items)
    return f"<html><head><title>{title}</title><script>var t=1;</script></head><body><ul>{lis}</ul></body></html>".encode("utf-8")


def test_extract_lines_keeps_img_alt_and_drops_script():
    lines = pages.extract_lines('<p>医療費を<img alt="ほてん" src="/hoten.gif">する保険金等</p><script>x()</script>'
                                '<p><img src="a.png" alt="別ウィンドウが開きます">PDF</p>')
    assert lines == ["医療費を⟨ほてん⟩する保険金等", "PDF"]


def test_first_run_is_baseline_then_conditional_get_304():
    f = StubFetcher({URL: lambda h: resp(304) if h.get("If-None-Match") == '"v1"' else
                     resp(200, _html("令和8年11月6日 a"), ETag='"v1"', Last_Modified="Fri, 06 Nov 2026 01:00:00 GMT",
                          Content_Type="text/html; charset=UTF-8")})
    check, state = pages.check_page(f, URL, "nta_news", None, SOFT404)
    assert check.status == "baseline" and state["etag"] == '"v1"'
    check2, state2 = pages.check_page(f, URL, "nta_news", state, SOFT404)
    assert f.calls[-1][1] == {"If-None-Match": '"v1"', "If-Modified-Since": "Fri, 06 Nov 2026 01:00:00 GMT"}
    assert check2.status == "not_modified" and state2 is None


def test_200_with_same_text_is_unchanged():
    # Last-Modified だけが変わる一斉更新（R3 実測 §2-2）
    _, state = pages.evaluate_response(resp(200, _html("a"), ETag='"v1"'), "t", None)
    check, new_state = pages.evaluate_response(resp(200, _html("a"), ETag='"v2"'), "t", state)
    assert check.status == "unchanged" and new_state["etag"] == '"v2"'


def test_changed_text_reports_added_and_removed_lines():
    _, state = pages.evaluate_response(resp(200, _html("令和8年11月6日 古い", "共通")), "t", None)
    check, _ = pages.evaluate_response(resp(200, _html("令和8年11月12日 年末調整の改正", "共通")), "t", state)
    assert check.status == "changed"
    assert check.added == ["令和8年11月12日 年末調整の改正"] and check.removed == ["令和8年11月6日 古い"]
    assert pages.matching_lines(check.added, ("年末調整",)) == check.added


def test_soft_404_after_baseline_is_missing():
    _, state = pages.evaluate_response(resp(200, _html("a")), "t", None)
    check, new_state = pages.evaluate_response(resp(200, _html("x", title="指定されたページを表示できませんでした")), "t", state, SOFT404)
    assert check.status == "missing" and new_state["missing"] is True
    again, _ = pages.evaluate_response(resp(200, _html("x", title="指定されたページを表示できませんでした")), "t", new_state, SOFT404)
    assert again.status == "error"  # 2回目からは issue にしない


def test_shift_jis_page_is_decoded():
    body = '<html><head><meta charset="Shift_JIS"><title>源泉</title></head><body><p>扶養控除</p></body></html>'.encode("cp932")
    _, state = pages.evaluate_response(resp(200, body), "t", None)
    assert state["title"] == "源泉" and "扶養控除" in state["lines"]
