"""Internal spool entrypoint for the selected parser virtualenv."""
import sys
import os
from pathlib import Path

from packages.ir import strict_loads
from packages.parsers.spool import validate_request
from workers.parser.main import process_request


def main():
    request_path, source, output = map(Path, sys.argv[1:])
    request = validate_request(strict_loads(request_path.read_bytes()))
    if 'accelerator' in request:
        os.environ['PARSER_ACCELERATOR'] = request['accelerator']
    process_request(request, source, output)


if __name__ == '__main__':
    main()
