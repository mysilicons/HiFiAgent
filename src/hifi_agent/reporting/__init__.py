"""Fault-tolerant Stage 12 report collection and rendering."""

from hifi_agent.reporting.collector import ReportCollector
from hifi_agent.reporting.models import FinalReportData, SyntheticReportScenario
from hifi_agent.reporting.renderer import ReportOutputs, render_final_report
from hifi_agent.reporting.synthetic import (
    DEFAULT_SYNTHETIC_SCENARIO,
    synthesize_candida_quality_regression,
)

__all__ = [
    "DEFAULT_SYNTHETIC_SCENARIO",
    "FinalReportData",
    "ReportCollector",
    "ReportOutputs",
    "SyntheticReportScenario",
    "render_final_report",
    "synthesize_candida_quality_regression",
]
