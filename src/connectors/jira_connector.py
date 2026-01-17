# src/connectors/jira_connector.py
import os
from jira import JIRA
from typing import List, Optional
from src.models import JiraTicket

class JiraConnector:
    def __init__(self, server: str, email: str, token: str, project_key: str = None):
        self.server = server or os.getenv("JIRA_SERVER")
        self.email = email or os.getenv("JIRA_EMAIL")
        self.token = token or os.getenv("JIRA_TOKEN")
        self.project_key = project_key or os.getenv("JIRA_PROJECT_KEY")
        self.jira = None
        
        # For hackathon/testing purposes, if no token, we can use mock data
        if not token or token == "MOCK_TOKEN":
            self.mock_mode = True
        else:
            self.mock_mode = False
            try:
                self.jira = JIRA(server=self.server, basic_auth=(self.email, self.token))
            except Exception as e:
                print(f"Failed to connect to Jira: {e}. Falling back to mock mode.")
                self.mock_mode = True

    def get_tickets(self, status: Optional[str] = None) -> List[JiraTicket]:
        if self.mock_mode:
            tickets = [
                JiraTicket(key="SCRUM-1", summary="Deprecate old C API", status="Testing", description="Task for SCRUM-1"),
                JiraTicket(key="SCRUM-6", summary="Update documentation for ctypes", status="Done", description="Task for SCRUM-6"),
                JiraTicket(key="SCRUM-3", summary="Another testing task", status="Testing", description="Task for SCRUM-3"),
            ]
            if status:
                return [t for t in tickets if t.status.lower() == status.lower()]
            return tickets

        jql = f'project = "{self.project_key}"'
        if status:
            jql += f' AND status = "{status}"'
        
        issues = self.jira.search_issues(jql)
        return [JiraTicket(
            key=i.key,
            summary=i.fields.summary,
            status=i.fields.status.name,
            description=i.fields.description or "",
            assignee=i.fields.assignee.displayName if i.fields.assignee else None
        ) for i in issues]

    def get_ticket(self, key: str) -> Optional[JiraTicket]:
        if self.mock_mode:
            tickets = self.get_tickets()
            for t in tickets:
                if t.key == key:
                    return t
            return None
        
        try:
            issue = self.jira.issue(key)
            return JiraTicket(
                key=issue.key,
                summary=issue.fields.summary,
                status=issue.fields.status.name,
                description=issue.fields.description or "",
                assignee=issue.fields.assignee.displayName if issue.fields.assignee else None
            )
        except Exception:
            return None

    def create_ticket(self, summary: str, description: str) -> str:
        if self.mock_mode:
            print(f"Mock: Created Jira ticket for '{summary}'")
            return "SCRUM-MOCK-NEW"
        
        new_issue = self.jira.create_issue(
            project=self.project_key,
            summary=summary,
            description=description,
            issuetype={'name': 'Task'}
        )
        return new_issue.key
