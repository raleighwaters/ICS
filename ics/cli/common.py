import requests
import sys
from operator import itemgetter

from ics.settings import settings


API_BASE = f"http://localhost:{settings.api_port}"

epilog_text = ''


def format_attribute(value: str):
    """Format attribute value."""
    if not value:
        return value
    return value[0].lower() + value[1:]

def check_response(response: requests.Response, exit_on_fail=True) -> bool:
    if response.status_code in (200, 201, 204):
        return True

    if response.status_code == 404:
        print("ERROR: " + response.json()["detail"])
        if exit_on_fail:
            sys.exit(1)
        return False

    print(f"Error: {response.status_code} {response.text}")
    if exit_on_fail:
        sys.exit(1)
    return False


def print_table(table, header=None, col_sort=0):
    """Print a pretty table"""
    # Determine column width
    max_col_width = {}  # Maximum character width for each column
    col_count = 0

    # Find maximum number of columns
    for row in table:
        row_len = len(row)
        if row_len > col_count:
            col_count = len(row)

    # Initialize maximum column length
    if header is not None:
        for col_num in range(col_count):
            max_col_width[col_num] = len(header[col_num])
    else:
        for col_num in range(col_count):
            max_col_width[col_num] = 0

    # Determine column width
    for row in table:
        for col_num in range(col_count):
            if max_col_width[col_num] < len(str(row[col_num])):
                max_col_width[col_num] = len(str(row[col_num]))

    # Sort table
    sorted_table = sorted(table, key=itemgetter(col_sort))

    # Print Header
    if header is not None:
        header_str = ''
        for col_num in range(col_count):
            header_str = header_str + header[col_num].ljust(max_col_width[col_num] + 4)

        print(header_str.strip(' '))
        print('-' * len(header_str))

    # Print table
    for row in sorted_table:
        table_row = ''
        for col_num in range(col_count):
            table_row = table_row + str(row[col_num]).ljust(max_col_width[col_num] + 4)
        print(table_row.strip(' '))
