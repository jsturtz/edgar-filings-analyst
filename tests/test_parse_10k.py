from pathlib import Path

from edgar_agent.parse_10k import html_to_text, parse_10k

HTML = (Path(__file__).parent / "fixtures" / "mini_10k.html").read_text()


def test_hidden_xbrl_header_removed():
    assert "DocumentFiscalYearFocus" not in html_to_text(HTML)


def test_tables_flattened_with_row_labels():
    text = html_to_text(HTML)
    assert "Net sales | 1,120 | 1,000" in text


def test_toc_ignored_and_real_sections_kept():
    sections = {s.item: s for s in parse_10k(HTML)}
    assert set(sections) == {"1", "1A", "7", "8"}
    assert "anvils, rockets" in sections["1"].text
    assert "Net sales increased 12%" in sections["7"].text
    assert sections["7"].title.startswith("Management")


def test_inline_item_reference_does_not_split_section():
    mdna = {s.item: s for s in parse_10k(HTML)}["7"].text
    assert "As discussed in Item 8, net income rose" in mdna
