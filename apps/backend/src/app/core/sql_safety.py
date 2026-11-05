import re

# Strict allow-list for SQL identifiers (table names, column names)
# Must start with letter/underscore, contain only alphanumeric/underscore.
# No special chars, even quotes are risky if not handled perfectly.
# Regex: ^[A-Za-z_][A-Za-z0-9_]*$
IDENTIFIER_REGEX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Table names might include schema (e.g. public.users)
# Regex: ^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$
TABLE_REGEX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")

def validate_identifier(name: str, label: str = "Identifier") -> str:
    """
    Validate that a SQL identifier (column, etc) is safe.
    Raises ValueError if invalid.
    Returns the name if valid.
    """
    if not name or not IDENTIFIER_REGEX.match(name):
        raise ValueError(f"Invalid SQL {label}: '{name}'")
    return name

def validate_table_identifier(name: str, label: str = "Table Name") -> str:
    """
    Validate that a SQL table identifier is safe.
    Allows 'schema.table' format.
    Raises ValueError if invalid.
    Returns the name if valid.
    """
    if not name or not TABLE_REGEX.match(name):
        raise ValueError(f"Invalid SQL {label}: '{name}'")
    return name
