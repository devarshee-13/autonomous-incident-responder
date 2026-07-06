"""Slack Block Kit builders for the incident brief message.

The Approve/Reject buttons carry only `incident_id` in their `value` — the
channel and message timestamp needed to update the message later come from
Slack's own interaction payload (body["channel"]["id"], body["message"]["ts"]),
so there's no need for a separate proposed_actions table just to route a
button click back to the right place yet.
"""

from __future__ import annotations


def incident_brief_blocks(
    *,
    alert: dict,
    culprit: dict,
    runbook: dict | None,
    impact: dict,
    proposed_action: dict | None,
    incident_id: str,
) -> list[dict]:
    """Build the Block Kit blocks for an incident brief. Includes
    Approve/Reject buttons only if a remediation was proposed."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🚨 {alert['alert_name']}: {alert['service']}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Probable cause:* `{culprit['commit_sha']}` "
                    f"(confidence {culprit['confidence']:.0%})\n"
                    f"{culprit['reasoning']}"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Runbook:* {runbook['runbook_id'] if runbook else 'none found'}\n"
                    f"*Impact:* {impact['summary']}"
                ),
            },
        },
    ]

    if proposed_action:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Proposed action:* `{proposed_action['action_type']}` "
                        f"on `{proposed_action['target_service']}`\n"
                        f"{proposed_action['rationale']}"
                    ),
                },
            }
        )
        blocks.append(
            {
                "type": "actions",
                "block_id": "incident_action_decision",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "approve_action",
                        "value": incident_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "action_id": "reject_action",
                        "value": incident_id,
                    },
                ],
            }
        )

    return blocks


def decision_result_blocks(*, decision: str, execution_result: str, decided_by: str) -> list[dict]:
    """Blocks to replace the actions block with, after a human clicks."""
    emoji = "✅" if decision == "approved" else "🚫"
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{decision.capitalize()}* by <@{decided_by}>\n{execution_result}",
            },
        }
    ]
