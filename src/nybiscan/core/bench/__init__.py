"""Bench (Repeater analog): craft, edit, and send requests verbatim.

Bench sends its own requests DIRECTLY (not through the proxy) with byte-level
fidelity - exactly the bytes the tester composed. Sends record into the tab's own
bench_history, never the main proxy history. Send is unrestricted (a manual, one
request at a time tool; the human is the per-send authorization check).
"""
