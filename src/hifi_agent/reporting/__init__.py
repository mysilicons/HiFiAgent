"""Fault-tolerant Stage 12 report collection and rendering."""

from hifi_agent.reporting.collector import ReportCollector
from hifi_agent.reporting.models import FinalReportData, SyntheticReportScenario
from hifi_agent.reporting.renderer import ReportOutputs, render_final_report
from hifi_agent.reporting.synthetic import (
    DEFAULT_SYNTHETIC_SCENARIO,
    synthesize_candida_quality_regression,
)
from hifi_agent.reporting.v2 import V2ReportOutputs, render_v2_report
from hifi_agent.reporting.v2_models import V2FinalReport

__all__ = [
    "DEFAULT_SYNTHETIC_SCENARIO",
    "FinalReportData",
    "ReportCollector",
    "ReportOutputs",
    "SyntheticReportScenario",
    "V2FinalReport",
    "V2ReportOutputs",
    "render_final_report",
    "render_v2_report",
    "synthesize_candida_quality_regression",
]
