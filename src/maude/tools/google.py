"""
Google Workspace tools — lazy-import registrations for Gmail, Drive, Sheets,
Calendar, Slides, Contacts, YouTube.

The actual implementations are loaded on demand from google_tools module
(requires google-api-python-client).
"""

from ..tool_registry import register_tool


def _google_unavailable(service: str) -> str:
    return f"Error: Google {service} requires google-api-python-client. Install with: pip install maude[google]"


# ── Gmail ──────────────────────────────────────────────────────

@register_tool("gmail_list")
def _dispatch_gmail_list(args):
    try:
        from ..integrations.google_workspace import gmail_list_messages
        return gmail_list_messages(args.get("query", ""), args.get("max_results", 10))
    except ImportError:
        return _google_unavailable("Gmail")

@register_tool("gmail_read")
def _dispatch_gmail_read(args):
    try:
        from ..integrations.google_workspace import gmail_read_message
        return gmail_read_message(args.get("message_id", ""))
    except ImportError:
        return _google_unavailable("Gmail")

@register_tool("gmail_send")
def _dispatch_gmail_send(args):
    try:
        from ..integrations.google_workspace import gmail_send_message
        return gmail_send_message(args.get("to", ""), args.get("subject", ""), args.get("body", ""), args.get("cc"))
    except ImportError:
        return _google_unavailable("Gmail")


# ── Drive ──────────────────────────────────────────────────────

@register_tool("drive_list")
def _dispatch_drive_list(args):
    try:
        from ..integrations.google_workspace import drive_list_files
        return drive_list_files(args.get("query", ""), args.get("max_results", 20))
    except ImportError:
        return _google_unavailable("Drive")

@register_tool("drive_search")
def _dispatch_drive_search(args):
    try:
        from ..integrations.google_workspace import drive_search
        return drive_search(args.get("query", ""))
    except ImportError:
        return _google_unavailable("Drive")

@register_tool("drive_read")
def _dispatch_drive_read(args):
    try:
        from ..integrations.google_workspace import drive_read_file
        return drive_read_file(args.get("file_id", ""))
    except ImportError:
        return _google_unavailable("Drive")

@register_tool("drive_upload")
def _dispatch_drive_upload(args):
    try:
        from ..integrations.google_workspace import drive_upload_file
        return drive_upload_file(args.get("local_path", ""), args.get("folder_id"))
    except ImportError:
        return _google_unavailable("Drive")

@register_tool("drive_create_folder")
def _dispatch_drive_create_folder(args):
    try:
        from ..integrations.google_workspace import drive_create_folder
        return drive_create_folder(args.get("name", ""), args.get("parent_id"))
    except ImportError:
        return _google_unavailable("Drive")

@register_tool("drive_create_doc")
def _dispatch_drive_create_doc(args):
    try:
        from ..integrations.google_workspace import drive_create_doc
        return drive_create_doc(args.get("name", ""), args.get("folder_id"), args.get("folder_name"), args.get("content", ""))
    except ImportError:
        return _google_unavailable("Drive")

@register_tool("drive_create_sheet")
def _dispatch_drive_create_sheet(args):
    try:
        from ..integrations.google_workspace import drive_create_sheet
        return drive_create_sheet(args.get("name", ""), args.get("folder_id"), args.get("folder_name"))
    except ImportError:
        return _google_unavailable("Drive")

@register_tool("drive_update_doc")
def _dispatch_drive_update_doc(args):
    try:
        from ..integrations.google_workspace import drive_update_doc
        return drive_update_doc(args.get("doc_id", ""), args.get("content", ""), args.get("append", False))
    except ImportError:
        return _google_unavailable("Drive")

@register_tool("drive_delete")
def _dispatch_drive_delete(args):
    try:
        from ..integrations.google_workspace import drive_delete_file
        return drive_delete_file(args.get("file_id", ""))
    except ImportError:
        return _google_unavailable("Drive")


# ── Sheets ─────────────────────────────────────────────────────

@register_tool("sheets_read")
def _dispatch_sheets_read(args):
    try:
        from ..integrations.google_workspace import sheets_read
        return sheets_read(args.get("spreadsheet_id", ""), args.get("range", "Sheet1"))
    except ImportError:
        return _google_unavailable("Sheets")

@register_tool("sheets_write")
def _dispatch_sheets_write(args):
    try:
        from ..integrations.google_workspace import sheets_write
        return sheets_write(args.get("spreadsheet_id", ""), args.get("range", ""), args.get("values", []))
    except ImportError:
        return _google_unavailable("Sheets")

@register_tool("sheets_append")
def _dispatch_sheets_append(args):
    try:
        from ..integrations.google_workspace import sheets_append
        return sheets_append(args.get("spreadsheet_id", ""), args.get("range", ""), args.get("values", []))
    except ImportError:
        return _google_unavailable("Sheets")

@register_tool("sheets_create")
def _dispatch_sheets_create(args):
    try:
        from ..integrations.google_workspace import sheets_create
        return sheets_create(args.get("title", ""), args.get("folder_id"))
    except ImportError:
        return _google_unavailable("Sheets")

@register_tool("sheets_list_sheets")
def _dispatch_sheets_list_sheets(args):
    try:
        from ..integrations.google_workspace import sheets_list_sheets
        return sheets_list_sheets(args.get("spreadsheet_id", ""))
    except ImportError:
        return _google_unavailable("Sheets")

@register_tool("sheets_clear")
def _dispatch_sheets_clear(args):
    try:
        from ..integrations.google_workspace import sheets_clear
        return sheets_clear(args.get("spreadsheet_id", ""), args.get("range", ""))
    except ImportError:
        return _google_unavailable("Sheets")


# ── Calendar ───────────────────────────────────────────────────

@register_tool("calendar_list_events")
def _dispatch_calendar_list_events(args):
    try:
        from ..integrations.google_workspace import calendar_list_events
        return calendar_list_events(args.get("max_results", 10), args.get("time_min"), args.get("time_max"), args.get("calendar_id", "primary"))
    except ImportError:
        return _google_unavailable("Calendar")

@register_tool("calendar_create_event")
def _dispatch_calendar_create_event(args):
    try:
        from ..integrations.google_workspace import calendar_create_event
        return calendar_create_event(args.get("summary", ""), args.get("start", ""), args.get("end", ""),
                                      args.get("description"), args.get("location"), args.get("calendar_id", "primary"))
    except ImportError:
        return _google_unavailable("Calendar")

@register_tool("calendar_update_event")
def _dispatch_calendar_update_event(args):
    try:
        from ..integrations.google_workspace import calendar_update_event
        return calendar_update_event(args.get("event_id", ""), args.get("summary"), args.get("start"), args.get("end"),
                                      args.get("description"), args.get("location"), args.get("calendar_id", "primary"))
    except ImportError:
        return _google_unavailable("Calendar")

@register_tool("calendar_delete_event")
def _dispatch_calendar_delete_event(args):
    try:
        from ..integrations.google_workspace import calendar_delete_event
        return calendar_delete_event(args.get("event_id", ""), args.get("calendar_id", "primary"))
    except ImportError:
        return _google_unavailable("Calendar")

@register_tool("calendar_search_events")
def _dispatch_calendar_search_events(args):
    try:
        from ..integrations.google_workspace import calendar_search_events
        return calendar_search_events(args.get("query", ""), args.get("max_results", 10), args.get("calendar_id", "primary"))
    except ImportError:
        return _google_unavailable("Calendar")

@register_tool("calendar_list_calendars")
def _dispatch_calendar_list_calendars(args):
    try:
        from ..integrations.google_workspace import calendar_list_calendars
        return calendar_list_calendars()
    except ImportError:
        return _google_unavailable("Calendar")


# ── Slides, Contacts, YouTube — stub registrations ────────────

for _name in ("slides_get_presentation", "slides_get_slide", "slides_create_presentation",
              "slides_add_slide", "slides_add_text",
              "contacts_list", "contacts_get", "contacts_create", "contacts_update",
              "contacts_delete", "contacts_search",
              "youtube_search", "youtube_get_video", "youtube_get_channel",
              "youtube_list_playlists", "youtube_get_playlist_items", "youtube_create_playlist",
              "youtube_add_to_playlist", "youtube_get_comments", "youtube_post_comment",
              "youtube_my_channel"):
    def _make_stub(tool_name):
        @register_tool(tool_name)
        def _stub(args, _tn=tool_name):
            service = _tn.split("_")[0].title()
            try:
                from ..integrations import google_workspace
                fn = getattr(google_workspace, _tn, None)
                if fn:
                    return fn(**args)
            except ImportError:
                pass
            return _google_unavailable(service)
    _make_stub(_name)
