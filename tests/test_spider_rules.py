"""Pure spider helpers: exclude matching, link extraction, binary skip, session
headers, seed subtree."""

from __future__ import annotations

import pytest

from nybiscan.core.spider import rules


def _ex(pattern, is_regex=False):
    return rules.compile_excludes([{"pattern": pattern, "is_regex": is_regex}])


def test_exclude_string_matches_exact_prefix_and_segment():
    r = _ex("/logout")
    assert rules.is_excluded("/logout", r)          # exact
    assert rules.is_excluded("/logout?x=1", r)      # query stripped
    assert rules.is_excluded("/logout/all", r)      # prefix dir
    assert rules.is_excluded("/auth/logout", r)     # segment
    assert not rules.is_excluded("/logoutpage", r)  # not a segment or prefix
    assert not rules.is_excluded("/home", r)


def test_exclude_regex_and_validation():
    r = rules.compile_excludes([{"pattern": r"/api/v\d+/admin", "is_regex": True}])
    assert rules.is_excluded("/api/v2/admin", r)
    assert not rules.is_excluded("/api/vx/admin", r)
    with pytest.raises(rules.ExcludeError):
        rules.compile_excludes([{"pattern": "(unclosed", "is_regex": True}])


def test_extract_links_resolves_and_filters_scheme():
    html = (
        b'<html><body>'
        b'<a href="/a">a</a>'
        b'<a href="page.html">rel</a>'
        b'<script src="/js/app.js"></script>'
        b'<form action="/submit"></form>'
        b'<a href="mailto:x@y.z">mail</a>'
        b'<a href="https://other.test/x">abs</a>'
        b'</body></html>'
    )
    links = rules.extract_links("http://h.test:8080/dir/index.html", html)
    assert "http://h.test:8080/a" in links
    assert "http://h.test:8080/dir/page.html" in links  # relative resolved
    assert "http://h.test:8080/js/app.js" in links
    assert "http://h.test:8080/submit" in links
    assert "https://other.test/x" in links
    assert not any(l.startswith("mailto") for l in links)  # non-http dropped


def test_skip_binary():
    assert rules.skip_binary("http://h/x.png", include_binary=False)
    assert rules.skip_binary("http://h/f.woff2", include_binary=False)
    assert not rules.skip_binary("http://h/app.js", include_binary=False)   # js is text
    assert not rules.skip_binary("http://h/a.css", include_binary=False)    # css is text
    assert not rules.skip_binary("http://h/page", include_binary=False)     # no ext
    assert not rules.skip_binary("http://h/x.png", include_binary=True)     # opt-in


def test_session_headers_drop_request_line_host_and_body_headers():
    raw = (
        "POST /login HTTP/1.1\r\nHost: old.test\r\nCookie: sess=abc\r\n"
        "Authorization: Bearer t\r\nContent-Length: 10\r\nContent-Type: application/json\r\n\r\n"
    )
    lines = rules.session_header_lines(raw)
    assert "Cookie: sess=abc" in lines
    assert "Authorization: Bearer t" in lines
    assert not any(l.lower().startswith("host:") for l in lines)
    assert not any(l.lower().startswith("content-length:") for l in lines)
    assert not any("HTTP/1.1" in l for l in lines)


def test_build_get_sets_target_host_and_session():
    raw_session = "GET / HTTP/1.1\r\nHost: whatever\r\nCookie: k=v\r\n\r\n"
    out = rules.build_get("/dash?x=1", "target.test", raw_session).decode()
    assert out.startswith("GET /dash?x=1 HTTP/1.1\r\nHost: target.test\r\n")
    assert "Cookie: k=v" in out
    assert out.endswith("\r\n\r\n")


def test_seed_subtree():
    assert rules.in_seed_subtree("/foo", "/foo")
    assert rules.in_seed_subtree("/foo/bar", "/foo")
    assert rules.in_seed_subtree("/foo/bar?x=1", "/foo")
    assert not rules.in_seed_subtree("/foobar", "/foo")   # not a child
    assert not rules.in_seed_subtree("/", "/foo")         # never ascend
    assert not rules.in_seed_subtree("/other", "/foo")
    # Seeding root crawls everything.
    assert rules.in_seed_subtree("/anything/deep", "/")
