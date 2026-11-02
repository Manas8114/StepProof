"""StepProof Test Harness: Self-healing web tests, locator drift tracking,
self-rewriting procedures, CI reporting (JUnit XML & HTML), and test scheduler.
"""
from .drift import DriftRecord, DriftReport, analyze_drift, self_rewrite_procedure
from .reports import generate_junit_xml, generate_html_report
from .scheduler import TestScheduler, get_scheduler

