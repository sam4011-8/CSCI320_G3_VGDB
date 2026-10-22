"""Repository entry point for the Group 3 video game database CLI."""
try:
    from src.vgdb.cli import main
except ModuleNotFoundError as error:
    if error.name not in {'psycopg', 'argon2'}:
        raise
    raise SystemExit('Install the application dependencies: python -m pip install -r requirements.txt') from error

if __name__ == '__main__':
    raise SystemExit(main())
