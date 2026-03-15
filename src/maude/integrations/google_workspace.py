"""
Google Workspace integration stub.

Copy google_tools.py from the terminal-llm source to fully implement.
For now, provides placeholder functions that explain setup requirements.
"""


def _not_configured(service: str) -> str:
    return (
        f"Google {service} not yet configured. To set up:\n"
        "1. Create a Google Cloud project and enable APIs\n"
        "2. Download OAuth credentials to ~/.config/maude/google_credentials.json\n"
        "3. Run: maude --setup-google"
    )


def gmail_list_messages(query="", max_results=10):
    return _not_configured("Gmail")

def gmail_read_message(message_id=""):
    return _not_configured("Gmail")

def gmail_send_message(to="", subject="", body="", cc=None):
    return _not_configured("Gmail")

def drive_list_files(query="", max_results=20):
    return _not_configured("Drive")

def drive_search(query=""):
    return _not_configured("Drive")

def drive_read_file(file_id=""):
    return _not_configured("Drive")

def drive_upload_file(local_path="", folder_id=None):
    return _not_configured("Drive")

def drive_create_folder(name="", parent_id=None):
    return _not_configured("Drive")

def drive_create_doc(name="", folder_id=None, folder_name=None, content=""):
    return _not_configured("Drive")

def drive_create_sheet(name="", folder_id=None, folder_name=None):
    return _not_configured("Drive")

def drive_update_doc(doc_id="", content="", append=False):
    return _not_configured("Drive")

def drive_delete_file(file_id=""):
    return _not_configured("Drive")

def sheets_read(spreadsheet_id="", range="Sheet1"):
    return _not_configured("Sheets")

def sheets_write(spreadsheet_id="", range="", values=None):
    return _not_configured("Sheets")

def sheets_append(spreadsheet_id="", range="", values=None):
    return _not_configured("Sheets")

def sheets_create(title="", folder_id=None):
    return _not_configured("Sheets")

def sheets_list_sheets(spreadsheet_id=""):
    return _not_configured("Sheets")

def sheets_clear(spreadsheet_id="", range=""):
    return _not_configured("Sheets")

def calendar_list_events(max_results=10, time_min=None, time_max=None, calendar_id="primary"):
    return _not_configured("Calendar")

def calendar_create_event(summary="", start="", end="", description=None, location=None, calendar_id="primary"):
    return _not_configured("Calendar")

def calendar_update_event(event_id="", summary=None, start=None, end=None, description=None, location=None, calendar_id="primary"):
    return _not_configured("Calendar")

def calendar_delete_event(event_id="", calendar_id="primary"):
    return _not_configured("Calendar")

def calendar_search_events(query="", max_results=10, calendar_id="primary"):
    return _not_configured("Calendar")

def calendar_list_calendars():
    return _not_configured("Calendar")
