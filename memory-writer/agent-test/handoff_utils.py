def next_action(handoff: str) -> str:
    """Return the content of the 'Próxima ação' section of a HANDOFF.md text.

    The content is the first non-empty line after the 'Próxima ação' header
    (the header may be plain text or a Markdown heading like '## Próxima ação').
    Returns an empty string when the section is missing or empty.
    """
    lines = handoff.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lstrip("#").strip().lower() == "próxima ação":
            for next_line in lines[i + 1:]:
                if next_line.strip():
                    return next_line.strip()
            return ""
    return ""
