# main.py
import argparse
import sys
import os
from dotenv import load_dotenv
from src.connectors.jira_connector import JiraConnector
from src.connectors.gdrive_connector import GDriveConnector
from src.ai.qa_engine import QAEngine

load_dotenv()

def main():
    parser = argparse.ArgumentParser(description="Python EOL/Deprecation Management Assistant")
    parser.add_argument("--jira-server", default=os.getenv("JIRA_SERVER"))
    parser.add_argument("--jira-email", default=os.getenv("JIRA_EMAIL"))
    parser.add_argument("--jira-token", default=os.getenv("JIRA_TOKEN"))
    parser.add_argument("--gdrive-creds", default=os.getenv("GDRIVE_CREDS", "credentials.json"), help="Path to Google Drive credentials JSON")
    parser.add_argument("--llm-provider", default=os.getenv("LLM_PROVIDER", "ollama"), choices=["ollama", "gemini", "mock"], help="LLM Provider")
    parser.add_argument("--llm-model", default=os.getenv("LLM_MODEL"), help="Model name (e.g. llama3, gemini-pro)")
    
    args = parser.parse_args()

    jira_conn = JiraConnector(args.jira_server, args.jira_email, args.jira_token)
    gdrive_conn = GDriveConnector(args.gdrive_creds)
    
    # Initialize LLM Client
    try:
        from src.ai.llm_client import create_llm_client
        llm_client = create_llm_client(args.llm_provider, args.llm_model)
    except Exception as e:
        print(f"Failed to initialize LLM client: {e}")
        sys.exit(1)

    engine = QAEngine(jira_conn, gdrive_conn, llm_client)

    print("=== Python EOL/Deprecation Assistant (Hackathon Edition) ===")
    print("Ask me anything about Python deprecations, Jira tickets, or the backlog.")
    print("Type 'quit' to exit.")
    
    while True:
        try:
            query = input("\nYour question: ")
            if query.lower() in ["quit", "exit", "q"]:
                break
            
            answer = engine.answer_query(query)
            print(f"\nAssistant: {answer}")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\nError: {e}")

if __name__ == "__main__":
    main()
