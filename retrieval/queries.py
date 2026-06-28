"""Cypher query helpers for incident lookup and evidence traversal."""

from __future__ import annotations


def _bounded_hops(max_hops: int, *, minimum: int = 1, maximum: int = 2) -> int:
    """Clamp a traversal depth to the retrieval contract's bounded range."""
    return max(minimum, min(max_hops, maximum))


INCIDENT_BY_ID_QUERY = """
MATCH (incident:Incident {id: $incident_id})
RETURN {
  incident: {
    node_id: incident.id,
    node_labels: labels(incident),
    properties: properties(incident)
  }
} AS result
""".strip()
"""Lookup one incident by canonical incident ID."""


INCIDENTS_BY_PRIMARY_SERVICE_QUERY = """
MATCH (incident:Incident {service: $service_name})
OPTIONAL MATCH (incident)-[observed_on:OBSERVED_ON]->(service:Service {name: $service_name})
RETURN {
  incident: {
    node_id: incident.id,
    node_labels: labels(incident),
    properties: properties(incident)
  },
  matched_service: CASE
    WHEN service IS NULL THEN NULL
    ELSE {
      node_id: service.id,
      node_labels: labels(service),
      properties: properties(service)
    }
  END,
  relationship: CASE
    WHEN observed_on IS NULL THEN NULL
    ELSE {
      relationship_type: type(observed_on),
      source_id: startNode(observed_on).id,
      target_id: endNode(observed_on).id,
      properties: properties(observed_on)
    }
  END
} AS result
ORDER BY incident.start_time DESC, incident.id ASC
""".strip()
"""Lookup incidents by the primary service stored on the Incident node."""


SERVICE_BY_NAME_QUERY = """
MATCH (service:Service {name: $service_name})
RETURN {
  service: {
    node_id: service.id,
    node_labels: labels(service),
    properties: properties(service)
  }
} AS result
ORDER BY service.id ASC
""".strip()
"""Lookup one or more services by exact service name."""


SERVICE_BY_ALIAS_QUERY = """
MATCH (service:Service)
WHERE $service_alias IN coalesce(service.aliases, [])
RETURN {
  service: {
    node_id: service.id,
    node_labels: labels(service),
    properties: properties(service)
  },
  matched_alias: $service_alias
} AS result
ORDER BY service.name ASC, service.id ASC
""".strip()
"""Lookup services by exact alias match against `Service.aliases`."""


def build_incident_evidence_neighborhood_query(*, topology_hops: int = 1) -> str:
    """Return a bounded incident-neighborhood traversal query."""
    hops = _bounded_hops(topology_hops)
    return f"""
MATCH (incident:Incident {{id: $incident_id}})
OPTIONAL MATCH (incident)<-[observed_in:OBSERVED_IN]-(incident_neighbor)
OPTIONAL MATCH (incident)-[incident_out:OBSERVED_ON|MATCHES|OCCURRED_AFTER]->(incident_target)
OPTIONAL MATCH (incident)-[incident_service_edge:OBSERVED_ON]->(service:Service)
OPTIONAL MATCH (hypothesis:Hypothesis)-[hypothesis_in:OBSERVED_IN]->(incident)
OPTIONAL MATCH (supporting_evidence)-[hypothesis_signal:SUPPORTS|RULES_OUT]->(hypothesis)
OPTIONAL MATCH (timeline:TimelineEvent)-[timeline_in:OBSERVED_IN]->(incident)
OPTIONAL MATCH (timeline)-[timeline_ref:REFERENCES]->(timeline_reference)
OPTIONAL MATCH (runbook:Runbook)<-[runbook_match:MATCHES]-(incident)
OPTIONAL MATCH (runbook)-[runbook_action_rel:RECOMMENDS]->(action:Action)
WITH
  incident,
  collect(DISTINCT service.id) AS service_ids,
  [item IN collect(DISTINCT CASE WHEN incident_neighbor IS NULL THEN NULL ELSE {{
    node_id: incident_neighbor.id,
    node_labels: labels(incident_neighbor),
    properties: properties(incident_neighbor)
  }} END) WHERE item IS NOT NULL] AS observed_in_nodes,
  [item IN collect(DISTINCT CASE WHEN incident_target IS NULL THEN NULL ELSE {{
    node_id: incident_target.id,
    node_labels: labels(incident_target),
    properties: properties(incident_target)
  }} END) WHERE item IS NOT NULL] AS outbound_nodes,
  [item IN collect(DISTINCT CASE WHEN service IS NULL THEN NULL ELSE {{
    node_id: service.id,
    node_labels: labels(service),
    properties: properties(service)
  }} END) WHERE item IS NOT NULL] AS service_nodes,
  [item IN collect(DISTINCT CASE WHEN timeline_reference IS NULL THEN NULL ELSE {{
    node_id: timeline_reference.id,
    node_labels: labels(timeline_reference),
    properties: properties(timeline_reference)
  }} END) WHERE item IS NOT NULL] AS timeline_reference_nodes,
  [item IN collect(DISTINCT CASE WHEN action IS NULL THEN NULL ELSE {{
    node_id: action.id,
    node_labels: labels(action),
    properties: properties(action)
  }} END) WHERE item IS NOT NULL] AS action_nodes,
  [item IN collect(DISTINCT CASE WHEN supporting_evidence IS NULL THEN NULL ELSE {{
    node_id: supporting_evidence.id,
    node_labels: labels(supporting_evidence),
    properties: properties(supporting_evidence)
  }} END) WHERE item IS NOT NULL] AS hypothesis_signal_nodes,
  [item IN collect(DISTINCT CASE WHEN observed_in IS NULL THEN NULL ELSE {{
    relationship_type: type(observed_in),
    source_id: startNode(observed_in).id,
    target_id: endNode(observed_in).id,
    properties: properties(observed_in)
  }} END) WHERE item IS NOT NULL] AS observed_in_edges,
  [item IN collect(DISTINCT CASE WHEN incident_out IS NULL THEN NULL ELSE {{
    relationship_type: type(incident_out),
    source_id: startNode(incident_out).id,
    target_id: endNode(incident_out).id,
    properties: properties(incident_out)
  }} END) WHERE item IS NOT NULL] AS incident_out_edges,
  [item IN collect(DISTINCT CASE WHEN hypothesis_in IS NULL THEN NULL ELSE {{
    relationship_type: type(hypothesis_in),
    source_id: startNode(hypothesis_in).id,
    target_id: endNode(hypothesis_in).id,
    properties: properties(hypothesis_in)
  }} END) WHERE item IS NOT NULL] AS hypothesis_in_edges,
  [item IN collect(DISTINCT CASE WHEN hypothesis_signal IS NULL THEN NULL ELSE {{
    relationship_type: type(hypothesis_signal),
    source_id: startNode(hypothesis_signal).id,
    target_id: endNode(hypothesis_signal).id,
    properties: properties(hypothesis_signal)
  }} END) WHERE item IS NOT NULL] AS hypothesis_signal_edges,
  [item IN collect(DISTINCT CASE WHEN timeline_in IS NULL THEN NULL ELSE {{
    relationship_type: type(timeline_in),
    source_id: startNode(timeline_in).id,
    target_id: endNode(timeline_in).id,
    properties: properties(timeline_in)
  }} END) WHERE item IS NOT NULL] AS timeline_in_edges,
  [item IN collect(DISTINCT CASE WHEN timeline_ref IS NULL THEN NULL ELSE {{
    relationship_type: type(timeline_ref),
    source_id: startNode(timeline_ref).id,
    target_id: endNode(timeline_ref).id,
    properties: properties(timeline_ref)
  }} END) WHERE item IS NOT NULL] AS timeline_ref_edges,
  [item IN collect(DISTINCT CASE WHEN runbook_action_rel IS NULL THEN NULL ELSE {{
    relationship_type: type(runbook_action_rel),
    source_id: startNode(runbook_action_rel).id,
    target_id: endNode(runbook_action_rel).id,
    properties: properties(runbook_action_rel)
  }} END) WHERE item IS NOT NULL] AS runbook_action_edges,
  [item IN collect(DISTINCT CASE WHEN runbook_match IS NULL THEN NULL ELSE {{
    relationship_type: type(runbook_match),
    source_id: startNode(runbook_match).id,
    target_id: endNode(runbook_match).id,
    properties: properties(runbook_match)
  }} END) WHERE item IS NOT NULL] AS runbook_match_edges
CALL {{
  WITH service_ids
  OPTIONAL MATCH path = (service:Service)-[:DEPENDS_ON*1..{hops}]-(related:Service)
  WHERE service.id IN service_ids
  WITH
    [item IN collect(DISTINCT CASE WHEN related IS NULL THEN NULL ELSE {{
      node_id: related.id,
      node_labels: labels(related),
      properties: properties(related)
    }} END) WHERE item IS NOT NULL] AS related_service_nodes,
    [path_item IN collect(DISTINCT path) WHERE path_item IS NOT NULL | path_item] AS dep_paths
  UNWIND CASE WHEN size(dep_paths) = 0 THEN [NULL] ELSE dep_paths END AS dep_path
  UNWIND CASE
    WHEN dep_path IS NULL THEN [NULL]
    ELSE relationships(dep_path)
  END AS dep_rel
  RETURN
    related_service_nodes,
    [item IN collect(DISTINCT CASE WHEN dep_rel IS NULL THEN NULL ELSE {{
      relationship_type: type(dep_rel),
      source_id: startNode(dep_rel).id,
      target_id: endNode(dep_rel).id,
      properties: properties(dep_rel)
    }} END) WHERE item IS NOT NULL] AS expanded_service_dep_edges
}}
WITH
  incident,
  observed_in_nodes,
  outbound_nodes,
  service_nodes,
  timeline_reference_nodes,
  action_nodes,
  hypothesis_signal_nodes,
  observed_in_edges,
  incident_out_edges,
  related_service_nodes,
  expanded_service_dep_edges,
  hypothesis_in_edges,
  hypothesis_signal_edges,
  timeline_in_edges,
  timeline_ref_edges,
  runbook_action_edges,
  runbook_match_edges
RETURN {{
  incident: {{
    node_id: incident.id,
    node_labels: labels(incident),
    properties: properties(incident)
  }},
  nodes: [{{
    node_id: incident.id,
    node_labels: labels(incident),
    properties: properties(incident)
  }}] + observed_in_nodes + outbound_nodes + service_nodes + related_service_nodes + timeline_reference_nodes + action_nodes + hypothesis_signal_nodes,
  edges: observed_in_edges
    + incident_out_edges
    + expanded_service_dep_edges
    + hypothesis_in_edges
    + hypothesis_signal_edges
    + timeline_in_edges
    + timeline_ref_edges
    + runbook_action_edges
    + runbook_match_edges
}} AS result
""".strip()


DEPLOYMENTS_FOR_INCIDENT_QUERY = """
MATCH (incident:Incident {id: $incident_id})<-[observed_in:OBSERVED_IN]-(deployment:Deployment)
OPTIONAL MATCH (deployment)-[observed_on:OBSERVED_ON]->(service:Service)
OPTIONAL MATCH (commit:Commit)-[included_in:INCLUDED_IN]->(deployment)
WITH
  incident,
  observed_in,
  deployment,
  observed_on,
  service,
  collect(DISTINCT CASE WHEN commit IS NULL THEN NULL ELSE {
    node_id: commit.id,
    node_labels: labels(commit),
    properties: properties(commit)
  } END) AS included_commit_items,
  collect(DISTINCT CASE WHEN included_in IS NULL THEN NULL ELSE {
    relationship_type: type(included_in),
    source_id: startNode(included_in).id,
    target_id: endNode(included_in).id,
    properties: properties(included_in)
  } END) AS included_in_edge_items
ORDER BY deployment.timestamp ASC, deployment.id ASC
WITH
  incident,
  observed_in,
  deployment,
  observed_on,
  service,
  [item IN included_commit_items WHERE item IS NOT NULL] AS included_commits,
  [item IN included_in_edge_items WHERE item IS NOT NULL] AS included_in_edges
RETURN {
  incident_id: incident.id,
  deployment: {
    node_id: deployment.id,
    node_labels: labels(deployment),
    properties: properties(deployment)
  },
  observed_in_edge: {
    relationship_type: type(observed_in),
    source_id: startNode(observed_in).id,
    target_id: endNode(observed_in).id,
    properties: properties(observed_in)
  },
  service: CASE
    WHEN service IS NULL THEN NULL
    ELSE {
      node_id: service.id,
      node_labels: labels(service),
      properties: properties(service)
    }
  END,
  observed_on_edge: CASE
    WHEN observed_on IS NULL THEN NULL
    ELSE {
      relationship_type: type(observed_on),
      source_id: startNode(observed_on).id,
      target_id: endNode(observed_on).id,
      properties: properties(observed_on)
    }
  END,
  included_commits: included_commits,
  included_in_edges: included_in_edges
} AS result
""".strip()
"""Retrieve deployment evidence attached to one incident."""


COMMITS_FOR_INCIDENT_QUERY = """
MATCH (incident:Incident {id: $incident_id})<-[observed_in:OBSERVED_IN]-(commit:Commit)
OPTIONAL MATCH (commit)-[changed_rel:CHANGED]->(configuration:Configuration)
OPTIONAL MATCH (commit)-[included_in:INCLUDED_IN]->(deployment:Deployment)
WITH
  incident,
  observed_in,
  commit,
  collect(DISTINCT CASE WHEN configuration IS NULL THEN NULL ELSE {
    node_id: configuration.id,
    node_labels: labels(configuration),
    properties: properties(configuration)
  } END) AS changed_configurations,
  collect(DISTINCT CASE WHEN changed_rel IS NULL THEN NULL ELSE {
    relationship_type: type(changed_rel),
    source_id: startNode(changed_rel).id,
    target_id: endNode(changed_rel).id,
    properties: properties(changed_rel)
  } END) AS changed_edges,
  collect(DISTINCT CASE WHEN deployment IS NULL THEN NULL ELSE {
    node_id: deployment.id,
    node_labels: labels(deployment),
    properties: properties(deployment)
  } END) AS deployments,
  collect(DISTINCT CASE WHEN included_in IS NULL THEN NULL ELSE {
    relationship_type: type(included_in),
    source_id: startNode(included_in).id,
    target_id: endNode(included_in).id,
    properties: properties(included_in)
  } END) AS included_in_edges
ORDER BY commit.timestamp ASC, commit.id ASC
WITH
  incident,
  observed_in,
  commit,
  [item IN changed_configurations WHERE item IS NOT NULL] AS changed_configurations,
  [item IN changed_edges WHERE item IS NOT NULL] AS changed_edges,
  [item IN deployments WHERE item IS NOT NULL] AS deployments,
  [item IN included_in_edges WHERE item IS NOT NULL] AS included_in_edges
RETURN {
  incident_id: incident.id,
  commit: {
    node_id: commit.id,
    node_labels: labels(commit),
    properties: properties(commit)
  },
  observed_in_edge: {
    relationship_type: type(observed_in),
    source_id: startNode(observed_in).id,
    target_id: endNode(observed_in).id,
    properties: properties(observed_in)
  },
  changed_configurations: changed_configurations,
  changed_edges: changed_edges,
  deployments: deployments,
  included_in_edges: included_in_edges
} AS result
""".strip()
"""Retrieve commit evidence attached to one incident."""


METRICS_FOR_INCIDENT_QUERY = """
MATCH (incident:Incident {id: $incident_id})<-[observed_in:OBSERVED_IN]-(series:MetricSeries)
OPTIONAL MATCH (series)-[metric_ref:REFERENCES]->(metric:Metric)
OPTIONAL MATCH (series)-[observed_on:OBSERVED_ON]->(service:Service)
RETURN {
  incident_id: incident.id,
  metric_series: {
    node_id: series.id,
    node_labels: labels(series),
    properties: properties(series)
  },
  observed_in_edge: {
    relationship_type: type(observed_in),
    source_id: startNode(observed_in).id,
    target_id: endNode(observed_in).id,
    properties: properties(observed_in)
  },
  metric: CASE
    WHEN metric IS NULL THEN NULL
    ELSE {
      node_id: metric.id,
      node_labels: labels(metric),
      properties: properties(metric)
    }
  END,
  metric_reference_edge: CASE
    WHEN metric_ref IS NULL THEN NULL
    ELSE {
      relationship_type: type(metric_ref),
      source_id: startNode(metric_ref).id,
      target_id: endNode(metric_ref).id,
      properties: properties(metric_ref)
    }
  END,
  service: CASE
    WHEN service IS NULL THEN NULL
    ELSE {
      node_id: service.id,
      node_labels: labels(service),
      properties: properties(service)
    }
  END,
  observed_on_edge: CASE
    WHEN observed_on IS NULL THEN NULL
    ELSE {
      relationship_type: type(observed_on),
      source_id: startNode(observed_on).id,
      target_id: endNode(observed_on).id,
      properties: properties(observed_on)
    }
  END
} AS result
ORDER BY coalesce(series.first_anomalous_at, series.window_start) ASC, series.id ASC
""".strip()
"""Retrieve metric-series evidence attached to one incident."""


LOGS_FOR_INCIDENT_QUERY = """
MATCH (incident:Incident {id: $incident_id})<-[observed_in:OBSERVED_IN]-(log:LogEvent)
OPTIONAL MATCH (log)-[observed_on:OBSERVED_ON]->(service:Service)
OPTIONAL MATCH (log)-[log_ref:REFERENCES]->(referenced)
WITH
  incident,
  observed_in,
  log,
  service,
  observed_on,
  collect(DISTINCT CASE WHEN referenced IS NULL THEN NULL ELSE {
    node_id: referenced.id,
    node_labels: labels(referenced),
    properties: properties(referenced)
  } END) AS references,
  collect(DISTINCT CASE WHEN log_ref IS NULL THEN NULL ELSE {
    relationship_type: type(log_ref),
    source_id: startNode(log_ref).id,
    target_id: endNode(log_ref).id,
    properties: properties(log_ref)
  } END) AS reference_edges
ORDER BY log.timestamp ASC, log.id ASC
WITH
  incident,
  observed_in,
  log,
  service,
  observed_on,
  [item IN references WHERE item IS NOT NULL] AS references,
  [item IN reference_edges WHERE item IS NOT NULL] AS reference_edges
RETURN {
  incident_id: incident.id,
  log: {
    node_id: log.id,
    node_labels: labels(log),
    properties: properties(log)
  },
  observed_in_edge: {
    relationship_type: type(observed_in),
    source_id: startNode(observed_in).id,
    target_id: endNode(observed_in).id,
    properties: properties(observed_in)
  },
  service: CASE
    WHEN service IS NULL THEN NULL
    ELSE {
      node_id: service.id,
      node_labels: labels(service),
      properties: properties(service)
    }
  END,
  observed_on_edge: CASE
    WHEN observed_on IS NULL THEN NULL
    ELSE {
      relationship_type: type(observed_on),
      source_id: startNode(observed_on).id,
      target_id: endNode(observed_on).id,
      properties: properties(observed_on)
    }
  END,
  references: references,
  reference_edges: reference_edges
} AS result
""".strip()
"""Retrieve log evidence attached to one incident."""


TIMELINE_EVENTS_FOR_INCIDENT_QUERY = """
MATCH (incident:Incident {id: $incident_id})<-[observed_in:OBSERVED_IN]-(timeline:TimelineEvent)
OPTIONAL MATCH (timeline)-[occurred_after:OCCURRED_AFTER]->(previous:TimelineEvent)
OPTIONAL MATCH (timeline)-[timeline_ref:REFERENCES]->(referenced)
WITH
  incident,
  observed_in,
  timeline,
  previous,
  occurred_after,
  collect(DISTINCT CASE WHEN referenced IS NULL THEN NULL ELSE {
    node_id: referenced.id,
    node_labels: labels(referenced),
    properties: properties(referenced)
  } END) AS references,
  collect(DISTINCT CASE WHEN timeline_ref IS NULL THEN NULL ELSE {
    relationship_type: type(timeline_ref),
    source_id: startNode(timeline_ref).id,
    target_id: endNode(timeline_ref).id,
    properties: properties(timeline_ref)
  } END) AS reference_edges
ORDER BY timeline.timestamp ASC, timeline.id ASC
WITH
  incident,
  observed_in,
  timeline,
  previous,
  occurred_after,
  [item IN references WHERE item IS NOT NULL] AS references,
  [item IN reference_edges WHERE item IS NOT NULL] AS reference_edges
RETURN {
  incident_id: incident.id,
  timeline_event: {
    node_id: timeline.id,
    node_labels: labels(timeline),
    properties: properties(timeline)
  },
  observed_in_edge: {
    relationship_type: type(observed_in),
    source_id: startNode(observed_in).id,
    target_id: endNode(observed_in).id,
    properties: properties(observed_in)
  },
  previous_event: CASE
    WHEN previous IS NULL THEN NULL
    ELSE {
      node_id: previous.id,
      node_labels: labels(previous),
      properties: properties(previous)
    }
  END,
  occurred_after_edge: CASE
    WHEN occurred_after IS NULL THEN NULL
    ELSE {
      relationship_type: type(occurred_after),
      source_id: startNode(occurred_after).id,
      target_id: endNode(occurred_after).id,
      properties: properties(occurred_after)
    }
  END,
  references: references,
  reference_edges: reference_edges
} AS result
""".strip()
"""Retrieve timeline evidence attached to one incident."""


HYPOTHESES_FOR_INCIDENT_QUERY = """
MATCH (hypothesis:Hypothesis)-[observed_in:OBSERVED_IN]->(incident:Incident {id: $incident_id})
OPTIONAL MATCH (supporting_evidence)-[supports:SUPPORTS]->(hypothesis)
OPTIONAL MATCH (counter_evidence)-[rules_out:RULES_OUT]->(hypothesis)
WITH
  incident,
  hypothesis,
  observed_in,
  collect(DISTINCT CASE WHEN supporting_evidence IS NULL THEN NULL ELSE {
    node_id: supporting_evidence.id,
    node_labels: labels(supporting_evidence),
    properties: properties(supporting_evidence)
  } END) AS supporting_evidence,
  collect(DISTINCT CASE WHEN supports IS NULL THEN NULL ELSE {
    relationship_type: type(supports),
    source_id: startNode(supports).id,
    target_id: endNode(supports).id,
    properties: properties(supports)
  } END) AS support_edges,
  collect(DISTINCT CASE WHEN counter_evidence IS NULL THEN NULL ELSE {
    node_id: counter_evidence.id,
    node_labels: labels(counter_evidence),
    properties: properties(counter_evidence)
  } END) AS ruling_out_evidence,
  collect(DISTINCT CASE WHEN rules_out IS NULL THEN NULL ELSE {
    relationship_type: type(rules_out),
    source_id: startNode(rules_out).id,
    target_id: endNode(rules_out).id,
    properties: properties(rules_out)
  } END) AS rules_out_edges
ORDER BY hypothesis.id ASC
WITH
  incident,
  hypothesis,
  observed_in,
  [item IN supporting_evidence WHERE item IS NOT NULL] AS supporting_evidence,
  [item IN support_edges WHERE item IS NOT NULL] AS support_edges,
  [item IN ruling_out_evidence WHERE item IS NOT NULL] AS ruling_out_evidence,
  [item IN rules_out_edges WHERE item IS NOT NULL] AS rules_out_edges
RETURN {
  incident_id: incident.id,
  hypothesis: {
    node_id: hypothesis.id,
    node_labels: labels(hypothesis),
    properties: properties(hypothesis)
  },
  observed_in_edge: {
    relationship_type: type(observed_in),
    source_id: startNode(observed_in).id,
    target_id: endNode(observed_in).id,
    properties: properties(observed_in)
  },
  supporting_evidence: supporting_evidence,
  support_edges: support_edges,
  ruling_out_evidence: ruling_out_evidence,
  rules_out_edges: rules_out_edges
} AS result
""".strip()
"""Retrieve candidate hypotheses and attached support or rule-out signals."""


RUNBOOKS_FOR_INCIDENT_QUERY = """
MATCH (incident:Incident {id: $incident_id})-[matched_by:MATCHES]->(runbook:Runbook)
OPTIONAL MATCH (runbook)-[recommends:RECOMMENDS]->(action:Action)
WITH
  incident,
  runbook,
  matched_by,
  collect(DISTINCT CASE WHEN action IS NULL THEN NULL ELSE {
    node_id: action.id,
    node_labels: labels(action),
    properties: properties(action)
  } END) AS recommended_actions,
  collect(DISTINCT CASE WHEN recommends IS NULL THEN NULL ELSE {
    relationship_type: type(recommends),
    source_id: startNode(recommends).id,
    target_id: endNode(recommends).id,
    properties: properties(recommends)
  } END) AS recommendation_edges
ORDER BY runbook.filename ASC, runbook.id ASC
WITH
  incident,
  runbook,
  matched_by,
  [item IN recommended_actions WHERE item IS NOT NULL] AS recommended_actions,
  [item IN recommendation_edges WHERE item IS NOT NULL] AS recommendation_edges
RETURN {
  incident_id: incident.id,
  runbook: {
    node_id: runbook.id,
    node_labels: labels(runbook),
    properties: properties(runbook)
  },
  matched_by_edge: {
    relationship_type: type(matched_by),
    source_id: startNode(matched_by).id,
    target_id: endNode(matched_by).id,
    properties: properties(matched_by)
  },
  recommended_actions: recommended_actions,
  recommendation_edges: recommendation_edges
} AS result
""".strip()
"""Retrieve runbooks matched to one incident and their recommended actions."""


def build_service_topology_for_incident_query(*, max_hops: int = 2) -> str:
    """Return a bounded service-topology query for services related to one incident."""
    hops = _bounded_hops(max_hops)
    return f"""
MATCH (incident:Incident {{id: $incident_id}})-[observed_on:OBSERVED_ON]->(service:Service)
WITH
  incident,
  [item IN collect(DISTINCT {{
    node_id: service.id,
    node_labels: labels(service),
    properties: properties(service)
  }}) WHERE item IS NOT NULL] AS incident_services,
  collect(DISTINCT service.id) AS service_ids,
  [item IN collect(DISTINCT {{
    relationship_type: type(observed_on),
    source_id: startNode(observed_on).id,
    target_id: endNode(observed_on).id,
    properties: properties(observed_on)
  }}) WHERE item IS NOT NULL] AS incident_service_edges
CALL {{
  WITH service_ids
  OPTIONAL MATCH path = (service:Service)-[:DEPENDS_ON*1..{hops}]-(related:Service)
  WHERE service.id IN service_ids
  WITH
  [item IN collect(DISTINCT CASE WHEN related IS NULL THEN NULL ELSE {{
    node_id: related.id,
    node_labels: labels(related),
    properties: properties(related)
  }} END) WHERE item IS NOT NULL] AS related_services,
    [path_item IN collect(DISTINCT path) WHERE path_item IS NOT NULL | path_item] AS dep_paths
  UNWIND CASE WHEN size(dep_paths) = 0 THEN [NULL] ELSE dep_paths END AS dep_path
  UNWIND CASE
    WHEN dep_path IS NULL THEN [NULL]
    ELSE relationships(dep_path)
  END AS dep_rel
  RETURN
    related_services,
    [item IN collect(DISTINCT CASE WHEN dep_rel IS NULL THEN NULL ELSE {{
      relationship_type: type(dep_rel),
      source_id: startNode(dep_rel).id,
      target_id: endNode(dep_rel).id,
      properties: properties(dep_rel)
    }} END) WHERE item IS NOT NULL] AS dependency_edges
}}
WITH
  incident,
  incident_services,
  related_services,
  incident_service_edges,
  dependency_edges
RETURN {{
  incident: {{
    node_id: incident.id,
    node_labels: labels(incident),
    properties: properties(incident)
  }},
  services: incident_services + related_services,
  edges: incident_service_edges + dependency_edges
}} AS result
""".strip()


INCIDENT_EVIDENCE_NEIGHBORHOOD_QUERY = build_incident_evidence_neighborhood_query()
"""Default bounded neighborhood query for incident-centered traversal."""


SERVICE_TOPOLOGY_FOR_INCIDENT_QUERY = build_service_topology_for_incident_query()
"""Default bounded service-topology query for incident-related services."""


__all__ = [
    "INCIDENT_BY_ID_QUERY",
    "INCIDENTS_BY_PRIMARY_SERVICE_QUERY",
    "SERVICE_BY_NAME_QUERY",
    "SERVICE_BY_ALIAS_QUERY",
    "INCIDENT_EVIDENCE_NEIGHBORHOOD_QUERY",
    "DEPLOYMENTS_FOR_INCIDENT_QUERY",
    "COMMITS_FOR_INCIDENT_QUERY",
    "METRICS_FOR_INCIDENT_QUERY",
    "LOGS_FOR_INCIDENT_QUERY",
    "TIMELINE_EVENTS_FOR_INCIDENT_QUERY",
    "HYPOTHESES_FOR_INCIDENT_QUERY",
    "RUNBOOKS_FOR_INCIDENT_QUERY",
    "SERVICE_TOPOLOGY_FOR_INCIDENT_QUERY",
    "build_incident_evidence_neighborhood_query",
    "build_service_topology_for_incident_query",
]
