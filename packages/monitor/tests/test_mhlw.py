from okura_monitor import mhlw
from okura_monitor.targets import MHLW_NOTICES

BASE = "https://www.mhlw.go.jp/hourei/new/tsuchi/newindex.html"
# 2026-11-12 に取得したページの形を縮めたもの（通知名は架空）
PAGE = """
<A name=tu_10>
<span style="font-size: large">
<B>保険局 新着の通知</B>
</span>
</A>
<PRE><span style="font-size: large"><B>令和８年１１月２日掲載</b></font></pre>
<br>
<UL>
<LI style="list-style-type: circle">
<A HREF="../../doc/tsuchi/T261102S0050.pdf" target="shinchaku">医療機器の保険適用について（令和８年10月30日保医発1030第２号）(PDF,388KB)</A>
<img src="../../ico_blank.png" title="別ウィンドウが開きます" alt="別ウィンドウが開きます">【保険局医療課　健康保険法関係】
<BR>
</LI>
</UL>
<UL>
<LI style="list-style-type: circle">
<A HREF="../../doc/tsuchi/T261102S0060.pdf" target="shinchaku">被扶養者の認定の取扱いについて（令和８年10月30日保保発1030第１号)(PDF,100KB)</A>
<img src="../../ico_blank.png" alt="別ウィンドウが開きます">【保険局保険課　健康保険法関係】
<BR><DIR>
<LI style="list-style-type:disc;">
<A HREF="../../doc/tsuchi/T261102S0061.pdf" target="shinchaku">新旧対照表(PDF,55KB)</A>
</DIR>
</LI>
</UL>
<A name=tu_4>
<B>医薬局 新着の通知</B>
<PRE><span style="font-size: large"><B>令和８年１１月１１日掲載</b></font></pre>
<UL>
<LI style="list-style-type: circle">
<A HREF="../../doc/tsuchi/T261111T0010.pdf" target="shinchaku">ある省令の施行について（令和８年11月10日医薬発1110第１号）(PDF,10KB)</A>
【医薬局総務課　医薬品医療機器等法関係】
</LI>
</UL>
"""


def test_parse_new_notices():
    items = mhlw.parse_new_notices(PAGE, BASE)
    assert [n.department for n in items] == ["保険局", "保険局", "医薬局"]
    n = items[1]
    assert n.url == "https://www.mhlw.go.jp/hourei/doc/tsuchi/T261102S0060.pdf"
    assert n.posted == "2026-11-02" and n.issued == "2026-10-30" and n.number == "保保発1030第１号"
    assert n.section == "保険局保険課 健康保険法関係"  # 空白はまとめる
    assert n.title.endswith("保保発1030第１号)") and "(PDF" not in n.title
    assert n.attachments == [{"title": "新旧対照表", "url": "https://www.mhlw.go.jp/hourei/doc/tsuchi/T261102S0061.pdf"}]
    assert items[2].posted == "2026-11-11"


def test_relevance_by_department_section_and_keywords():
    items = mhlw.parse_new_notices(PAGE, BASE)
    assert [mhlw.is_relevant(n, MHLW_NOTICES) for n in items] == [False, True, False]  # 医療課は除く


def test_diff_notices():
    items = mhlw.parse_new_notices(PAGE, BASE)
    old = {items[0].key, "https://www.mhlw.go.jp/hourei/doc/tsuchi/OLD.pdf"}
    new, removed = mhlw.diff_notices(old, items)
    assert [n.key for n in new] == [items[1].key, items[2].key]
    assert removed == ["https://www.mhlw.go.jp/hourei/doc/tsuchi/OLD.pdf"]  # データベースへの登載で消える
