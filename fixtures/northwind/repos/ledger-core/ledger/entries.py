from .models import Entry

_ENTRIES: dict[str, Entry] = {}


def post_entry(entry: Entry) -> Entry:
    if entry.id in _ENTRIES:
        return _ENTRIES[entry.id]
    _ENTRIES[entry.id] = entry
    return entry


def get_entry(entry_id: str) -> Entry | None:
    return _ENTRIES.get(entry_id)
