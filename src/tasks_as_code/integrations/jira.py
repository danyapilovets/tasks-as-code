"""One-way push of local tasks to Jira Cloud (REST API v3).

Local YAML stays the source of truth: this module never writes back into task
files. Credentials come from the environment. Everything that differs per project
or per language — status, type and priority names — is configuration rather than a
constant, because no default can be right for every Jira.

The other half of that problem is fields. A team-managed project decides which
fields exist on its create screen, and sending one it does not have is a hard 400
for every task. So the create screen is read once per run and the payload is
pruned to what the project actually accepts.

Requires the optional ``jira`` extra; see the install section of the README.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..core.config import JiraSettings
from ..core.loader import TaskRef

REQUIRED_ENV = ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY")

#: Where an issue goes rather than what is in it. Create-screen metadata does not
#: list these, so pruning against that metadata must never touch them.
STRUCTURAL_FIELDS = frozenset({"project", "issuetype"})

#: Rate limiting and transient server errors. Any other 4xx is a request to fix,
#: not one to repeat.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

#: Labels per JQL search. A batch matches at most one issue per label, so a
#: single page of 100 always covers a chunk of 50 and pagination cannot bite.
_LABELS_PER_QUERY = 50


class JiraNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class JiraCredentials:
    base_url: str
    email: str
    api_token: str
    project_key: str
    #: Jira Cloud accepts only an accountId here; usernames and emails were
    #: removed from the API. Optional: without it issues are created unassigned,
    #: which makes them invisible on a board filtered by assignee.
    assignee_account_id: str | None = None

    @classmethod
    def from_env(cls) -> JiraCredentials:
        missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
        if missing:
            raise JiraNotConfigured(
                "Missing environment variables: " + ", ".join(missing) + ". See docs/jira-sync.md."
            )
        return cls(
            base_url=os.environ["JIRA_BASE_URL"].rstrip("/"),
            email=os.environ["JIRA_EMAIL"],
            api_token=os.environ["JIRA_API_TOKEN"],
            project_key=os.environ["JIRA_PROJECT_KEY"],
            assignee_account_id=os.getenv("JIRA_ASSIGNEE_ACCOUNT_ID") or None,
        )


@dataclass(frozen=True)
class TypeMeta:
    """What the project's create screen accepts for one issue type."""

    issue_type_id: str
    field_ids: frozenset[str]
    #: Priority names the scheme offers, or ``None`` when the project has no
    #: priority field at all — a distinction that matters, because no choice of
    #: name helps in the second case.
    priorities: frozenset[str] | None


@dataclass(frozen=True)
class Finding:
    """One thing that does not line up between the backlog and the project."""

    blocking: bool
    message: str


def task_label(settings: JiraSettings, task_id: str) -> str:
    """Label that ties a Jira issue to a local task id, used to find it again."""
    return f"{settings.label_prefix}-{task_id}"


def issue_type_for(settings: JiraSettings, ref: TaskRef) -> str:
    return settings.type_map.get(ref.task.type, ref.task.type)


def priority_for(settings: JiraSettings, ref: TaskRef) -> str:
    return settings.priority_map.get(ref.task.priority, ref.task.priority)


def _inline(text: str) -> list[dict[str, Any]]:
    """Inline nodes for one block of text.

    Atlassian Document Format carries line structure in nodes, so a newline
    inside a text node is not a line break — it is dropped, and the text runs
    together. Each one becomes a ``hardBreak`` instead.
    """
    nodes: list[dict[str, Any]] = []
    for index, line in enumerate(text.split("\n")):
        if index:
            nodes.append({"type": "hardBreak"})
        if line:
            nodes.append({"type": "text", "text": line})
    return nodes


def _paragraph(text: str) -> dict[str, Any]:
    return {"type": "paragraph", "content": _inline(text)}


def _bullet_list(items: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "bulletList",
        "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": _inline(item)}]}
            for item in items
        ],
    }


def build_description(ref: TaskRef) -> dict[str, Any]:
    """Render a task as an ADF document: paragraphs and a real bullet list."""
    task = ref.task
    blocks: list[dict[str, Any]] = []
    if task.description:
        blocks.append(_paragraph(task.description))
    if task.acceptance_criteria:
        blocks.append(_paragraph("Acceptance criteria:"))
        blocks.append(_bullet_list(task.acceptance_criteria))
    if task.depends_on:
        blocks.append(_paragraph(f"Depends on: {', '.join(task.depends_on)}"))
    if not blocks:
        blocks.append(_paragraph("—"))
    return {"version": 1, "type": "doc", "content": blocks}


class JiraClient:
    def __init__(
        self,
        credentials: JiraCredentials,
        max_attempts: int = 3,
        sleep: Any = time.sleep,
    ):
        try:
            import requests
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on install extras
            raise JiraNotConfigured(
                "Jira sync needs the optional 'jira' extra. Reinstall with it:\n"
                '  pipx install "tasks-as-code[jira] @ '
                'git+https://github.com/danyapilovets/tasks-as-code@v1.0.0"'
            ) from exc

        self.credentials = credentials
        self.api = f"{credentials.base_url}/rest/api/3"
        self.max_attempts = max_attempts
        self._sleep = sleep
        self._meta_cache: dict[str, TypeMeta | None] = {}
        self._types_cache: list[dict[str, Any]] | None = None
        self.session = requests.Session()
        self.session.auth = requests.auth.HTTPBasicAuth(credentials.email, credentials.api_token)
        self.session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )

    def _retry_delay(self, response: Any, attempt: int) -> float:
        """Seconds to wait, preferring what Jira asked for.

        Jira rate-limits per user and says when to come back; guessing longer
        wastes time and guessing shorter gets throttled again.
        """
        header = getattr(response, "headers", {}) or {}
        retry_after = header.get("Retry-After")
        if retry_after is not None:
            try:
                return max(0.0, float(retry_after))
            except (TypeError, ValueError):
                pass
        return float(2**attempt)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in range(self.max_attempts):
            response = self.session.request(method, f"{self.api}{path}", timeout=30, **kwargs)
            last = attempt == self.max_attempts - 1
            if response.status_code in RETRY_STATUSES and not last:
                self._sleep(self._retry_delay(response, attempt))
                continue
            break
        if response.status_code >= 400:
            raise RuntimeError(f"Jira {method} {path} -> {response.status_code}: {response.text}")
        return {} if response.status_code == 204 else response.json()

    def _paginate(self, path: str, key: str) -> list[dict[str, Any]]:
        """Collect every page of one of the paginated metadata endpoints."""
        items: list[dict[str, Any]] = []
        start = 0
        while True:
            separator = "&" if "?" in path else "?"
            page = self._request("GET", f"{path}{separator}startAt={start}&maxResults=50")
            batch = page.get(key) or []
            items += batch
            total = page.get("total")
            start += len(batch)
            if not batch or total is None or start >= total:
                return items

    def issue_types(self) -> list[dict[str, Any]]:
        """Issue types the project offers.

        The single ``/issue/createmeta`` call that used to return this alongside
        every field is deprecated and answers 404, so types and fields are two
        separate, paginated endpoints now. That trade is what makes the result
        worth caching for the run: the replacements are one call per issue type,
        and asking again for each of them is a way to get rate-limited.
        """
        if self._types_cache is None:
            self._types_cache = self._paginate(
                f"/issue/createmeta/{self.credentials.project_key}/issuetypes", "issueTypes"
            )
        return self._types_cache

    def create_fields(self, issue_type_id: str) -> list[dict[str, Any]]:
        """Field metadata for one issue type's create screen."""
        return self._paginate(
            f"/issue/createmeta/{self.credentials.project_key}/issuetypes/{issue_type_id}",
            "fields",
        )

    def metadata_for(self, issue_type: str) -> TypeMeta | None:
        """Create-screen metadata for an issue type, or ``None`` if unreadable.

        Failing open is deliberate. Metadata is how the payload is trimmed to fit
        the project; if it cannot be read, sending everything and letting Jira
        answer is far better than dropping every field and creating empty issues.
        """
        if issue_type in self._meta_cache:
            return self._meta_cache[issue_type]

        meta: TypeMeta | None = None
        try:
            match = next(
                (
                    candidate
                    for candidate in self.issue_types()
                    if str(candidate.get("name", "")).casefold() == issue_type.casefold()
                ),
                None,
            )
            if match is not None:
                fields = self.create_fields(str(match["id"]))
                priority = next((f for f in fields if f.get("fieldId") == "priority"), None)
                meta = TypeMeta(
                    issue_type_id=str(match["id"]),
                    field_ids=frozenset(
                        str(field["fieldId"]) for field in fields if field.get("fieldId")
                    ),
                    priorities=(
                        frozenset(
                            str(value.get("name"))
                            for value in priority.get("allowedValues") or []
                            if value.get("name")
                        )
                        if priority is not None
                        else None
                    ),
                )
        except (RuntimeError, KeyError, TypeError, AttributeError):
            meta = None

        self._meta_cache[issue_type] = meta
        return meta

    def project_statuses(self) -> dict[str, frozenset[str]]:
        """Statuses reachable per issue type name."""
        payload = self._request("GET", f"/project/{self.credentials.project_key}/statuses")
        groups = payload if isinstance(payload, list) else []
        return {
            str(group.get("name")): frozenset(
                str(status.get("name")) for status in group.get("statuses") or []
            )
            for group in groups
            if group.get("name")
        }

    def find_by_label(self, label: str) -> dict[str, Any] | None:
        body = {
            "jql": f'project = {self.credentials.project_key} AND labels = "{label}"',
            "fields": ["summary", "status", "labels"],
            "maxResults": 1,
        }
        issues = self._request("POST", "/search/jql", json=body).get("issues", [])
        return issues[0] if issues else None

    def issues_by_labels(self, labels: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Look up many labels at once, keyed by label.

        One search per task is the bulk of the call budget for a sync, and the
        quickest way to meet the rate limit on a backlog of any size.
        """
        found: dict[str, dict[str, Any]] = {}
        for start in range(0, len(labels), _LABELS_PER_QUERY):
            chunk = set(labels[start : start + _LABELS_PER_QUERY])
            quoted = ", ".join(f'"{label}"' for label in sorted(chunk))
            body = {
                "jql": f"project = {self.credentials.project_key} AND labels IN ({quoted})",
                "fields": ["summary", "status", "labels"],
                "maxResults": 100,
            }
            for issue in self._request("POST", "/search/jql", json=body).get("issues", []):
                for label in issue.get("fields", {}).get("labels", []):
                    if label in chunk:
                        found.setdefault(label, issue)
        return found

    def create_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/issue", json=payload)

    def update_issue(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/issue/{key}", json=payload)

    def available_transitions(self, key: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/issue/{key}/transitions").get("transitions", [])

    def apply_transition(self, key: str, transition_id: str) -> dict[str, Any]:
        return self._request(
            "POST", f"/issue/{key}/transitions", json={"transition": {"id": transition_id}}
        )


def _prune(fields: dict[str, Any], meta: TypeMeta | None) -> dict[str, Any]:
    """Drop fields this project's create screen does not have."""
    if meta is None:
        return fields
    return {
        name: value
        for name, value in fields.items()
        if name in STRUCTURAL_FIELDS or name in meta.field_ids
    }


def sync_task(
    client: JiraClient,
    settings: JiraSettings,
    ref: TaskRef,
    dry_run: bool = False,
    known: Mapping[str, dict[str, Any]] | None = None,
) -> str:
    """Create or update the Jira issue mirroring one local task.

    ``known`` is a label-to-issue map from one batched search, so a sync of the
    whole backlog does not spend a query per task.
    """
    label = task_label(settings, ref.task.id)
    issue_type = issue_type_for(settings, ref)
    meta = client.metadata_for(issue_type)
    assignee = client.credentials.assignee_account_id

    fields: dict[str, Any] = {
        "summary": ref.task.summary,
        "description": build_description(ref),
        "priority": {"name": priority_for(settings, ref)},
    }

    existing = known.get(label) if known is not None else client.find_by_label(label)
    if existing:
        key = existing["key"]
        if dry_run:
            return f"would update {key}"
        if assignee and settings.force_assignee:
            fields["assignee"] = {"id": assignee}
        client.update_issue(key, {"fields": _prune(fields, meta)})
        _move_to_target_status(client, settings, key, existing, ref.task.status)
        return f"updated {key}"

    if dry_run:
        return "would create"
    if assignee:
        fields["assignee"] = {"id": assignee}
    fields |= {
        "project": {"key": client.credentials.project_key},
        "issuetype": {"name": issue_type},
        "labels": [label, f"epic-{ref.epic}"],
    }
    created = client.create_issue({"fields": _prune(fields, meta)})
    key = created["key"]
    if ref.task.status != "todo":
        _move_to_target_status(client, settings, key, None, ref.task.status)
    return f"created {key}"


def _move_to_target_status(
    client: JiraClient,
    settings: JiraSettings,
    key: str,
    existing: dict[str, Any] | None,
    status: str,
) -> None:
    target = settings.status_map.get(status)
    if not target:
        return
    if existing:
        current = existing.get("fields", {}).get("status", {}).get("name")
        if current and current.casefold() == target.casefold():
            return

    transitions = client.available_transitions(key)
    # The configured name is a status, so match where a transition leads. Matching
    # the transition's own name only works in workflows that happen to name it
    # after its destination ("Done"), and not in the ones that do not
    # ("Start progress" leading to "In Progress").
    for transition in transitions:
        destination = (transition.get("to") or {}).get("name")
        if destination and str(destination).casefold() == target.casefold():
            client.apply_transition(key, transition["id"])
            return
    for transition in transitions:
        if str(transition.get("name", "")).casefold() == target.casefold():
            client.apply_transition(key, transition["id"])
            return


def preflight(
    client: JiraClient,
    settings: JiraSettings,
    refs: Sequence[TaskRef],
) -> list[Finding]:
    """Compare the backlog against the project before sending anything.

    Everything needed is in the API: the project's issue types, the priorities of
    its scheme, the statuses of its workflow and the fields on its create screen.
    Reading them first turns a misconfiguration from one 400 per task, halfway
    through a push, into a list.
    """
    findings: list[Finding] = []
    try:
        available_types = {str(entry.get("name")) for entry in client.issue_types()}
    except (RuntimeError, KeyError, TypeError) as exc:
        return [Finding(True, f"Could not read the project's issue types: {exc}")]

    used_types: dict[str, list[str]] = {}
    for ref in refs:
        used_types.setdefault(issue_type_for(settings, ref), []).append(ref.task.id)

    for issue_type, task_ids in sorted(used_types.items()):
        if not any(name.casefold() == issue_type.casefold() for name in available_types):
            findings.append(
                Finding(
                    True,
                    f"Issue type '{issue_type}' does not exist in the project "
                    f"(used by {len(task_ids)} task(s); it has: "
                    f"{', '.join(sorted(available_types)) or 'none'}). "
                    "Map it with jira.type_map.",
                )
            )
            continue

        meta = client.metadata_for(issue_type)
        if meta is None:
            findings.append(Finding(False, f"Could not read the create screen for '{issue_type}'."))
            continue

        wanted = {"summary", "description", "priority", "labels"}
        if client.credentials.assignee_account_id:
            wanted.add("assignee")
        dropped = sorted(wanted - meta.field_ids)
        if dropped:
            findings.append(
                Finding(
                    False,
                    f"'{issue_type}' has no {', '.join(dropped)} on its create screen; "
                    "those values will not be sent.",
                )
            )

        if meta.priorities is not None:
            for priority in sorted(
                {
                    priority_for(settings, ref)
                    for ref in refs
                    if issue_type_for(settings, ref) == issue_type
                }
            ):
                if not any(name.casefold() == priority.casefold() for name in meta.priorities):
                    findings.append(
                        Finding(
                            True,
                            f"Priority '{priority}' is not in the scheme for '{issue_type}' "
                            f"(it offers: {', '.join(sorted(meta.priorities)) or 'none'}). "
                            "Map it with jira.priority_map.",
                        )
                    )

    try:
        statuses = client.project_statuses()
    except (RuntimeError, KeyError, TypeError) as exc:
        findings.append(Finding(False, f"Could not read the project's statuses: {exc}"))
        return findings

    reachable = {name.casefold() for group in statuses.values() for name in group}
    for local, target in sorted(settings.status_map.items()):
        if target and target.casefold() not in reachable:
            findings.append(
                Finding(
                    True,
                    f"status_map maps '{local}' to '{target}', which is not a status in this "
                    f"project (it has: {', '.join(sorted(reachable)) or 'none'}).",
                )
            )
    return findings
