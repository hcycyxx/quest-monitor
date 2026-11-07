"""Compatibility entry: delegate to the stable latest release launcher."""
from sidequest_latest import main
if __name__ == '__main__':
    raise SystemExit(main())
