# src/ai/qa_engine.py
from src.connectors.doc_connector import DocConnector
from src.connectors.jira_connector import JiraConnector
from src.connectors.gdrive_connector import GDriveConnector
from src.ai.llm_client import LLMClient
from typing import List, Optional
import re
import sys
import io

# Set UTF-8 encoding for stdout to handle symbols in various terminals
if hasattr(sys.stdout, 'encoding') and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

class QAEngine:
    def __init__(self, jira_conn: JiraConnector, gdrive_conn: GDriveConnector, llm_client: LLMClient):
        self.doc_conn = DocConnector()
        self.jira_conn = jira_conn
        self.gdrive_conn = gdrive_conn
        self.llm_client = llm_client
        self.deprecations = self.doc_conn.fetch_deprecations()

    def _find_deprecations(self, query: str):
        q = query.lower()

        # A) "pending removal in Python 3.15"
        m = re.search(r"pending removal in python\s*(3\.\d+)", q)
        if m:
            target = m.group(1)
            hits = [d for d in self.deprecations if (d.version_removed or "").lower() == target.lower()]
            return ("REMOVAL_LIST", target, hits)

        # B) generic feature search: match feature/module/description
        needle = re.sub(r"[^a-z0-9_\.]+", " ", q).strip()
        tokens = [t for t in needle.split() if t not in {"deprecation", "deprecated", "remove", "removal", "eol"}]

        def score(d):
            hay = " ".join([
                (d.feature or ""),
                (d.module or ""),
                (d.description or ""),
            ]).lower()
            s = 0
            for t in tokens:
                if not t:
                    continue
                if t in hay:
                    s += 2
                if d.feature and t in d.feature.lower():
                    s += 3
            return s

        ranked = sorted(self.deprecations, key=score, reverse=True)
        hits = [d for d in ranked if score(d) > 0][:10]
        return ("FEATURE_SEARCH", None, hits)


    def _format_deprecations_context(self, mode, target, hits):
        if mode == "REMOVAL_LIST":
            if not hits:
                return f"No deprecations found pending removal in Python {target}."
            return (
                f"Deprecations pending removal in Python {target}:\n"
                + "\n".join(
                    f"- {d.feature} | Deprecated: {d.version_deprecated or 'N/A'} | Module: {d.module or 'N/A'}\n"
                    f"  {d.description or ''}\n"
                    f"  {d.url or ''}".rstrip()
                    for d in hits
                )
            )

        # FEATURE_SEARCH
        if not hits:
            return "No matching deprecations found in the official list."
        return (
            "Matching deprecations:\n"
            + "\n".join(
                f"- {d.feature} (Deprecated: {d.version_deprecated or 'N/A'}, Removed: {d.version_removed or 'N/A'})"
                f" | Module: {d.module or 'N/A'}\n"
                f"  {d.description or ''}\n"
                f"  {d.url or ''}".rstrip()
                for d in hits
            )
        )


    def answer_query(self, query: str) -> str:
        # 1. Intent Classification
        system_instruction = (
            "You are a helpful assistant for a Python EOL management project. "
            "Classify the user's query into one of the following INTENTS:\n"
            "- DEPRECATION_INFO: Questions about Python features, deprecations, or removals.\n"
            "- DEPRECATION_GAP: Requests to find deprecations that happened but are NOT in the backlog (e.g. 'new proposals', 'not in backlog').\n"
            "- JIRA_LIST: Requests to list Jira tickets (e.g., 'show me tickets', 'list items').\n"
            "- JIRA_DETAIL: Requests for details about a specific Jira ticket (e.g., SCRUM-123, 'content of ticket').\n"
            "- JIRA_COUNT: Requests to count tickets in a certain status (e.g., 'how many testing tickets').\n"
            "- BACKLOG_LIST: Requests to list files in the Google Drive backlog.\n"
            "- BACKLOG_PICKUP: Requests to find backlog items not yet in Jira.\n"
            "- GENERAL: General greeting or queries not related to the above.\n\n"
            "If the query contains a ticket key like SCRUM-123, prefer JIRA_DETAIL.\n"
            "Respond ONLY with the INTENT name."
        )
        
        intent = self.llm_client.generate_response(f"Classify this query: '{query}'", system_instruction=system_instruction).strip()
        
        # Clean up intent
        valid_intents = ["DEPRECATION_INFO", "DEPRECATION_GAP", "JIRA_LIST", "JIRA_DETAIL", "JIRA_COUNT", "BACKLOG_LIST", "BACKLOG_PICKUP", "GENERAL"]
        found_intent = False
        for valid in valid_intents:
            if valid in intent:
                intent = valid
                found_intent = True
                break
        
        # Heuristic overrides for robustness
        msg_lower = query.lower()

        # Strong override: deprecation-related questions should not depend on LLM intent
        if (
            any(k in msg_lower for k in ["deprecation", "deprecated", "pending removal", "removal", "eol"])
            or re.search(r"\bpython\s*3\.\d+\b", msg_lower)
        ):
            intent = "DEPRECATION_INFO"

        # Jira overrides (ticket key should win)
        if "scrum-" in msg_lower:
            intent = "JIRA_DETAIL"
        elif "how many" in msg_lower and "ticket" in msg_lower:
            intent = "JIRA_COUNT"

        if not found_intent and intent not in valid_intents:
            intent = "GENERAL"

        # 2. Data Retrieval & Response Generation
        context_data = ""

        if intent == "DEPRECATION_INFO":
            # Deterministic retrieval instead of dumping the full list
            # Requires helper methods added to the class:
            # - self._find_deprecations(query)
            # - self._format_deprecations_context(mode, target, hits)
            mode, target, hits = self._find_deprecations(query)
            context_data = self._format_deprecations_context(mode, target, hits)

        elif intent == "DEPRECATION_GAP":
            backlog_tasks = self.gdrive_conn.get_backlog_tasks()
            backlog_titles = {t.title.lower() for t in backlog_tasks}

            gap_items = []
            for dep in self.deprecations:
                is_in_backlog = False
                for title in backlog_titles:
                    if dep.feature.lower() in title:
                        is_in_backlog = True
                        break

                if not is_in_backlog:
                    gap_items.append(dep)

            if not gap_items:
                context_data = "All deprecations seem to be represented in the backlog."
            else:
                context_data = "Deprecations NOT found in Backlog:\n" + "\n".join(
                    [f"- {d.feature} (Deprecated: {d.version_deprecated})" for d in gap_items]
                )

        elif intent == "JIRA_LIST":
            tickets = self.jira_conn.get_tickets()
            if not tickets:
                context_data = "No Jira tickets found."
            else:
                context_data = "Jira Tickets:\n" + "\n".join(
                    [f"{t.key}: {t.summary} ({t.status})" for t in tickets]
                )

        elif intent == "JIRA_COUNT":
            # Extract status if present
            target_status = None
            if "testing" in msg_lower:
                target_status = "Testing"
            elif "done" in msg_lower:
                target_status = "Done"
            elif "progress" in msg_lower:
                target_status = "In Progress"
            elif "todo" in msg_lower or "to do" in msg_lower:
                target_status = "To Do"

            tickets = self.jira_conn.get_tickets(status=target_status)
            count = len(tickets)
            status_str = target_status if target_status else "Total"
            context_data = f"Found {count} tickets with status '{status_str}'."

        elif intent == "JIRA_DETAIL":
            match = re.search(r"scrum-(\d+)", msg_lower)
            if match:
                key = f"SCRUM-{match.group(1)}"
                ticket = self.jira_conn.get_ticket(key)
                if ticket:
                    context_data = (
                        f"Ticket Details:\n"
                        f"Key: {ticket.key}\n"
                        f"Summary: {ticket.summary}\n"
                        f"Status: {ticket.status}\n"
                        f"Description: {ticket.description}\n"
                        f"Assignee: {ticket.assignee}"
                    )
                else:
                    context_data = f"Ticket {key} not found."
            else:
                context_data = "Could not identify ticket key (SCRUM-XXX) in query."

        elif intent == "BACKLOG_LIST":
            tasks = self.gdrive_conn.get_backlog_tasks()
            if not tasks:
                context_data = "Backlog is empty."
            else:
                context_data = "Backlog Files:\n" + "\n".join([f"{t.title}" for t in tasks])

        elif intent == "BACKLOG_PICKUP":
            tasks = self.gdrive_conn.get_backlog_tasks()
            tickets = self.jira_conn.get_tickets()
            ticket_summaries = [t.summary.lower() for t in tickets]
            pickup_list = [t for t in tasks if t.title.lower() not in ticket_summaries]

            if not pickup_list:
                context_data = "Everything in backlog is already in Jira."
            else:
                context_data = "Items to Pickup (in Backlog but not Jira):\n" + "\n".join(
                    [f"{t.title}" for t in pickup_list]
                )

        else:  # GENERAL
            pass

        # 3. Final Response
        final_system_prompt = (
            "You are the Python EOL Assistant. Answer the user's query using the provided CONTEXT DATA.\n"
            "Rules:\n"
            "1. If the CONTEXT DATA contains the answer, use it.\n"
            "2. If the query asks for deprecation info and the feature is NOT in 'Known Deprecations', say you don't have information about it. DO NOT hallucinate versions.\n"
            "3. For counting requests, use the count provided in context.\n"
            "4. Keep the answer concise and professional."
        )
        
        final_prompt = f"User Query: {query}\n\nCONTEXT DATA:\n{context_data}"
        return self.llm_client.generate_response(final_prompt, system_instruction=final_system_prompt)
