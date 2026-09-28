from app.schedule_parser import parse_schedule


PUBLISHED_HTML = """
<html><body><h1>NIST Transportation</h1>
<table><tr><th>Bus No</th><th>Route</th><th>Driver</th></tr>
<tr><td>12</td><td>City Center - NIST</td><td>Ravi Kumar</td></tr>
<tr><td>18</td><td>Railway Station - NIST</td><td>Aman Das</td></tr></table>
</body></html>
"""


def test_successful_erp_response_with_published_schedule_is_parsed():
    schedule = parse_schedule(PUBLISHED_HTML)
    assert schedule is not None
    assert "Bus No | Route | Driver" in schedule.display_lines
    assert "12 | City Center - NIST | Ravi Kumar" in schedule.display_lines


def test_empty_or_unpublished_schedule_is_not_parsed():
    html = "<html><body><table><tr><td>No schedule available for selected time.</td></tr></table></body></html>"
    assert parse_schedule(html) is None


def test_minor_whitespace_changes_do_not_change_hash():
    compact = "<table><tr><th>Bus No</th><th>Route</th></tr><tr><td>12</td><td>Town - NIST</td></tr></table>"
    spaced = "<table> <tr><th> Bus No </th><th> Route </th></tr><tr><td>12</td><td>Town   -   NIST</td></tr></table>"
    assert parse_schedule(compact).content_hash == parse_schedule(spaced).content_hash


def test_malformed_or_unexpected_html_fails_safely():
    assert parse_schedule("<html><body><div>System online at 10:30</div>") is None
    assert parse_schedule("<table><tr><td>Broken</td><td>layout") is None
