"""Deterministic generic hypothesis scoring for fallback RCA generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from retrieval.types import EvidenceBundle


FailurePattern = Literal[
    "configuration_change",
    "software_regression",
    "resource_exhaustion",
    "infrastructure_failure",
    "external_dependency_failure",
    "data_consistency_issue",
    "scaling_failure",
    "network_communication_failure",
]


@dataclass(slots=True)
class GenericEvidenceFeatures:
    """Typed evidence features extracted from one evidence bundle."""

    latest_deployment: dict[str, Any] | None = None
    rollback_deployment: dict[str, Any] | None = None
    recent_change_records: list[dict[str, Any]] = field(default_factory=list)
    rollback_recovery_records: list[dict[str, Any]] = field(default_factory=list)
    software_change_records: list[dict[str, Any]] = field(default_factory=list)
    configuration_change_records: list[dict[str, Any]] = field(default_factory=list)
    resource_exhaustion_records: list[dict[str, Any]] = field(default_factory=list)
    infrastructure_failure_records: list[dict[str, Any]] = field(default_factory=list)
    external_dependency_records: list[dict[str, Any]] = field(default_factory=list)
    dependency_healthy_records: list[dict[str, Any]] = field(default_factory=list)
    data_consistency_records: list[dict[str, Any]] = field(default_factory=list)
    write_success_records: list[dict[str, Any]] = field(default_factory=list)
    scaling_failure_records: list[dict[str, Any]] = field(default_factory=list)
    network_failure_records: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class PatternAssessment:
    """Support and contradiction assessment for one generic failure pattern."""

    pattern: FailurePattern
    support_score: float
    rule_out_score: float
    support_records: list[dict[str, Any]]
    rule_out_records: list[dict[str, Any]]
    reason_codes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScoredHypothesis:
    """Scored raw benchmark hypothesis projected from generic failure patterns."""

    text: str
    normalized_text: str
    mapped_patterns: list[FailurePattern]
    chosen_pattern: FailurePattern
    support_score: float
    rule_out_score: float
    support_records: list[dict[str, Any]]
    rule_out_records: list[dict[str, Any]]
    reason_codes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class HypothesisScoringReport:
    """Deterministic hypothesis scoring result for one evidence bundle."""

    winning_hypothesis: ScoredHypothesis | None
    hypotheses: list[ScoredHypothesis] = field(default_factory=list)
    features: GenericEvidenceFeatures = field(default_factory=GenericEvidenceFeatures)


def score_hypotheses(evidence_bundle: EvidenceBundle) -> HypothesisScoringReport:
    """Score raw benchmark hypotheses through generic reusable failure patterns."""
    hypothesis_records = [record for record in evidence_bundle.hypotheses if str(record.get("text", "")).strip()]
    if not hypothesis_records:
        return HypothesisScoringReport(winning_hypothesis=None)

    features = extract_generic_features(evidence_bundle)
    assessments = assess_failure_patterns(features)

    scored_hypotheses: list[ScoredHypothesis] = []
    for hypothesis in hypothesis_records:
        text = str(hypothesis.get("text", "")).strip()
        normalized = text.lower()
        mapped_patterns = map_hypothesis_to_patterns(text)
        selected_assessment = _select_best_assessment(mapped_patterns, assessments)
        if selected_assessment is None:
            continue
        support_adjustment, rule_out_adjustment, raw_reason_codes = _raw_hypothesis_adjustments(
            text=text,
            features=features,
            pattern=selected_assessment.pattern,
        )

        scored_hypotheses.append(
            ScoredHypothesis(
                text=text,
                normalized_text=normalized,
                mapped_patterns=mapped_patterns,
                chosen_pattern=selected_assessment.pattern,
                support_score=selected_assessment.support_score + support_adjustment,
                rule_out_score=selected_assessment.rule_out_score + rule_out_adjustment,
                support_records=list(selected_assessment.support_records),
                rule_out_records=list(selected_assessment.rule_out_records),
                reason_codes=list(selected_assessment.reason_codes) + raw_reason_codes,
            )
        )

    ranked = sorted(
        scored_hypotheses,
        key=lambda item: (
            item.support_score - item.rule_out_score,
            item.support_score,
            -item.rule_out_score,
            item.text,
        ),
        reverse=True,
    )
    return HypothesisScoringReport(
        winning_hypothesis=ranked[0] if ranked and ranked[0].support_score > 0 else None,
        hypotheses=ranked,
        features=features,
    )


def extract_generic_features(evidence_bundle: EvidenceBundle) -> GenericEvidenceFeatures:
    """Extract generic evidence features from a runtime-safe evidence bundle."""
    incident = evidence_bundle.incident or {}
    deployments = sorted(evidence_bundle.deployments, key=lambda record: str(record.get("timestamp", "")))
    commits = list(evidence_bundle.commits)
    metrics = list(evidence_bundle.metrics)
    logs = list(evidence_bundle.logs)
    timeline = list(evidence_bundle.timeline)
    configurations = list(evidence_bundle.configurations)

    latest_deployment = _latest_deployment_before_incident(deployments, incident)
    rollback_deployment = _first_rollback_after_incident(deployments, incident)

    recent_change_records = _dedupe_records(
        [record for record in [latest_deployment] if record is not None]
        + commits[:3]
    )
    rollback_recovery_records = _dedupe_records(
        ([rollback_deployment] if rollback_deployment is not None else [])
        + _matching_records(
            timeline + logs + metrics,
            (
                "rollback completed",
                "returned to baseline",
                "recovered",
                "recovery",
                "scale up",
                "scale-up",
                "restored",
                "rollback",
            ),
        )[:4]
    )
    software_change_records = _matching_records(
        commits + logs + timeline,
        (
            "cache",
            "warmup",
            "fanout",
            "decode context",
            "read routing",
            "replica",
            "autoscaler",
            "retry budget",
            "backoff",
            "rollout",
            "regression",
            "deployment",
            "version",
        ),
    )[:8]
    configuration_change_records = _matching_records(
        commits + logs + timeline + configurations,
        (
            "config",
            "policy",
            "tls",
            "egress",
            "certificate",
            "feature flag",
            "route",
            "network policy",
            "stale-while-revalidate",
        ),
    )[:8]
    resource_exhaustion_records = _matching_records(
        metrics + logs + timeline,
        (
            "memory",
            "heap",
            "rss",
            "oom",
            "oomkilled",
            "restart",
            "cpu",
            "pool exhaustion",
            "saturation",
            "watermark",
            "connection pool",
            "throttle",
        ),
    )[:8]
    infrastructure_failure_records = _matching_records(
        logs + timeline + configurations,
        (
            "kubelet",
            "node",
            "kernel",
            "disk",
            "az",
            "zone",
            "host",
            "container runtime",
            "eviction",
        ),
    )[:8]
    external_dependency_records = _matching_records(
        metrics + logs + timeline,
        (
            "s3",
            "ses",
            "provider",
            "cdn",
            "upstream",
            "downstream",
            "latency",
            "dependency",
            "vendor",
            "probe",
        ),
    )[:8]
    dependency_healthy_records = _matching_records(
        metrics + logs + timeline,
        (
            "stays flat",
            "stay flat",
            "remains normal",
            "healthy",
            "probe healthy",
            "latency stayed flat",
            "success percent remains normal",
            "within normal range",
        ),
    )[:8]
    data_consistency_records = _matching_records(
        metrics + logs + timeline + configurations + commits,
        (
            "replica lag",
            "stale",
            "not found",
            "read source returned no active subscription rows",
            "replica",
            "read share",
            "consistency",
            "freshness",
            "cache refresh skipped",
            "subscription not found",
        ),
    )[:8]
    write_success_records = _matching_records(
        metrics + logs + timeline,
        (
            "purchase success",
            "written successfully",
            "checkout purchase succeeded",
            "successful checkout",
            "success percent remains normal",
        ),
    )[:6]
    scaling_failure_records = _matching_records(
        metrics + logs + timeline + configurations + commits,
        (
            "backlog",
            "queue depth",
            "message age",
            "autoscaler",
            "scale",
            "scaling",
            "shard",
            "tenant migration",
            "load shape",
            "observed visible depth",
        ),
    )[:8]
    network_failure_records = _matching_records(
        logs + timeline + metrics + configurations + commits,
        (
            "timeout",
            "retry",
            "reconnect",
            "disconnect",
            "tls",
            "egress",
            "network",
            "handshake",
            "mesh",
            "connection reset",
            "socket",
        ),
    )[:8]

    return GenericEvidenceFeatures(
        latest_deployment=latest_deployment,
        rollback_deployment=rollback_deployment,
        recent_change_records=_dedupe_records(recent_change_records),
        rollback_recovery_records=_dedupe_records(rollback_recovery_records),
        software_change_records=_dedupe_records(software_change_records),
        configuration_change_records=_dedupe_records(configuration_change_records),
        resource_exhaustion_records=_dedupe_records(resource_exhaustion_records),
        infrastructure_failure_records=_dedupe_records(infrastructure_failure_records),
        external_dependency_records=_dedupe_records(external_dependency_records),
        dependency_healthy_records=_dedupe_records(dependency_healthy_records),
        data_consistency_records=_dedupe_records(data_consistency_records),
        write_success_records=_dedupe_records(write_success_records),
        scaling_failure_records=_dedupe_records(scaling_failure_records),
        network_failure_records=_dedupe_records(network_failure_records),
    )


def assess_failure_patterns(features: GenericEvidenceFeatures) -> dict[FailurePattern, PatternAssessment]:
    """Assess all generic failure patterns from extracted evidence features."""
    assessments: dict[FailurePattern, PatternAssessment] = {}
    assessments["software_regression"] = _assess_software_regression(features)
    assessments["configuration_change"] = _assess_configuration_change(features)
    assessments["resource_exhaustion"] = _assess_resource_exhaustion(features)
    assessments["infrastructure_failure"] = _assess_infrastructure_failure(features)
    assessments["external_dependency_failure"] = _assess_external_dependency_failure(features)
    assessments["data_consistency_issue"] = _assess_data_consistency_issue(features)
    assessments["scaling_failure"] = _assess_scaling_failure(features)
    assessments["network_communication_failure"] = _assess_network_failure(features)
    return assessments


def map_hypothesis_to_patterns(text: str) -> list[FailurePattern]:
    """Map one raw benchmark hypothesis into reusable generic failure patterns."""
    normalized = text.strip().lower()
    patterns: list[FailurePattern] = []

    if any(keyword in normalized for keyword in ("replica", "stale", "consistency", "write failure")):
        patterns.append("data_consistency_issue")
    if any(keyword in normalized for keyword in ("cache", "software", "warmup")):
        patterns.append("software_regression")
    if "regression" in normalized and not any(
        keyword in normalized for keyword in ("autoscaling", "autoscaler", "scaling", "tenant", "shard")
    ):
        patterns.append("software_regression")
    if any(keyword in normalized for keyword in ("config", "policy", "tls", "egress", "flag")):
        patterns.append("configuration_change")
    if any(keyword in normalized for keyword in ("memory", "cpu", "pool", "saturation", "resource")):
        patterns.append("resource_exhaustion")
    if any(keyword in normalized for keyword in ("object storage", "provider", "dependency", "cdn", "delivery")):
        patterns.append("external_dependency_failure")
    if any(keyword in normalized for keyword in ("autoscaling", "autoscaler", "hot shard", "traffic surge", "scaling")):
        patterns.append("scaling_failure")
    if any(keyword in normalized for keyword in ("timeout", "retry", "reconnect", "disconnect", "network")):
        patterns.append("network_communication_failure")
    if any(keyword in normalized for keyword in ("az", "zone", "node", "host", "infra")):
        patterns.append("infrastructure_failure")

    if not patterns:
        patterns.append("software_regression")

    return _dedupe_pattern_list(patterns)


def build_evidence_summary(report: HypothesisScoringReport) -> list[str]:
    """Build generic evidence-summary bullets from the scoring report."""
    winning = report.winning_hypothesis
    if winning is None:
        return []

    features = report.features
    lines: list[str] = []
    if features.latest_deployment is not None:
        deployment_id = features.latest_deployment.get("deployment_id", features.latest_deployment.get("node_id"))
        timestamp = features.latest_deployment.get("timestamp")
        lines.append(f"Symptoms begin after deployment {deployment_id} at {timestamp}.")

    pattern_line = _pattern_summary_line(winning.chosen_pattern, features)
    if pattern_line:
        lines.append(pattern_line)

    if features.rollback_recovery_records:
        lines.append("Rollback or recovery evidence strengthens the causal link to the observed failure pattern.")

    if winning.rule_out_records:
        lines.append("Competing explanations are weaker because contradictory evidence points away from them.")

    return lines[:4]


def compose_root_cause(report: HypothesisScoringReport) -> str:
    """Compose one concise generic root-cause statement from the scoring report."""
    winning = report.winning_hypothesis
    if winning is None:
        return ""

    features = report.features
    pattern_label = _pattern_label(winning.chosen_pattern)
    sentence = f"Evidence most strongly supports {winning.text} as a {pattern_label}."

    if features.latest_deployment is not None:
        deployment_id = features.latest_deployment.get("deployment_id", features.latest_deployment.get("node_id"))
        deployment_time = features.latest_deployment.get("timestamp")
        sentence += f" The strongest correlation begins immediately after deployment {deployment_id} at {deployment_time}."

    signal_line = _pattern_root_cause_line(winning.chosen_pattern, features)
    if signal_line:
        sentence += f" {signal_line}"

    if features.rollback_deployment is not None or features.rollback_recovery_records:
        rollback_time = (
            features.rollback_deployment.get("timestamp")
            if features.rollback_deployment is not None
            else None
        )
        sentence += f" Recovery after the rollback{f' at {rollback_time}' if rollback_time else ''} strengthens that conclusion."

    return sentence


def _select_best_assessment(
    mapped_patterns: list[FailurePattern],
    assessments: dict[FailurePattern, PatternAssessment],
) -> PatternAssessment | None:
    """Return the strongest generic pattern assessment for one raw hypothesis."""
    selected: list[PatternAssessment] = [assessments[pattern] for pattern in mapped_patterns if pattern in assessments]
    if not selected:
        return None
    return sorted(
        selected,
        key=lambda item: (
            item.support_score - item.rule_out_score,
            item.support_score,
            -item.rule_out_score,
            item.pattern,
        ),
        reverse=True,
    )[0]


def _raw_hypothesis_adjustments(
    *,
    text: str,
    features: GenericEvidenceFeatures,
    pattern: FailurePattern,
) -> tuple[float, float, list[str]]:
    """Adjust one raw hypothesis within its generic category using incident-local evidence."""
    normalized = text.lower()
    support_adjustment = 0.0
    rule_out_adjustment = 0.0
    reason_codes: list[str] = []

    if pattern == "data_consistency_issue":
        if "replica" in normalized and _records_match(features.data_consistency_records, ("replica lag", "replica", "read share")):
            support_adjustment += 1.0
            reason_codes.append("raw_hypothesis_matches_replica_signals")
        if "write failure" in normalized and features.write_success_records:
            rule_out_adjustment += 2.5
            reason_codes.append("successful_write_signals_contradict_write_failure")

    if pattern == "resource_exhaustion":
        if "memory" in normalized and _records_match(features.resource_exhaustion_records, ("memory", "heap", "rss", "oom", "restart")):
            support_adjustment += 1.0
            reason_codes.append("raw_hypothesis_matches_memory_signals")
        if "cpu" in normalized and _records_match(features.resource_exhaustion_records, ("cpu", "saturation")):
            support_adjustment += 0.5
            reason_codes.append("raw_hypothesis_matches_cpu_signals")

    if pattern == "scaling_failure":
        if "autoscaling" in normalized and _records_match(features.scaling_failure_records, ("autoscaler", "scale", "observed visible depth")):
            support_adjustment += 1.0
            reason_codes.append("raw_hypothesis_matches_autoscaling_signals")
        if "hot shard" in normalized and _records_match(features.scaling_failure_records, ("shard", "tenant migration", "load shape")):
            support_adjustment += 0.75
            reason_codes.append("raw_hypothesis_matches_load_skew_signals")

    if pattern == "external_dependency_failure":
        if "provider" in normalized and _records_match(features.dependency_healthy_records, ("healthy", "stays flat", "remains normal", "probe healthy")):
            rule_out_adjustment += 1.5
            reason_codes.append("healthy_dependency_signals_contradict_provider_failure")

    return support_adjustment, rule_out_adjustment, reason_codes


def _assess_software_regression(features: GenericEvidenceFeatures) -> PatternAssessment:
    support_records = _dedupe_records(
        features.recent_change_records
        + features.software_change_records
        + features.rollback_recovery_records[:2]
    )
    rule_out_records = _dedupe_records(features.external_dependency_records[:2] + features.infrastructure_failure_records[:2])
    support_score = 0.0
    reason_codes: list[str] = []
    if features.recent_change_records:
        support_score += 2.0
        reason_codes.append("recent_change_before_impact")
    if features.software_change_records:
        support_score += 3.0
        reason_codes.append("software_behavior_change_detected")
    if features.rollback_recovery_records:
        support_score += 2.0
        reason_codes.append("rollback_recovery_detected")
    rule_out_score = 1.5 if features.infrastructure_failure_records else 0.0
    rule_out_score += 1.5 if features.external_dependency_records and not features.dependency_healthy_records else 0.0
    if features.data_consistency_records and features.write_success_records:
        rule_out_score += 2.5
    if _records_match(features.resource_exhaustion_records, ("memory", "heap", "rss", "oom", "restart")):
        rule_out_score += 1.5
    return PatternAssessment(
        pattern="software_regression",
        support_score=support_score,
        rule_out_score=rule_out_score,
        support_records=support_records,
        rule_out_records=rule_out_records,
        reason_codes=reason_codes,
    )


def _assess_configuration_change(features: GenericEvidenceFeatures) -> PatternAssessment:
    support_records = _dedupe_records(
        features.configuration_change_records
        + features.recent_change_records
        + features.rollback_recovery_records[:2]
        + features.network_failure_records[:2]
    )
    support_score = 0.0
    reason_codes: list[str] = []
    if features.configuration_change_records:
        support_score += 4.0
        reason_codes.append("configuration_or_policy_change_detected")
    if features.recent_change_records:
        support_score += 2.0
        reason_codes.append("change_timing_matches_impact")
    if features.rollback_recovery_records:
        support_score += 2.5
        reason_codes.append("rollback_recovery_detected")
    rule_out_score = 1.5 if features.resource_exhaustion_records and not features.configuration_change_records else 0.0
    return PatternAssessment(
        pattern="configuration_change",
        support_score=support_score,
        rule_out_score=rule_out_score,
        support_records=support_records,
        rule_out_records=list(features.resource_exhaustion_records[:2]),
        reason_codes=reason_codes,
    )


def _assess_resource_exhaustion(features: GenericEvidenceFeatures) -> PatternAssessment:
    support_records = _dedupe_records(
        features.resource_exhaustion_records
        + features.scaling_failure_records[:2]
        + features.rollback_recovery_records[:1]
    )
    support_score = 0.0
    reason_codes: list[str] = []
    if features.resource_exhaustion_records:
        support_score += 4.0
        reason_codes.append("resource_growth_or_restart_detected")
        if _records_match(features.resource_exhaustion_records, ("memory", "heap", "rss", "oom", "restart", "watermark")):
            support_score += 2.0
            reason_codes.append("memory_or_restart_signal_detected")
    if features.scaling_failure_records:
        support_score += 1.5
        reason_codes.append("capacity_pressure_detected")
    if features.recent_change_records:
        support_score += 1.0
        reason_codes.append("recent_change_precedes_resource_growth")
    if features.rollback_recovery_records:
        support_score += 1.0
        reason_codes.append("recovery_after_intervention")
    rule_out_score = 2.0 if features.external_dependency_records and not features.dependency_healthy_records else 0.0
    return PatternAssessment(
        pattern="resource_exhaustion",
        support_score=support_score,
        rule_out_score=rule_out_score,
        support_records=support_records,
        rule_out_records=list(features.external_dependency_records[:2]),
        reason_codes=reason_codes,
    )


def _assess_infrastructure_failure(features: GenericEvidenceFeatures) -> PatternAssessment:
    support_records = _dedupe_records(features.infrastructure_failure_records + features.network_failure_records[:2])
    support_score = 4.0 if features.infrastructure_failure_records else 0.0
    if features.network_failure_records:
        support_score += 1.0
    rule_out_score = 2.0 if features.software_change_records or features.configuration_change_records else 0.0
    return PatternAssessment(
        pattern="infrastructure_failure",
        support_score=support_score,
        rule_out_score=rule_out_score,
        support_records=support_records,
        rule_out_records=_dedupe_records(features.software_change_records[:2] + features.configuration_change_records[:2]),
        reason_codes=["infrastructure_signal_detected"] if support_records else [],
    )


def _assess_external_dependency_failure(features: GenericEvidenceFeatures) -> PatternAssessment:
    support_records = _dedupe_records(features.external_dependency_records)
    support_score = 4.0 if features.external_dependency_records else 0.0
    rule_out_records = _dedupe_records(features.dependency_healthy_records + features.recent_change_records[:2])
    rule_out_score = 3.0 if features.dependency_healthy_records else 0.0
    if features.recent_change_records and features.rollback_recovery_records:
        rule_out_score += 1.5
    return PatternAssessment(
        pattern="external_dependency_failure",
        support_score=support_score,
        rule_out_score=rule_out_score,
        support_records=support_records,
        rule_out_records=rule_out_records,
        reason_codes=["dependency_signal_detected"] if support_records else [],
    )


def _assess_data_consistency_issue(features: GenericEvidenceFeatures) -> PatternAssessment:
    support_records = _dedupe_records(
        features.data_consistency_records
        + features.write_success_records
        + features.software_change_records[:2]
        + features.rollback_recovery_records[:2]
    )
    support_score = 0.0
    reason_codes: list[str] = []
    if features.data_consistency_records:
        support_score += 5.0
        reason_codes.append("stale_or_replica_lag_signal_detected")
        if _records_match(features.data_consistency_records, ("replica lag", "stale", "read share", "not found")):
            support_score += 2.0
            reason_codes.append("replica_or_stale_read_evidence_detected")
    if features.write_success_records:
        support_score += 2.0
        reason_codes.append("writes_succeed_while_reads_fail")
    if features.recent_change_records:
        support_score += 1.0
        reason_codes.append("recent_change_precedes_consistency_failure")
    if features.software_change_records:
        support_score += 1.5
        reason_codes.append("read_behavior_change_detected")
    if features.rollback_recovery_records:
        support_score += 1.5
        reason_codes.append("rollback_recovery_detected")
    rule_out_records = _dedupe_records(features.resource_exhaustion_records[:2] + features.external_dependency_records[:2])
    rule_out_score = 1.5 if features.resource_exhaustion_records else 0.0
    rule_out_score += 1.5 if features.external_dependency_records and not features.dependency_healthy_records else 0.0
    return PatternAssessment(
        pattern="data_consistency_issue",
        support_score=support_score,
        rule_out_score=rule_out_score,
        support_records=support_records,
        rule_out_records=rule_out_records,
        reason_codes=reason_codes,
    )


def _assess_scaling_failure(features: GenericEvidenceFeatures) -> PatternAssessment:
    support_records = _dedupe_records(
        features.scaling_failure_records
        + features.rollback_recovery_records[:2]
        + features.recent_change_records[:2]
    )
    support_score = 0.0
    reason_codes: list[str] = []
    if features.scaling_failure_records:
        support_score += 2.5
        reason_codes.append("backlog_or_autoscaling_signal_detected")
        if _records_match(
            features.scaling_failure_records,
            ("autoscaler", "observed visible depth", "shard", "tenant migration", "message age", "queue depth"),
        ):
            support_score += 3.0
            reason_codes.append("autoscaling_or_load_skew_signal_detected")
    if features.recent_change_records:
        support_score += 1.5
        reason_codes.append("recent_scaling_related_change_detected")
    if features.rollback_recovery_records:
        support_score += 1.5
        reason_codes.append("recovery_after_scaling_intervention")
    rule_out_records = _dedupe_records(features.external_dependency_records[:2] + features.resource_exhaustion_records[:2])
    rule_out_score = 2.0 if features.external_dependency_records and not features.dependency_healthy_records else 0.0
    return PatternAssessment(
        pattern="scaling_failure",
        support_score=support_score,
        rule_out_score=rule_out_score,
        support_records=support_records,
        rule_out_records=rule_out_records,
        reason_codes=reason_codes,
    )


def _assess_network_failure(features: GenericEvidenceFeatures) -> PatternAssessment:
    support_records = _dedupe_records(
        features.network_failure_records
        + features.configuration_change_records[:2]
        + features.rollback_recovery_records[:1]
    )
    support_score = 0.0
    reason_codes: list[str] = []
    if features.network_failure_records:
        support_score += 4.0
        reason_codes.append("timeout_or_reconnect_signal_detected")
    if features.configuration_change_records:
        support_score += 1.5
        reason_codes.append("network_policy_or_tls_change_detected")
    if features.rollback_recovery_records:
        support_score += 1.0
        reason_codes.append("recovery_after_network_change")
    rule_out_score = 1.5 if features.resource_exhaustion_records and not features.configuration_change_records else 0.0
    return PatternAssessment(
        pattern="network_communication_failure",
        support_score=support_score,
        rule_out_score=rule_out_score,
        support_records=support_records,
        rule_out_records=list(features.resource_exhaustion_records[:2]),
        reason_codes=reason_codes,
    )


def _pattern_summary_line(pattern: FailurePattern, features: GenericEvidenceFeatures) -> str:
    """Return one generic summary sentence for the winning failure pattern."""
    if pattern == "data_consistency_issue":
        return "Logs and metrics point to stale or lagging reads rather than a broad write-path failure."
    if pattern == "resource_exhaustion":
        return "Metrics and logs show sustained capacity pressure, including resource growth or restart signals."
    if pattern == "scaling_failure":
        return "Backlog and scaling signals diverge, indicating the system did not add effective capacity for the observed load shape."
    if pattern == "external_dependency_failure":
        return "Dependency-facing signals point to an upstream service bottleneck or degradation."
    if pattern == "network_communication_failure":
        return "Timeout, retry, reconnect, or policy-related signals point to a communication-path problem."
    if pattern == "configuration_change":
        return "A configuration or policy change aligns with onset and the observed failure behavior."
    if pattern == "infrastructure_failure":
        return "Host or platform-level signals suggest an infrastructure problem rather than an application-only regression."
    return "Recent application changes align with onset and explain the symptom pattern better than competing causes."


def _pattern_root_cause_line(pattern: FailurePattern, features: GenericEvidenceFeatures) -> str:
    """Return one generic RCA sentence tailored to the winning failure pattern."""
    if pattern == "data_consistency_issue":
        return "The strongest signals are stale-read or replica-lag indicators, supported by successful write-path evidence and recovery after intervention."
    if pattern == "resource_exhaustion":
        return "The strongest signals are resource-growth, saturation, or restart indicators that reduce effective processing capacity."
    if pattern == "scaling_failure":
        return "The strongest signals are backlog growth and autoscaling mismatch, showing that available capacity did not track demand correctly."
    if pattern == "external_dependency_failure":
        return "The strongest signals are dependency-facing latency or error indicators rather than internal compute saturation."
    if pattern == "network_communication_failure":
        return "The strongest signals are timeout or reconnect patterns consistent with a broken communication path."
    if pattern == "configuration_change":
        return "The strongest signals are policy or configuration changes whose timing matches onset and recovery."
    if pattern == "infrastructure_failure":
        return "The strongest signals are platform-level faults rather than feature-level behavior changes."
    return "The strongest signals are application-level behavior changes followed by clear recovery after rollback or mitigation."


def _pattern_label(pattern: FailurePattern) -> str:
    """Return a human-readable label for one generic failure pattern."""
    return pattern.replace("_", " ")


def _dedupe_pattern_list(values: list[FailurePattern]) -> list[FailurePattern]:
    """Return stable unique failure patterns while preserving order."""
    seen: set[str] = set()
    deduped: list[FailurePattern] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _latest_deployment_before_incident(
    deployments: list[dict[str, Any]],
    incident: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the most recent deployment at or before incident start."""
    incident_start = _parse_iso8601(incident.get("start_time"))
    candidates = [
        record
        for record in deployments
        if incident_start is not None and (_parse_iso8601(record.get("timestamp")) or incident_start) <= incident_start
    ]
    return candidates[-1] if candidates else (deployments[-1] if deployments else None)


def _first_rollback_after_incident(
    deployments: list[dict[str, Any]],
    incident: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the first rollback deployment after incident start when present."""
    incident_start = _parse_iso8601(incident.get("start_time"))
    for record in deployments:
        strategy = str(record.get("strategy", "")).lower()
        timestamp = _parse_iso8601(record.get("timestamp"))
        if "rollback" in strategy and incident_start is not None and timestamp is not None and timestamp >= incident_start:
            return record
    return None


def _matching_records(records: list[dict[str, Any]], keywords: tuple[str, ...]) -> list[dict[str, Any]]:
    """Return records whose text fields mention any of the supplied keywords."""
    matches: list[dict[str, Any]] = []
    for record in records:
        haystack = _record_text(record)
        if any(keyword in haystack for keyword in keywords):
            matches.append(record)
    return matches


def _record_text(record: dict[str, Any]) -> str:
    """Return a normalized searchable text projection for one evidence record."""
    parts: list[str] = []
    for key in ("message", "event", "detail", "summary", "title", "metric", "text", "service", "component"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip().lower())
    for key in ("files_changed", "recommended_actions"):
        value = record.get(key)
        if isinstance(value, list):
            parts.extend(str(item).strip().lower() for item in value if str(item).strip())
    return " | ".join(parts)


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return records with unique node IDs while preserving order."""
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        node_id = str(record.get("node_id", "")).strip()
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        deduped.append(record)
    return deduped


def _parse_iso8601(value: Any) -> datetime | None:
    """Parse one dataset timestamp into a datetime when possible."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _records_match(records: list[dict[str, Any]], keywords: tuple[str, ...]) -> bool:
    """Return True when any record text contains one of the supplied keywords."""
    for record in records:
        haystack = _record_text(record)
        if any(keyword in haystack for keyword in keywords):
            return True
    return False


__all__ = [
    "FailurePattern",
    "GenericEvidenceFeatures",
    "HypothesisScoringReport",
    "PatternAssessment",
    "ScoredHypothesis",
    "build_evidence_summary",
    "compose_root_cause",
    "score_hypotheses",
]
